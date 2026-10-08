"""U1 guards and lifecycle. Reads and starts never call a model."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from . import records_jobs_repository as jobs
from . import repository
from .queue import queue_client
from .records_repository import QuestionStale, RecordsRepository
from .settings import get_settings
from .workspace_settings import resolve_workspace_model

QUEUE_NAME = "docgrain:records"
STAGES = ("discover", "accept_schema", "extract", "match", "merge", "publish")
LABELS = dict(zip(STAGES, (
    "Listeler bulunuyor", "Bilgi yapısı kontrol ediliyor", "Bilgiler çıkarılıyor",
    "Aynı kayıtlar karşılaştırılıyor", "Bilgiler birleştiriliyor", "Yayın hazırlanıyor",
), strict=True))
ERRORS = {
    "guard": "İşlem koşulları değişti; belgeleri ve model ayarlarını kontrol edin.",
    "source_changed": "Belgeler değişti; işlemi yeniden başlatın.",
    "publication_changed": "Yayın değişti; sayfayı yenileyin.",
    "schema_review": "Bilgi yapısı kontrol edilmeli.",
    "empty": "Yayınlanacak bilgi bulunamadı.",
    "incomplete": "Bilgilerin tamamı çıkarılamadı; işlemi yeniden başlatın.",
    "timeout": "İşlem süresi doldu; işlemi yeniden başlatın.",
    "worker_stale": "İşlem durdu; işlemi yeniden başlatın.",
    "dispatch": "İşlem başlatılamadı; yeniden deneyin.",
    "step_failed": "Bilgiler hazırlanamadı; yeniden deneyin.",
}
# A queue without a worker must also eventually become visibly terminal.
QUEUE_TIMEOUT = 300
HEARTBEAT_TIMEOUT = 90
STAGE_TIMEOUTS = dict(zip(STAGES, (1800, 120, 3600, 600, 600, 300), strict=True))


class JobConflict(RuntimeError):
    def __init__(self, code="guard"):
        self.code = code
        super().__init__(ERRORS[code])


def now():
    return datetime.now(UTC).isoformat()


def pack_store():
    root = get_settings().records_publication_root
    if not root:
        raise JobConflict()
    return RecordsRepository(root)


def source_snapshot(workspace):
    """Pin current prepared documents and canonical heads, without model or HTTP I/O."""
    from .routers.knowledge import latest_knowledge

    if get_settings().use_fixtures:
        raise JobConflict()
    documents = sorted((d for d in repository.list_documents() if d.workspace_id == workspace),
                       key=lambda d: d.id)
    if not documents:
        raise JobConflict()
    pins = []
    for doc in documents:
        version = repository.get_version(doc.id, doc.latest_version_id)
        preparation = repository.job_for_version(doc.latest_version_id)
        if (not version or version.status != "done" or version.workspace_id != workspace
                or not preparation or preparation.status != "done" or preparation.page_failures):
            raise JobConflict()
        try:
            snapshot = latest_knowledge(doc.id).snapshot
        except Exception:  # noqa: BLE001 - fail closed without exposing storage errors.
            raise JobConflict() from None
        source = snapshot.source_version
        if (source.workspace_id != workspace or source.document_id != doc.id
                or source.content_sha256 != version.content_sha256
                or snapshot.metadata.get("structural_parse", {}).get("issues")):
            raise JobConflict()
        pins.append({"document_id": doc.id, "document_version_id": version.id,
                     "source_version_id": source.id,
                     "knowledge_revision_id": snapshot.knowledge_revision.id,
                     "content_sha256": source.content_sha256})
    return pins


def head(store, workspace):
    revisions = store.list_revisions(workspace)
    return revisions[0] if revisions else None


def has_accepted(store, workspace):
    revision_id = head(store, workspace)
    return bool(revision_id and any(c.review_state == "accepted"
                for r in store._source(workspace, revision_id).records
                for f in r.fields.values() for c in f.candidates))


def expired(job, at=None):
    at = at or datetime.now(UTC)
    if job["status"] not in jobs.ACTIVE:
        return None
    if job["status"] == "queued":
        if at > datetime.fromisoformat(job["queued_at"]) + timedelta(seconds=QUEUE_TIMEOUT):
            return "worker_stale"
    elif job.get("stage_deadline") and at > datetime.fromisoformat(job["stage_deadline"]):
        return "timeout"
    elif at > datetime.fromisoformat(job["heartbeat_at"]) + timedelta(seconds=HEARTBEAT_TIMEOUT):
        return "worker_stale"
    return None


def finish(workspace, job_id, code=None, revision_id=None):
    def mutate(job):
        job.update(status=("needs_review" if code == "schema_review" else "failed") if code else "done",
                   error_code=code, message=ERRORS[code] if code else
                   "Bilgiler hazır; onay bekleyenleri Sorular'dan kontrol edin",
                   revision_id=revision_id, finished_at=now())
        if job["stage"]:
            stage = job["stages"][job["stage"]]
            stage.update(status=job["status"] if code else "done", finished_at=now())
        if not code:
            job["completed_stages"] = 6
    return jobs.change(workspace, job_id, mutate)


def reap_locked(workspace):
    """Caller holds publication/answer lock; a stale child cannot publish after this fence."""
    job = jobs.active(workspace)
    if job and (code := expired(job)):
        finish(workspace, job["job_id"], code)


def start(workspace, request_id):
    if get_settings().use_fixtures:
        raise JobConflict()
    store = pack_store()
    with store._workspace_lock(workspace):
        reap_locked(workspace)
        existing = jobs.requested(workspace, request_id) or jobs.active(workspace)
        if existing:
            jobs.remember_request(workspace, request_id, existing["job_id"])
            return existing["job_id"]
        resolved = resolve_workspace_model(workspace)
        pins = source_snapshot(workspace)
        if has_accepted(store, workspace):
            raise JobConflict("publication_changed")
        stamp = now()
        job = {"job_id": "records_" + uuid4().hex, "workspace_id": workspace,
               "request_id": request_id, "status": "queued", "stage": None,
               "completed_stages": 0, "total_stages": 6, "message": "İşlem sırada",
               "revision_id": None, "error_code": None, "queued_at": stamp,
               "updated_at": stamp, "started_at": None, "finished_at": None,
               "heartbeat_at": stamp, "stage_deadline": None,
               "settings_version": resolved.settings_version, "sources": pins,
               "publication_head": head(store, workspace), "metadata": {},
               "stages": {stage: {"status": "pending", "started_at": None, "finished_at": None}
                          for stage in STAGES}}
        jobs.create(job)
        try:
            queue_client().lpush(QUEUE_NAME, job["job_id"])
        except Exception:  # noqa: BLE001 - durable terminal dispatch failure, no provider text.
            finish(workspace, job["job_id"], "dispatch")
            raise JobConflict("dispatch") from None
        return job["job_id"]


def read(workspace, job_id=None):
    if get_settings().use_fixtures:
        return None
    with pack_store()._workspace_lock(workspace):
        reap_locked(workspace)
        return jobs.get(workspace, job_id) if job_id else jobs.latest(workspace)


def block_answer(workspace):
    """Called by the production review adapter inside the same workspace lock as start."""
    if get_settings().use_fixtures:
        raise QuestionStale("Örnek görünümde bilgiler değiştirilemez.")
    reap_locked(workspace)
    if jobs.active(workspace):
        raise QuestionStale("Bilgiler hazırlanıyor; işlem bitince cevaplayın.")
