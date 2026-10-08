"""Network-free U1 API double using the real request and publication contracts.

Values below are deliberately independent of golden.json, the smoke test oracle.
This simulates HTTP orchestration, not parser or model quality.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default

import httpx
from docgrain_api.records_jobs import STAGES
from docgrain_api.routers.documents import RegisterRequest, RegisterResponse
from docgrain_api.routers.record_jobs import StartJob
from docgrain_api.routers.try_ai import Question
from docgrain_api.routers.workspace_settings import WorkspaceCreate
from docgrain_api.workspace_settings import ModelUpdate
from docgrain_domain import Document, DocumentVersion, Job, JobStatus, VersionStatus
from docgrain_records.discovery_models import WorkspaceSchema
from docgrain_records.export import project_records
from docgrain_records.merge_models import MergeRevision
from docgrain_records.review import CandidateAnswer, answer_revision, questions, summary


class FakeAPI:
    def __init__(self, fixtures, fault=None):
        self.fixtures, self.fault = fixtures, fault
        self.workspace = "ws_synthetic"
        self.enabled = False
        self.documents, self.versions, self.jobs = {}, {}, {}
        self.uploads, self.requests = {}, []
        self.revision = None
        self.polls = 0
        self.issued = {}

    def build_revision(self):
        pins, by_name = [], {}
        for doc in self.documents.values():
            pin = {"document_id": doc.id, "document_name": doc.filename,
                   "source_version_id": doc.latest_version_id,
                   "knowledge_revision_id": "knowledge_" + doc.id}
            pins.append(pin)
            by_name[doc.filename] = pin

        def candidate(key, value, filename, quote):
            pin = by_name[filename]
            return {"id": key, "value": value, "lang": "tr", "review_state": "needs_review",
                    "evidence": [{k: v for k, v in pin.items() if k != "document_name"}
                                 | {"locator": "§1", "quote": quote}]}

        def field(*candidates):
            return {"primary_lang": "tr", "candidates": list(candidates)}

        room = {"name": field(candidate("room_name", "Bahçe Odası", "odalar.txt", "Bahçe Odası")),
                "size_m2": field(candidate("size32", 32, "odalar.txt", "Büyüklük: 32 m2"),
                                 candidate("size36", 36, "hizmetler.txt", "Büyüklük: 36 m2")),
                "capacity": field(candidate("capacity", 2, "odalar.txt", "Kapasite: 2 kişi"))}
        service = {"name": field(candidate("service_name", "Danışma", "hizmetler.txt", "Danışma")),
                   "hours": field(candidate("hours", "08:00–20:00", "hizmetler.txt",
                                            "Çalışma saatleri: 08:00–20:00"))}
        labels = [{"lang": "en", "value": "Items"}, {"lang": "tr", "value": "Bilgiler"}]
        collections = []
        for key, fields in (("rooms", room), ("services", service)):
            collections.append({"key": key, "identity": "name", "label_i18n": labels,
                                "description": "Synthetic company records.", "review_state": "accepted",
                                "fields": [{"key": name, "type": "number" if name in {
                                    "size_m2", "capacity"} else "string", "unit": None, "label_i18n": labels,
                                    "review_state": "accepted"} for name in fields],
                                "examples": [{"values": [{"key": name,
                                    "value": f["candidates"][0]["value"], "lang": "tr",
                                    "evidence": [{k: v for k, v in f["candidates"][0]["evidence"][0].items()
                                                  if k in {"document_id", "quote", "locator"}}]}
                                    for name, f in fields.items()]}]})
        schema = WorkspaceSchema(workspace_id=self.workspace, version=1, review_state="accepted",
                                 sources=[], collections=collections)
        self.revision = MergeRevision.model_validate({
            "workspace_id": self.workspace, "id": "rev_initial", "documents": pins,
            "workspace_schema": schema.model_dump(mode="json"),
            "records": [{"id": "room", "type": "rooms", "fields": room},
                        {"id": "service", "type": "services", "fields": service}],
        })

    def handle(self, request):
        method, path = request.method, request.url.path
        self.requests.append((method, path))
        body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else None

        def reply(value, status=200):
            return httpx.Response(status, json=value)

        if (method, path) == ("POST", "/v1/workspaces"):
            WorkspaceCreate.model_validate(body)
            return reply({"id": self.workspace, "name": body["name"], "documents": 0}, 201)
        if (method, path) == ("POST", "/v1/documents"):
            payload = RegisterRequest.model_validate(body)
            assert payload.workspace_id == self.workspace
            data = (self.fixtures / payload.filename).read_bytes()
            assert payload.byte_size == len(data) and payload.content_sha256 == hashlib.sha256(data).hexdigest()
            index = len(self.documents) + 1
            doc_id, version_id, job_id = f"doc_{index}", f"version_{index}", f"job_{index}"
            now = datetime.now(UTC)
            doc = Document(id=doc_id, workspace_id=self.workspace, title=payload.filename,
                           filename=payload.filename, mime_type=payload.mime_type,
                           latest_version_id=version_id, version_count=1, created_at=now, updated_at=now)
            version = DocumentVersion(id=version_id, document_id=doc_id, workspace_id=self.workspace,
                                      revision=1, content_sha256=payload.content_sha256,
                                      source_uri=f"uploads/{self.workspace}/{doc_id}/{version_id}",
                                      byte_size=payload.byte_size, created_at=now)
            job = Job(id=job_id, document_id=doc_id, document_version_id=version_id,
                      workspace_id=self.workspace, stages=[], queued_at=now)
            self.documents[doc_id], self.versions[version_id], self.jobs[job_id] = doc, version, job
            registration = RegisterResponse(document=doc, version=version, job_id=job_id,
                                            upload_url=f"http://u1.invalid/v1/documents/{doc_id}/versions/{version_id}/content")
            return reply(registration.model_dump(mode="json"), 202)
        match = re.fullmatch(r"/v1/documents/(doc_\d+)/versions/(version_\d+)/(content|uploaded)", path)
        if match:
            doc_id, version_id, action = match.groups()
            doc, version = self.documents[doc_id], self.versions[version_id]
            assert version.document_id == doc_id
            if method == "PUT" and action == "content":
                message = BytesParser(policy=default).parsebytes(
                    f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.content)
                part, = message.iter_parts()
                assert part.get_filename() == doc.filename
                data = part.get_payload(decode=True)
                assert data == (self.fixtures / doc.filename).read_bytes()
                self.uploads[doc.filename] = data
                return reply({"status": "stored", "object_name": version.source_uri}, 201)
            if method == "POST" and action == "uploaded":
                assert doc.filename in self.uploads
                job = next(j for j in self.jobs.values() if j.document_version_id == version_id)
                job.status = JobStatus.DONE
                version.status, version.page_count = VersionStatus.DONE, 1
                return reply({"job_id": job.id, "status": "queued"}, 202)
        if method == "GET" and path.startswith("/v1/jobs/"):
            return reply(self.jobs[path.rsplit("/", 1)[1]].model_dump(mode="json"))
        if method == "GET" and path.startswith("/v1/versions/"):
            return reply(self.versions[path.rsplit("/", 1)[1]].model_dump(mode="json"))
        prefix = f"/v1/workspaces/{self.workspace}"
        assert path.startswith(prefix), f"Unexpected fake route: {method} {path}"
        suffix = path.removeprefix(prefix)
        if (method, suffix) == ("GET", "/model/profiles"):
            return reply([{"id": "synthetic", "label": "Sentetik bağlantı", "ready": True}])
        if (method, suffix) == ("PUT", "/model"):
            model = ModelUpdate.model_validate(body)
            assert model.credential_id == "synthetic"
            self.enabled = model.enabled
            return reply(model.model_dump() | {"credential_ready": True, "settings_version": 1})
        if (method, suffix) == ("POST", "/record-jobs"):
            StartJob.model_validate(body)
            if not self.enabled:
                return reply({"detail": "Model kapalı."}, 409)
            assert len(self.uploads) == 2
            self.build_revision()
            return reply({"job_id": "records_synthetic"}, 202)
        if (method, suffix) == ("GET", "/record-jobs/records_synthetic"):
            self.polls += 1
            status = "running" if self.polls == 1 else "done"
            if self.fault in {"job_failed", "job_needs_review"} and self.polls > 1:
                status = self.fault.removeprefix("job_")
            if self.fault == "job_timeout":
                status = "running"
            stage = "publish" if status == "done" else "discover"
            now = datetime.now(UTC).isoformat()
            return reply({"job_id": "records_synthetic", "workspace_id": self.workspace,
                          "status": status, "stage": stage, "completed_stages": 6 if status == "done" else 0,
                          "total_stages": 6, "message": "Sentetik işlem", "revision_id": self.revision.id
                          if status == "done" else None, "error_code": "dispatch" if status == "failed" else None,
                          "updated_at": now, "queued_at": now, "started_at": now,
                          "finished_at": now if status == "done" else None,
                          "stages": {s: {"status": "done" if status == "done" else "pending",
                                         "started_at": None, "finished_at": None} for s in STAGES}})
        if (method, suffix) == ("GET", "/summary"):
            result = summary(self.revision, datetime.now(UTC).isoformat())
            if self.fault == "unsupported":
                result["unsupported_fields"] = 1
            return reply(result)
        if (method, suffix) == ("GET", "/questions"):
            items = questions(self.revision)
            for item in items:
                self.issued[item["id"]] = self.revision.id
            offset, limit = int(request.url.params.get("offset", 0)), int(request.url.params.get("limit", 20))
            return reply({"total": len(items), "items": items[offset:offset + limit]})
        if method == "POST" and re.fullmatch(r"/questions/q_\w+/answer", suffix):
            answer = CandidateAnswer.model_validate(body)
            question_id = suffix.split("/")[2]
            if self.issued.get(question_id) != self.revision.id:
                return reply({"detail": "Soruları yenileyin."}, 409)
            if self.fault == "wrong_value" and answer.candidate_id == "size32":
                answer = CandidateAnswer(candidate_id="size36")
            self.revision = answer_revision(self.revision, question_id, answer)
            return reply({"revision_id": self.revision.id, "remaining": len(questions(self.revision))})
        match = re.fullmatch(r"/revisions/(rev_\w+)/collections/(rooms|services)", suffix)
        if method == "GET" and match:
            revision, collection = match.groups()
            assert revision == self.revision.id
            return reply(project_records(self.revision, request.url.params.get("lang"),
                                         request.url.params.get("mode", "preview"))[collection])
        if (method, suffix) == ("POST", "/ai/ask"):
            question = Question.model_validate(body).question
            if not self.enabled:
                return reply({"detail": "Model kapalı."}, 409)
            sources = []
            known = question == "Bahçe Odası kaç metrekare ve kaç kişilik?"
            if known or self.fault == "invented_unknown_source":
                room = self.revision.records[0]
                for name in ("size_m2", "capacity"):
                    candidate = room.fields[name].accepted("tr")
                    evidence = candidate.evidence[0].model_dump(mode="json")
                    sources.append(evidence | {"id": f"source_{name}", "document_name": "odalar.txt"})
            if self.fault == "missing_sources" and known:
                sources = []
            return reply({"answer": "Bahçe Odası 32 m2 ve 2 kişiliktir." if known else "Bilmiyorum.",
                          "abstained": not known, "workspace_id": self.workspace,
                          "revision_id": self.revision.id, "mode": "approved", "sources": sources})
        raise AssertionError(f"Unexpected fake route: {method} {path}")
