"""Start the hash-verified Windows CPU-only vision server, with private API key.

Run setup_local_vision.py first. The ignored env file can be loaded by API Compose.
No documents or credentials are sent to a cloud service.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import urllib.error
import urllib.request
import zipfile

from setup_local_vision import PROFILE, TARGET, checked_file


def main() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    for item in profile["files"]:
        if not checked_file(TARGET / item["name"], item["sha256"], item["size"]):
            raise RuntimeError("Model checksum mismatch; run setup_local_vision.py")
    runtime = profile["runtime"]
    if not checked_file(TARGET / "runtime.zip", runtime["sha256"]):
        raise RuntimeError("Runtime checksum mismatch")
    folder = TARGET / runtime["version"]
    with zipfile.ZipFile(TARGET / "runtime.zip") as bundle:
        for item in bundle.infolist():
            if item.filename.endswith((".exe", ".dll")):
                payload = (folder / item.filename).read_bytes()
                if hashlib.sha256(payload).digest() != hashlib.sha256(bundle.read(item)).digest():
                    raise RuntimeError("Runtime binary mismatch")
    key_path = TARGET / "api-key.txt"
    if not key_path.exists():
        key_path.write_text(secrets.token_hex(32), encoding="utf-8")
    key = key_path.read_text(encoding="utf-8").strip()
    check = urllib.request.Request("http://127.0.0.1:11435/v1/models", headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(check, timeout=2) as response:
            existing = json.loads(response.read(64 * 1024))
    except (urllib.error.URLError, OSError):
        existing = None
    if existing is not None:
        if any(item.get("id") == profile["id"] for item in existing.get("data", [])):
            print("The selected local model is already running")
            return
        raise RuntimeError("Port 11435 already serves another profile; stop that owned runtime first")
    env_file = TARGET / "api.env"
    env_file.write_text(
        "DOCGRAIN_LOCAL_VISION_ENABLED=true\n"
        "DOCGRAIN_LOCAL_VISION_URL=http://host.docker.internal:11435\n"
        f"DOCGRAIN_LOCAL_VISION_API_KEY={key}\n", encoding="utf-8")
    args = [str(folder / "llama-server.exe"), "--model", str(TARGET / profile["files"][0]["name"]),
            "--mmproj", str(TARGET / profile["files"][1]["name"]), "--no-mmproj-offload",
            "--n-gpu-layers", "0", "--threads", str(profile["cpu_threads"]), "--threads-batch", str(profile["cpu_threads"]),
            "--ctx-size", str(profile["context_tokens"]), "--parallel", "1",
            "--image-max-tokens", str(profile["image_max_tokens"]), "--reasoning", "off",
            "--alias", profile["id"], "--host", "0.0.0.0", "--port", "11435",
            "--api-key-file", str(key_path)]
    with (TARGET / "server.stdout.log").open("ab") as stdout, (TARGET / "server.stderr.log").open("ab") as stderr:
        process = subprocess.Popen(args, cwd=folder, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    (TARGET / "server.pid").write_text(str(process.pid), encoding="ascii")
    print(f"CPU server started, PID {process.pid}; key remains in ignored files")


if __name__ == "__main__":
    main()
