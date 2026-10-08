"""Missing models fail locally, before any Docling initialization or queue work."""

import sys
from types import SimpleNamespace

import pytest
from docgrain_domain.source_format import SourceFormat
from docgrain_worker import docling_models, docling_profiles


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCGRAIN_DOCLING_MODEL_DIR", str(tmp_path))
    for model in docling_models.MODELS:
        for name in model.files:
            path = tmp_path / model.folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic-model-artifact")
    return tmp_path


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("relative", [
    f"{model.folder}/{name}" for model in docling_models.MODELS for name in model.files
])
def test_each_required_artifact_is_checked(artifacts, relative, empty):
    assert docling_models.verify_artifacts() == artifacts
    path = artifacts / relative
    if empty:
        path.write_bytes(b"")
    else:
        path.unlink()
    with pytest.raises(ValueError, match="runtime model downloads are disabled") as error:
        docling_models.verify_artifacts()
    assert relative in str(error.value)


def test_picture_models_required_only_when_enabled(artifacts):
    model = docling_models.PICTURE_CLASSIFIER
    (artifacts / model.folder / model.files[0]).unlink()
    assert docling_models.verify_artifacts(pictures=False) == artifacts
    with pytest.raises(ValueError, match="DocumentFigureClassifier"):
        docling_models.verify_artifacts()


@pytest.mark.parametrize("profile", ["B_docling", "C_tesseract", "D_fullpage"])
@pytest.mark.parametrize("fmt", [SourceFormat.PDF, SourceFormat.PNG, SourceFormat.JPEG])
def test_missing_models_fail_before_docling_initialization(tmp_path, monkeypatch, profile, fmt):
    monkeypatch.setenv("DOCGRAIN_DOCLING_MODEL_DIR", str(tmp_path))
    def unexpected(*args, **kwargs):
        pytest.fail("must not initialize Docling or download models")
    monkeypatch.setattr(docling_profiles, "verify_installed_options", unexpected)
    monkeypatch.setattr(docling_models, "download_models", unexpected)
    with pytest.raises(ValueError, match="Rebuild the worker image"):
        docling_profiles.build_converter(fmt, profile=profile)


def test_worker_startup_logs_missing_artifacts_before_connecting(tmp_path, monkeypatch, caplog):
    from docgrain_worker import main

    monkeypatch.setenv("DOCGRAIN_DOCLING_MODEL_DIR", str(tmp_path))
    def unexpected(*args, **kwargs):
        pytest.fail("must not connect to Redis or download models")
    monkeypatch.setattr(main.redis.Redis, "from_url", unexpected)
    monkeypatch.setattr(docling_models, "download_models", unexpected)
    with pytest.raises(ValueError, match="Docling artifacts missing"):
        main.run()
    assert "Rebuild the worker image" in caplog.text


def test_explicit_download_uses_pinned_snapshots_and_checks_results(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCGRAIN_DOCLING_MODEL_DIR", str(tmp_path))
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        model = next(m for m in docling_models.MODELS if m.repo_id == kwargs["repo_id"])
        assert kwargs["revision"] == model.revision
        assert len(model.revision) == 40
        assert set(model.files) <= set(kwargs["allow_patterns"])
        for name in model.files:
            path = kwargs["local_dir"] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic-model-artifact")
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    docling_models.download_models()
    assert len(calls) == 3
    assert docling_models.verify_artifacts() == tmp_path
    assert all("model.onnx" not in call["allow_patterns"] for call in calls)
