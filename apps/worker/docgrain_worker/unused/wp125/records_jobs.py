# KULLANILMIYOR (karar 18, WP125): güncelleme öncesi tam kopya (apps/api/docgrain_api/records_jobs.py); içe aktarılmaz.
"""U1 guards and lifecycle. Reads and starts never call a model."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from docgrain_records.auto_accept import human_accepted
from docgrain_records.discovery_models import WorkspaceSchema

from . import records_jobs_repository as jobs
from . import repository
from .queue import queue_client
from .records_repository import QuestionStale, RecordsRepository
from .settings import get_settings
from .workspace_settings import get_workspace_model, resolve_workspace_model

QUEUE_NAME = "docgrain:records"
# WP119 (karar 21): "structure" builds collections from Docling tables/lists before any model.
STAGES = ("structure", "discover", "accept_schema", "extract", "match", "merge", "publish")
FILL_STAGES = ("fill", "publish")
FILL_LABELS = {"fill": "Yeni alan belgelerden dolduruluyor", "publish": "Yayın hazırlanıyor"}
FILL_STAGE_TIMEOUTS = {"fill": 3600, "publish": 300}
FILL_FALLBACK = "Alan eklendi; belgelerden doldurulamadı. Değerleri elle girebilirsiniz."
FILL_QUEUED = "Alan eklendi; değerler belgelerden aranıyor."
FILL_MODEL_OFF = "Model kapalı; alanı elle doldurabilirsiniz."
LABELS = dict(zip(STAGES, (
    "Tablolar ve listeler okunuyor", "Listeler bulunuyor", "Bilgi yapısı kontrol ediliyor",
    "Bilgiler çıkarılıyor", "Aynı kayıtlar karşılaştırılıyor", "Bilgiler birleştiriliyor",
    "Yayın hazırlanıyor",
), strict=True))
# KULLANILMIYOR (karar 18, WP119): yapı aşamasından önceki altı aşama.
_STAGES_BEFORE_WP119 = ("discover", "accept_schema", "extract", "match", "merge", "publish")
ERRORS = {
    "guard": "İşlem koşulları değişti; belgeleri ve model ayarlarını kontrol edin.",
    "source_changed": "Belgeler değişti; işlemi yeniden başlatın.",
    "publication_changed": "Yayın değişti; sayfayı yenileyin.",
    "schema_review": "Bilgi yapısı kontrol edilmeli.",
    "empty": "Yayınlanacak bilgi bulunamadı.",
    # KULLANILMIYOR (karar 18, WP110): işi artık reddedilen alan ya da tek başarısız bölüm durdurmuyor.
    "incomplete": "Bilgilerin tamamı çıkarılamadı; işlemi yeniden başlatın.",
    "sections_failed": "Belge bölümlerinin yüzde 20'sinden fazlası okunamadı; model bağlantısını "
                       "kontrol edip işlemi yeniden başlatın.",
    "timeout": "İşlem süresi doldu; işlemi yeniden başlatın.",
    "worker_stale": "İşlem durdu; işlemi yeniden başlatın.",
    "dispatch": "İşlem başlatılamadı; yeniden deneyin.",
    "step_failed": "Bilgiler hazırlanamadı; yeniden deneyin.",
    # WP119: model kapalı ve belgelerde okunabilir tablo/liste yok.
    "needs_model": "Belgelerde tablo ya da liste bulunamadı; bilgileri çıkarmak için Ayarlar'dan "
                   "model seçip açın.",
}
# A queue without a worker must also eventually become visibly terminal.
QUEUE_TIMEOUT = 300
HEARTBEAT_TIMEOUT = 90
# WP110: more failed sections than this (after one more try) fail the job.
MAX_FAILED_SECTIONS_PERCENT = 20
STAGE_TIMEOUTS = dict(zip(STAGES, (600, 1800, 120, 3600, 600, 600, 300), strict=True))


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


PREPARING = {"queued", "running"}
USABLE = {"done", "partial"}


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
        if not version or version.workspace_id != workspace or not preparation:
            raise JobConflict()
        # Documents still being prepared block the job: their content is not pinned yet.
        if version.status in PREPARING or preparation.status in PREPARING:
            raise JobConflict()
        # A failed document is skipped, not fatal for the whole company. Partial documents are used: the
        # readable part carries verified evidence, and pages Docling graded low stay visible in the report.
        if version.status not in USABLE or preparation.status not in USABLE:
            continue
        try:
            snapshot = latest_knowledge(doc.id).snapshot
        except Exception:  # noqa: BLE001 - fail closed without exposing storage errors.
            raise JobConflict() from None
        source = snapshot.source_version
        # Reading issues (low-grade pages, downscaled images) are reported, not blocking.
        if (source.workspace_id != workspace or source.document_id != doc.id
                or source.content_sha256 != version.content_sha256):
            raise JobConflict()
        pins.append({"document_id": doc.id, "document_version_id": version.id,
                     "source_version_id": source.id,
                     "knowledge_revision_id": snapshot.knowledge_revision.id,
                     "content_sha256": source.content_sha256})
    if not pins:
        raise JobConflict()
    return pins


def head(store, workspace):
    revisions = store.list_revisions(workspace)
    return revisions[0] if revisions else None


def has_accepted(store, workspace):
    """A person's acceptance on the head; a new job must not overwrite it (karar 20: rules don't count)."""
    revision_id = head(store, workspace)
    return bool(revision_id and human_accepted(store._source(workspace, revision_id)))


# KULLANILMIYOR (karar 18, WP111): kural onayları (karar 20) da sayılıp her yeni işi engelliyordu.
def _has_accepted_before_wp111(store, workspace):
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
                   ("Yeni alan dolduruldu; onay bekleyenleri Sorular'dan kontrol edin"
                    if job.get("kind") == "field_fill" else
                    "Bilgiler hazır; onay bekleyenleri Sorular'dan kontrol edin"),
                   revision_id=revision_id, finished_at=now())
        if job["stage"]:
            stage = job["stages"][job["stage"]]
            stage.update(status=job["status"] if code else "done", finished_at=now())
        if not code:
            job["completed_stages"] = job["total_stages"]
    return jobs.change(workspace, job_id, mutate)


def summary(job):
    """Plain notes for a job, from metadata counts only: no source text, model output or secrets."""
    metadata = job.get("metadata") or {}
    rejected = sum(count for reasons in (metadata.get("rejected_fields") or {}).values()
                   for count in reasons.values())
    failed = len(metadata.get("failed_sections") or [])
    review = list(dict.fromkeys(item["label"] for item in metadata.get("schema_needs_review") or []))
    notes = []
    if rejected:
        notes.append(f"{rejected} alan doğrulanamadığı için alınmadı")
    if failed:
        notes.append(f"{failed} bölüm okunamadı")
    if review:
        notes.append("İncelenmeyi bekleyen yapı: " + ", ".join(review))
    # WP119: where the records came from, and documents the model would still have to read.
    structure = metadata.get("structure") or {}
    if structure.get("records_from_structure"):
        notes.append(f"{structure['records_from_structure']} kayıt belgelerdeki tablo ve "
                     "listelerden alındı")
    waiting = [item.get("filename") or item.get("document_id")
               for item in structure.get("documents_without_model") or []]
    if waiting:
        notes.append("Şu belgelerdeki yazılı bilgiler için Ayarlar'dan model açılmalı: "
                     + ", ".join(waiting))
    return {"rejected_fields": rejected, "failed_sections": failed,
            "total_sections": (metadata.get("extraction_sections") or {}).get("total", 0),
            "needs_review": review, "notes": notes}


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
        active = jobs.active(workspace)
        if active and active.get("kind") == "field_fill":
            raise JobConflict("publication_changed")
        existing = jobs.requested(workspace, request_id) or active
        if existing:
            jobs.remember_request(workspace, request_id, existing["job_id"])
            return existing["job_id"]
        # WP119 (karar 21): with the model off the job still runs on document structure only;
        # a model that is switched on but not ready still blocks the start.
        model = get_workspace_model(workspace)
        if model.get("enabled"):
            resolved = resolve_workspace_model(workspace)
            settings_version, model_enabled = resolved.settings_version, True
        else:
            settings_version, model_enabled = int(model["settings_version"]), False
        pins = source_snapshot(workspace)
        if has_accepted(store, workspace):
            raise JobConflict("publication_changed")
        stamp = now()
        job = {"job_id": "records_" + uuid4().hex, "workspace_id": workspace,
               "request_id": request_id, "status": "queued", "stage": None,
               "completed_stages": 0, "total_stages": len(STAGES), "message": "İşlem sırada",
               "revision_id": None, "error_code": None, "queued_at": stamp,
               "updated_at": stamp, "started_at": None, "finished_at": None,
               "heartbeat_at": stamp, "stage_deadline": None,
               "settings_version": settings_version, "model_enabled": model_enabled,
               "sources": pins,
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
    active = jobs.active(workspace)
    if active and active.get("kind") == "field_fill":
        raise QuestionStale("Yeni alan dolduruluyor; bitince tekrar deneyin.")
    if active:
        raise QuestionStale("Bilgiler hazırlanıyor; işlem bitince cevaplayın.")


def context_job(store, revision):
    """Walk publication ancestry without reading document contexts in the API."""
    ancestor = revision.parent_id
    while ancestor:
        manifest = store.manifest(revision.workspace_id, ancestor)
        job_id = manifest.get("record_job_id")
        if job_id:
            job = jobs.get(revision.workspace_id, job_id)
            if not job or job.get("kind") != "field_fill":
                return job_id
        ancestor = store._source(revision.workspace_id, ancestor).parent_id
    return None


def prepare_field_fill(store, revision, collection, field):
    """Plan a field job under the workspace lock, without DB, queue or model I/O."""
    workspace = revision.workspace_id
    if not get_workspace_model(workspace)["enabled"]:
        return None, FILL_MODEL_OFF
    try:
        if get_settings().use_fixtures:
            return None, FILL_FALLBACK
        resolved = resolve_workspace_model(workspace)
        schema = WorkspaceSchema.model_validate(revision.workspace_schema)
        definition = next(item for item in schema.collections if item.key == collection)
        pinned = context_job(store, revision)
        if field == definition.identity or not schema.sources or not pinned:
            return None, FILL_FALLBACK
        stamp = now()
        job_id = "records_" + uuid4().hex
        job = {"job_id": job_id, "workspace_id": workspace, "request_id": job_id,
               "kind": "field_fill", "collection": collection, "field": field,
               "base_revision_id": revision.id, "context_job_id": pinned,
               "status": "queued", "stage": None, "completed_stages": 0,
               "total_stages": len(FILL_STAGES), "message": "İşlem sırada",
               "revision_id": None, "error_code": None, "queued_at": stamp,
               "updated_at": stamp, "started_at": None, "finished_at": None,
               "heartbeat_at": stamp, "stage_deadline": None,
               "settings_version": resolved.settings_version, "model_enabled": True,
               "sources": [], "publication_head": revision.id, "metadata": {},
               "stages": {stage: {"status": "pending", "started_at": None, "finished_at": None}
                          for stage in FILL_STAGES}}
    except Exception:  # noqa: BLE001 - schema succeeds even if job preparation is unavailable.
        return None, FILL_FALLBACK
    return job, FILL_QUEUED


def dispatch_field_fill(job):
    """The empty field revision is already published; persist and queue its job."""
    created = False
    try:
        jobs.create(job)
        created = True
        queue_client().lpush(QUEUE_NAME, job["job_id"])
    except Exception:  # noqa: BLE001 - never expose DB, queue or provider exception text.
        if created:
            try:
                finish(job["workspace_id"], job["job_id"], "dispatch")
            except Exception:  # noqa: BLE001 - the field is published; GET reaps a stale row.
                return False
        return False
    return True


def field_fill_note(workspace, change):
    """Resolve the current user-facing note without changing an immutable revision."""
    try:
        job = jobs.get(workspace, change.fill_job_id)
    except Exception:  # noqa: BLE001 - a schema read must not fail on job storage; keep the stored note.
        return change.note
    if job and job["status"] in jobs.ACTIVE:
        return FILL_QUEUED
    if job and job["status"] == "done":
        return change.note
    return FILL_FALLBACK
