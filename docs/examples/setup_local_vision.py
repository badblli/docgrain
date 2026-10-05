"""Download and hash-check the selected CPU runtime/model. Never sends documents.

Run on Windows: python docs/examples/setup_local_vision.py
Files stay under ignored data/models/local-vision; inference has no downloads.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "apps/api/docgrain_api/profiles/local-vision-cpu-1.json"
TARGET = ROOT / "data/models/local-vision"


def checked_file(path: Path, checksum: str, size: int | None = None) -> bool:
    if not path.is_file() or (size is not None and path.stat().st_size != size):
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == checksum


def download(url: str, path: Path, checksum: str, size: int | None = None) -> None:
    if checked_file(path, checksum, size):
        print(f"Verified existing {path.name}", flush=True)
        return
    partial = path.with_suffix(path.suffix + ".partial")
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if not checked_file(partial, checksum, size):
        raise RuntimeError(f"Checksum/size mismatch for {path.name}")
    partial.replace(path)
    print(f"Downloaded and verified {path.name}", flush=True)


def main() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    TARGET.mkdir(parents=True, exist_ok=True)
    runtime = profile["runtime"]
    archive = TARGET / "runtime.zip"
    jobs = [(runtime["url"], archive, runtime["sha256"], None)]
    for item in profile["files"]:
        url = (f"https://huggingface.co/{profile['model_repository']}/resolve/"
               f"{profile['model_revision']}/{item['name']}")
        jobs.append((url, TARGET / item["name"], item["sha256"], item["size"]))
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download, *args) for args in jobs]
        for future in futures:
            future.result()
    runtime_dir = TARGET / runtime["version"]
    runtime_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            destination = (runtime_dir / item.filename).resolve()
            if not destination.is_relative_to(runtime_dir.resolve()):
                raise RuntimeError("Unsafe archive path")
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                payload = bundle.read(item)
                if checked_file(destination, hashlib.sha256(payload).hexdigest(), len(payload)):
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
    print(f"Ready: {runtime_dir}", flush=True)


if __name__ == "__main__":
    main()
