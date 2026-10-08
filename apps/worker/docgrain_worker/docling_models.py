"""Docling 2.130 CPU artifacts: explicit build-time download, local-only checks."""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class ModelArtifacts:
    repo_id: str
    revision: str
    files: tuple[str, ...]

    @property
    def folder(self) -> str:
        return self.repo_id.replace("/", "--")


# Matches Docling 2.130's default Transformers Heron and figure-classifier
# presets, and TableStructureModel's v2.3.0 TableFormer ACCURATE snapshot.
# Full commit IDs keep image rebuilds independent of moving HF branches/tags.
LAYOUT = ModelArtifacts(
    "docling-project/docling-layout-heron",
    "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
    ("config.json", "preprocessor_config.json", "model.safetensors"),
)
TABLEFORMER = ModelArtifacts(
    "docling-project/docling-models",
    "fc0f2d45e2218ea24bce5045f58a389aed16dc23",
    ("model_artifacts/tableformer/accurate/tm_config.json",
     "model_artifacts/tableformer/accurate/tableformer_accurate.safetensors"),
)
PICTURE_CLASSIFIER = ModelArtifacts(
    "docling-project/DocumentFigureClassifier-v2.5",
    "f859dfbff5c9916cd996942d4b0db7fa25808220",
    ("config.json", "preprocessor_config.json", "model.safetensors"),
)
MODELS = (LAYOUT, TABLEFORMER, PICTURE_CLASSIFIER)


def model_directory() -> Path:
    return Path(os.getenv("DOCGRAIN_DOCLING_MODEL_DIR", "/opt/docling-models"))


def verify_artifacts(*, pictures: bool = True) -> Path:
    """Fail before initializing Docling; never import or call a downloader."""
    directory = model_directory()
    models = MODELS if pictures else (LAYOUT, TABLEFORMER)
    missing = []
    for model in models:
        for name in model.files:
            path = directory / model.folder / name
            if not path.is_file() or path.stat().st_size == 0:
                missing.append(f"{model.folder}/{name}")
    if missing:
        raise ValueError(
            f"Docling artifacts missing or empty in {directory}: {', '.join(missing)}. "
            "Rebuild the worker image; runtime model downloads are disabled."
        )
    return directory


def startup_check() -> None:
    try:
        verify_artifacts()
    except ValueError as exc:
        logging.getLogger(__name__).error("%s", exc)
        raise


def download_models() -> None:
    """Only invoked explicitly by the Docker build, before offline ENV is set."""
    from huggingface_hub import snapshot_download

    directory = model_directory()
    with TemporaryDirectory() as cache:
        for model in MODELS:
            snapshot_download(
                repo_id=model.repo_id,
                revision=model.revision,
                allow_patterns=[*model.files, "README.md", "LICENSE*"],
                local_dir=directory / model.folder,
                cache_dir=cache,
            )
    verify_artifacts()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Build-time only")
    if parser.parse_args().download:
        download_models()
    else:
        startup_check()
