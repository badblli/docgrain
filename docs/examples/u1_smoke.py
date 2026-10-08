"""Repeat the U1 walk; offline by default, live only with explicit model settings."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "packages/ingestion"), str(ROOT / "packages/domain"),
               str(ROOT / "packages/records"), str(ROOT / "packages/access"),
               str(ROOT / "apps/api"), str(Path(__file__).parent)]

from docgrain_ingest.cli import ingest_folder

FIXTURES = ROOT / "tests/fixtures/u1-company"
STEPS = (
    "Çalışma alanı oluştur", "Model kapalıyken işlemleri dene", "Belgeleri yükle",
    "Hazır bağlantıyı seç ve modeli aç", "Bilgileri çıkar ve yayını bekle",
    "İlk özeti ve çelişkiyi kontrol et", "Soruları doğru değerlerle yanıtla",
    "Onaylı bilgileri doğruluk anahtarıyla karşılaştır", "Kaynaklı yanıtı ve bilinmeyeni dene",
)


class SmokeFailure(Exception):
    """Only locally written, credential-free reasons may reach the report."""


def require(condition, reason):
    if not condition:
        raise SmokeFailure(reason)


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def same_value(actual, expected):
    # Discovery may represent size as a number (unit belongs to the schema).
    expected = normalized(expected)
    if re.fullmatch(r"\d+(?:\.\d+)?(?: m2)?", expected):
        actual = normalized(actual)
        if re.fullmatch(r"\d+(?:\.\d+)?(?: m2)?", actual):
            return float(actual.removesuffix(" m2")) == float(expected.removesuffix(" m2"))
    return normalized(actual).replace("–", "-") == expected.replace("–", "-")


def request(client, method, path, status=200, **kwargs):
    response = client.request(method, path, **kwargs)
    require(response.status_code == status, f"HTTP {response.status_code}; beklenen {status}.")
    return response.json()


class Report:
    def __init__(self):
        self.steps = []
        self.workspace_id = None
        self.duration = 0.0

    @property
    def passed(self):
        return len(self.steps) == len(STEPS) and all(s["status"] == "pass" for s in self.steps)

    def write(self, output):
        data = {"status": "pass" if self.passed else "fail", "duration": self.duration,
                "workspace_id": self.workspace_id, "steps": self.steps}
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
        lines = ["# U1 yürüyüş raporu", "", f"Sonuç: {'GEÇTİ' if self.passed else 'KALDI'}",
                 f"Toplam süre: {self.duration:.2f} s", f"Çalışma alanı: {self.workspace_id}", "",
                 "| Adım | Sonuç | Süre (s) | Açıklama |", "| --- | --- | --- | --- |"]
        labels = {"pass": "GEÇTİ", "fail": "KALDI", "blocked": "ENGELLENDİ"}
        for step in self.steps:
            label = labels[step["status"]]
            print(f"[{label}] {step['step']} ({step['duration']:.2f} s): {step['reason']}")
            lines.append(f"| {step['step']} | {label} | {step['duration']:.2f} | {step['reason']} |")
        (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Sonuç: {'GEÇTİ' if self.passed else 'KALDI'} ({self.duration:.2f} s)")


class Walk:
    def __init__(self, client, fixtures, output, *, credential_id, base_url, model,
                 timeout, poll_interval):
        self.client, self.fixtures, self.output = client, fixtures, output
        self.settings = {"enabled": True, "credential_id": credential_id,
                         "base_url": base_url, "model": model}
        self.timeout, self.poll_interval = timeout, poll_interval
        self.report = Report()
        self.golden = None
        self.documents = {}
        self.revision = None

    def api(self, method, suffix, status=200, **kwargs):
        return request(self.client, method, f"/v1/workspaces/{self.report.workspace_id}{suffix}",
                       status, **kwargs)

    def create(self):
        self.golden = json.loads((self.fixtures / "golden.json").read_text(encoding="utf-8"))
        for name, source in self.golden["sources"].items():
            require(Path(name).name == name, "Kaynak adı tek bir dosya adı olmalı.")
            digest = hashlib.sha256((self.fixtures / name).read_bytes()).hexdigest()
            require(digest == source["sha256"].lower(), "Örnek belge doğruluk anahtarıyla eşleşmiyor.")
        workspace = request(self.client, "POST", "/v1/workspaces", 201,
                            json={"name": "U1 Sentetik Şirket " + uuid4().hex[:8]})
        require(bool(workspace["id"]), "Çalışma alanı kimliği eksik.")
        self.report.workspace_id = workspace["id"]

    def model_off(self):
        self.api("POST", "/ai/ask", 409, json={"question": self.golden["questions"][0]["question"]})
        self.api("POST", "/record-jobs", 409, json={"request_id": "off_" + uuid4().hex})

    def upload(self):
        # ingest_folder supports TXT; README/golden/reports must never enter the source bundle.
        with tempfile.TemporaryDirectory(prefix="u1-sources-") as folder:
            for name in self.golden["sources"]:
                shutil.copyfile(self.fixtures / name, Path(folder) / name)
            result = ingest_folder(Path(folder), self.report.workspace_id, self.client,
                                   report_path=self.output / "ingest-report.json",
                                   timeout=self.timeout, poll_interval=self.poll_interval)
        require({r["file"] for r in result["files"]} == set(self.golden["sources"]),
                "Yüklenen belge listesi doğruluk anahtarıyla eşleşmiyor.")
        for row in result["files"]:
            require(row["status"] == "done", "Belge hazırlama tamamlanamadı.")
            require(row["sha256"] == self.golden["sources"][row["file"]]["sha256"].lower(),
                    "Yüklenen dosyanın özeti değişmiş.")
            self.documents[row["document_id"]] = (row["file"], row["version_id"])

    def enable(self):
        profiles = self.api("GET", "/model/profiles")
        require(any(p["id"] == self.settings["credential_id"] and p["ready"] is True
                    for p in profiles), "Seçilen bağlantı sunucuda hazır değil.")
        result = self.api("PUT", "/model", json=self.settings)
        require(result["enabled"] is True and result["credential_ready"] is True,
                "Model bağlantısı etkinleşmedi.")

    def extract(self):
        job = self.api("POST", "/record-jobs", 202, json={"request_id": "u1_" + uuid4().hex})
        deadline = time.monotonic() + self.timeout
        while True:
            result = self.api("GET", f"/record-jobs/{job['job_id']}")
            status = result["status"]
            if status in {"done", "failed", "needs_review"}:
                require(status == "done", "Bilgi çıkarma başarısız veya inceleme bekliyor.")
                require(result["stage"] == "publish" and bool(result["revision_id"]),
                        "İşlem onaylanabilir bir yayın üretmedi.")
                self.revision = result["revision_id"]
                return
            require(status in {"queued", "running"}, "Beklenmeyen işlem durumu.")
            require(time.monotonic() < deadline, "Bilgi çıkarma bekleme süresi doldu.")
            time.sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))

    def initial_summary(self):
        result = self.api("GET", "/summary")
        require(result["revision_id"] == self.revision, "Özet farklı bir yayına ait.")
        require(result["documents"] == len(self.golden["sources"]), "Özette belge eksik.")
        require(result["records"] >= len(self.golden["records"]), "Özette kayıt eksik.")
        require(result["unsupported_fields"] == 0, "Kaynaksız alan bulundu.")
        require(result["conflicts"] == 1, "Ekilen 32/36 m² çelişkisi tam bir kez bulunmalı.")
        require(result["needs_review"] >= 0, "İnceleme sayısı geçersiz.")

    def citation_matches(self, citation, expected):
        name = citation.get("document_name")
        if "document_id" in citation:
            pin = self.documents.get(citation["document_id"])
            if not pin:
                return False
            if name is not None and name != pin[0]:
                return False
            name = pin[0]
            # Published evidence pins the canonical source (source_...), not the upload version (dver_...);
            # the document id is the stable link to the uploaded fixture.
        quote = citation.get("quote")
        if not name or not quote or not citation.get("locator"):
            return False
        source = self.fixtures / name if name in self.golden["sources"] else None
        return bool(source and name == expected["document_name"]
                    # The product may quote just the value ("32") or the whole line ("Büyüklük: 32 m2").
                    and (normalized(expected["quote"]) in normalized(quote)
                         or normalized(quote) in normalized(expected["quote"]))
                    and normalized(quote) in normalized(source.read_text(encoding="utf-8")))

    def matches_field(self, value, citations, field):
        return same_value(value, field["expected"]) and any(
            self.citation_matches(citation, expected)
            for citation in citations for expected in field["evidence"])

    def answer(self):
        remaining = None
        conflicts = 0
        for _ in range(100):
            # Every answer creates a revision: refresh issued IDs before the next write.
            page = self.api("GET", "/questions", params={"limit": 100})
            if remaining is not None:
                require(page["total"] == remaining, "Kalan soru sayısı yanıtla eşleşmiyor.")
            if page["total"] == 0:
                require(conflicts == 1, "32/36 m² çelişki sorusu doğrulanmadı.")
                return
            require(bool(page["items"]), "Soru sayısı var ama soru listesi boş.")
            question = page["items"][0]
            require(question["kind"] in {"conflict", "needs_review"}, "Beklenmeyen soru türü.")
            records = [r for r in self.golden["records"].values()
                       if r["collection"] == question["collection"] and
                       same_value(question["record_title"], r["fields"]["name"]["expected"])]
            require(len(records) == 1, "Soru doğruluk anahtarındaki tek bir kayda eşleşmeli.")
            fields = records[0]["fields"]
            options = question["options"]
            matches = [(o, field) for o in options for field in fields.values()
                       if self.matches_field(o["value"], [o], field)]
            require(bool(question["field"]) and bool(matches), "Soru için kaynaklı doğru seçenek yok.")
            candidate_ids = {o["candidate_id"] for o, _ in matches}
            require(len(candidate_ids) == 1, "Doğru seçenek tek bir aday olmalı.")
            if question["kind"] == "conflict":
                conflicts += 1
                field = matches[0][1]
                require("rejected" in field and any(
                    same_value(o["value"], field["rejected"]) and any(
                        self.citation_matches(o, e) for e in field["rejected_evidence"])
                    for o in options), "Çelişkinin reddedilen 36 m² seçeneği eksik.")
            result = self.api("POST", f"/questions/{question['id']}/answer",
                              json={"candidate_id": next(iter(candidate_ids))})
            require(bool(result["revision_id"]) and result["revision_id"] != self.revision,
                    "Yanıt yeni bir düzenleme oluşturmadı.")
            require(result["remaining"] == page["total"] - 1, "Yanıt soruyu çözmedi.")
            remaining, self.revision = result["remaining"], result["revision_id"]
        raise SmokeFailure("Sorular 100 yanıtta tamamlanamadı.")

    def approved(self):
        result = self.api("GET", "/summary")
        require(result["revision_id"] == self.revision, "Onaylı özet farklı bir yayına ait.")
        require(result["accepted_ratio"] == 1.0 and result["conflicts"] == 0
                and result["needs_review"] == 0 and result["unsupported_fields"] == 0,
                "Tüm alanlar kaynaklı ve onaylı değil.")
        checked = 0
        for key in {r["collection"] for r in self.golden["records"].values()}:
            rows = self.api("GET", f"/revisions/{self.revision}/collections/{key}",
                            params={"mode": "approved", "lang": "tr"})
            for record in self.golden["records"].values():
                if record["collection"] != key:
                    continue
                matching_rows = [row for row in rows if any(
                    self.matches_field(row.get(field), meta["evidence"], record["fields"]["name"])
                    for field, meta in row["_meta"]["fields"].items())]
                require(len(matching_rows) == 1, "Onaylı kayıt eksik veya yinelenmiş.")
                row = matching_rows[0]
                for field in record["fields"].values():
                    require(any(meta["review_state"] == "accepted" and self.matches_field(
                        row.get(key), meta["evidence"], field)
                        for key, meta in row["_meta"]["fields"].items()),
                        "Onaylı alanın değeri veya kaynağı doğruluk anahtarıyla eşleşmiyor.")
                    checked += 1
        require(checked == sum(len(r["fields"]) for r in self.golden["records"].values()),
                "Doğruluk anahtarı bütünüyle karşılaştırılmadı.")

    def ask(self):
        golden_question = self.golden["questions"][0]
        result = self.api("POST", "/ai/ask", json={"question": golden_question["question"]})
        require(result["abstained"] is False and result["revision_id"] == self.revision
                and result["mode"] == "approved", "Yanıt onaylı bilgiye dayanmıyor.")
        # Check whole numbers; 320 and 20 must not accidentally satisfy 32 and 2.
        for expected in golden_question["expected_answers"]:
            for number in re.findall(r"\d+", expected):
                require(re.search(rf"(?<!\w){number}(?!\w)", result["answer"]),
                        "Yanıtta doğruluk anahtarındaki sayı eksik.")
        expected_sources = [e for f in self.golden["records"]["bahce_odasi"]["fields"].values()
                            for e in f["evidence"] if e["document_name"] == "odalar.txt" and e["quote"] in
                            golden_question["expected_evidence_quotes"]]
        require(all(any(self.citation_matches(s, e) for s in result["sources"])
                    for e in expected_sources), "Yanıtta odalar.txt kaynakları eksik veya uydurma.")
        unknowns = ["Otelin helikopter pisti var mı?", self.golden["questions"][1]["question"]]
        for question in unknowns:
            result = self.api("POST", "/ai/ask", json={"question": question})
            require(result["abstained"] is True and result["answer"] == "Bilmiyorum."
                    and result["sources"] == [] and result["revision_id"] == self.revision,
                    "Bilinmeyen soruda kaynak veya yanıt uyduruldu.")

    def run(self):
        started = time.perf_counter()
        blocked = False
        functions = (self.create, self.model_off, self.upload, self.enable, self.extract,
                     self.initial_summary, self.answer, self.approved, self.ask)
        for name, action in zip(STEPS, functions, strict=True):
            step_started = time.perf_counter()
            status, reason = "blocked", "Önceki adım tamamlanamadı."
            if not blocked:
                try:
                    action()
                    status, reason = "pass", "Beklenen davranış doğrulandı."
                except SmokeFailure as exc:
                    status, reason, blocked = "fail", str(exc), True
                except Exception as exc:  # noqa: BLE001 -- never expose response bodies/credentials.
                    status, reason, blocked = "fail", f"İşlem tamamlanamadı ({type(exc).__name__}).", True
            self.report.steps.append({"step": name, "status": status, "reason": reason,
                                      "duration": time.perf_counter() - step_started})
        self.report.duration = time.perf_counter() - started
        self.report.write(self.output)
        return self.report


def main(argv=None):
    parser = argparse.ArgumentParser(description="U1 sentetik şirket yürüyüşü; varsayılan ağsızdır.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="API ve seçilen model ile çalıştır")
    mode.add_argument("--fake", action="store_true", help="Ağsız çalıştır (varsayılan)")
    for name in ("api", "credential-id", "base-url", "model"):
        parser.add_argument("--" + name)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--out", type=Path, default=ROOT / "storage/u1-smoke")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--poll-interval", type=float, default=1)
    args = parser.parse_args(argv)
    if args.live and not all((args.api, args.credential_id, args.base_url, args.model)):
        parser.error("Canlı çalışma için --api, --credential-id, --base-url ve --model gerekli.")
    if args.timeout <= 0 or args.poll_interval < 0:
        parser.error("Bekleme süresi pozitif, kontrol aralığı sıfır veya pozitif olmalı.")
    transport = None
    if not args.live:
        from u1_smoke_fake import FakeAPI

        transport = httpx.MockTransport(FakeAPI(args.fixtures).handle)
    with httpx.Client(base_url=args.api if args.live else "http://u1.invalid", timeout=60,
                      transport=transport, trust_env=False) as client:
        report = Walk(client, args.fixtures, args.out,
                      credential_id=args.credential_id if args.live else "synthetic",
                      base_url=args.base_url if args.live else "http://model.invalid/v1",
                      model=args.model if args.live else "synthetic",
                      timeout=args.timeout, poll_interval=args.poll_interval if args.live else 0).run()
    return int(not report.passed)


if __name__ == "__main__":
    raise SystemExit(main())
