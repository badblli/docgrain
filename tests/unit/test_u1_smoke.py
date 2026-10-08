"""Real upload bytes and publication contracts, without any sockets or models."""

import json
import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs/examples"))

import u1_smoke as smoke
import u1_smoke_fake as fake_module
from u1_smoke_fake import FakeAPI


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("U1 unit tests must never open a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def run_fake(tmp_path, fault=None, handler=None, timeout=1):
    fake = FakeAPI(smoke.FIXTURES, fault)
    with httpx.Client(base_url="http://u1.invalid", transport=httpx.MockTransport(
            handler or fake.handle), trust_env=False) as client:
        report = smoke.Walk(client, smoke.FIXTURES, tmp_path, credential_id="synthetic",
                            base_url="http://model.invalid/v1", model="synthetic",
                            timeout=timeout, poll_interval=0).run()
    return fake, report


def test_pass_uploads_fixture_bytes_and_checks_every_step(tmp_path, capsys):
    fake, report = run_fake(tmp_path)
    assert report.passed
    assert len(report.steps) == 9
    assert all(step["status"] == "pass" and step["duration"] >= 0 for step in report.steps)
    assert fake.uploads == {name: (smoke.FIXTURES / name).read_bytes()
                            for name in ("odalar.txt", "hizmetler.txt")}
    assert len(fake.revision.history) == 5
    assert fake.revision.records[0].fields["size_m2"].accepted("tr").value == 32
    assert fake.polls == 2
    assert sum(method == "POST" and path.endswith("/answer") for method, path in fake.requests) == 5
    # The double rejects stale questions, proving that each write refreshed the issued revision.
    assert sum(method == "GET" and path.endswith("/questions") for method, path in fake.requests) == 6
    assert not any("health" in path for _, path in fake.requests)
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved["status"] == "pass" and saved["steps"] == report.steps
    assert "Sonuç: GEÇTİ" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert capsys.readouterr().out.count("[GEÇTİ]") == 9


@pytest.mark.parametrize("fault, failed_step", [
    ("wrong_value", 7), ("missing_sources", 8), ("unsupported", 5),
    ("job_failed", 4), ("invented_unknown_source", 8), ("job_needs_review", 4),
])
def test_required_failures_produce_reports_and_nonzero_exit(tmp_path, capsys, monkeypatch,
                                                          fault, failed_step):
    created = []

    def factory(fixtures):
        fake = FakeAPI(fixtures, fault)
        created.append(fake)
        return fake

    monkeypatch.setattr(fake_module, "FakeAPI", factory)
    assert smoke.main(["--fake", "--out", str(tmp_path)]) == 1
    result = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert result["status"] == "fail" and len(result["steps"]) == 9
    assert result["steps"][failed_step]["status"] == "fail"
    assert all(s["status"] == "blocked" for s in result["steps"][failed_step + 1:])
    printed = capsys.readouterr().out
    assert "[KALDI]" in printed and "Sonuç: KALDI" in printed
    assert (tmp_path / "report.md").exists()
    if fault == "wrong_value":
        assert created[0].revision.records[0].fields["size_m2"].accepted("tr").value == 36


def test_timeout_finishes_with_blocked_steps_and_report(tmp_path):
    _, report = run_fake(tmp_path, "job_timeout", timeout=0.001)
    assert not report.passed
    assert "süresi doldu" in report.steps[4]["reason"]
    assert all(s["status"] == "blocked" for s in report.steps[5:])
    assert (tmp_path / "report.json").exists()


def test_default_cli_is_fake_and_reads_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-do-not-read")
    assert smoke.main(["--out", str(tmp_path)]) == 0
    assert "synthetic-do-not-read" not in (tmp_path / "report.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("flag", ["--api", "--credential-id", "--base-url", "--model"])
def test_live_requires_all_four_settings(tmp_path, flag):
    settings = {"--api": "http://u1.invalid", "--credential-id": "synthetic",
                "--base-url": "http://model.invalid/v1", "--model": "synthetic"}
    args = ["--live", "--out", str(tmp_path)]
    for key, value in settings.items():
        if key != flag:
            args.extend([key, value])
    with pytest.raises(SystemExit) as exc:
        smoke.main(args)
    assert exc.value.code == 2
    assert not (tmp_path / "report.json").exists()


def test_api_error_body_is_never_reported(tmp_path, capsys):
    def handler(request):
        return httpx.Response(503, json={"detail": "synthetic-private-provider-message"})

    _, report = run_fake(tmp_path, handler=handler)
    assert report.steps[0]["status"] == "fail"
    assert report.steps[0]["reason"] == "HTTP 503; beklenen 201."
    assert "synthetic-private-provider-message" not in capsys.readouterr().out
    assert "synthetic-private-provider-message" not in (tmp_path / "report.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_answer", ["Oda 320 m2 ve 20 kişilik.", "Oda 36 m2 ve 2 kişilik."])
def test_answer_numbers_are_compared_as_whole_values(tmp_path, bad_answer):
    fake = FakeAPI(smoke.FIXTURES)

    def handler(request):
        response = fake.handle(request)
        if request.url.path.endswith("/ai/ask") and response.status_code == 200:
            body = response.json()
            if not body["abstained"]:
                body["answer"] = bad_answer
                return httpx.Response(200, json=body)
        return response

    _, report = run_fake(tmp_path, handler=handler)
    assert not report.passed and report.steps[8]["status"] == "fail"


def test_five_fields_are_checked_even_when_summary_says_accepted(tmp_path):
    fake = FakeAPI(smoke.FIXTURES)

    def handler(request):
        response = fake.handle(request)
        if "/collections/services" in request.url.path:
            rows = response.json()
            rows[0]["hours"] = "09:00–18:00"
            return httpx.Response(200, json=rows)
        return response

    _, report = run_fake(tmp_path, handler=handler)
    assert not report.passed and report.steps[7]["status"] == "fail"


def test_source_quote_must_exist_in_uploaded_fixture(tmp_path):
    fake = FakeAPI(smoke.FIXTURES)

    def handler(request):
        response = fake.handle(request)
        if request.url.path.endswith("/ai/ask") and response.status_code == 200:
            body = response.json()
            if not body["abstained"]:
                body["sources"][0]["quote"] += " Invented evidence."
                return httpx.Response(200, json=body)
        return response

    _, report = run_fake(tmp_path, handler=handler)
    assert not report.passed and report.steps[8]["status"] == "fail"
