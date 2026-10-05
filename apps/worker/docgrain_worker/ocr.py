"""Pinned, offline-at-runtime Docling EasyOCR profile. Scores never imply source acceptance."""

from __future__ import annotations

import importlib.metadata
import os
from hashlib import sha256
from pathlib import Path

CHECKPOINTS = {
    "craft_mlt_25k.pth": "4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17",
    "latin_g2.pth": "aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55",
}


def model_directory() -> Path:
    return Path(os.getenv("DOCGRAIN_OCR_MODEL_DIR", "/opt/docgrain/easyocr"))


def verified_profile(*, download: bool = False) -> dict:
    if importlib.metadata.version("easyocr") != "1.7.2":
        raise ValueError("OCR profile requires EasyOCR 1.7.2")
    directory = model_directory()
    if download:
        from docling.models.stages.ocr.easyocr_model import EasyOcrModel

        EasyOcrModel.download_models(
            detection_models=["craft"],
            recognition_models=["latin_g2"],
            local_dir=directory,
        )
    for name, expected in CHECKPOINTS.items():
        path = directory / name
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"OCR checkpoint missing or checksum mismatch: {name}")
    return {
        "engine": "easyocr",
        "version": "1.7.2",
        "languages": ["tr", "en"],
        "device": "cpu",
        "checkpoints": CHECKPOINTS.copy(),
        "mode": "pdf_aware_layout_regions",
        "recognition_threshold": 0.0,
        "review_threshold": 0.8,
        "download_enabled": False,
        "profile_version": "n1-1",
    }


def options():
    from docling.datamodel.pipeline_options import EasyOcrOptions, OcrMode

    verified_profile()
    return EasyOcrOptions(
        lang=["tr", "en"],
        mode=OcrMode.PDF_AWARE_LAYOUT_REGIONS,
        model_storage_directory=str(model_directory()),
        download_enabled=False,
        confidence_threshold=0.0,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    print(verified_profile(download=parser.parse_args().download))
