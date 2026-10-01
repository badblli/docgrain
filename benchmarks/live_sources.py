"""Optional isolated filesystem create/update/delete comparison; not a runtime dependency.

Run in the Pathway spike container, where Pathway is explicitly installed.
All mutations stay in a generated TemporaryDirectory, never user source folders.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def pathway_child(root, output):
    started = time.perf_counter()
    clock = time.perf_counter
    import pathway as pw

    table = pw.io.fs.read(root, "binary", mode="streaming", with_metadata=True,
                          autocommit_duration_ms=100)
    def append(record):
        with open(output, "a") as stream:
            stream.write(json.dumps(record) + "\n")
    def changed(key, row, time, is_addition):
        append({"time": clock(), "addition": is_addition,
                "sha256": hashlib.sha256(row["data"]).hexdigest(), "batch": time})
    pw.io.subscribe(table, changed)
    append({"ready": time.perf_counter(), "import_setup_ms": (time.perf_counter()-started)*1000})
    pw.run(monitoring_level=pw.MonitoringLevel.NONE, with_http_server=False)


def wait_for(predicate, timeout=25):
    started = time.perf_counter()
    while time.perf_counter()-started < timeout:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise TimeoutError("source change was not observed")


def benchmark():
    from docgrain_worker.source_adapters import FilesystemSource

    with tempfile.TemporaryDirectory(prefix="docgrain-source-spike-") as directory:
        base = Path(directory)
        root = base / "sources"
        root.mkdir()
        output = base / "events.jsonl"
        log = base / "pathway.log"
        def records():
            if not output.exists():
                return []
            result = []
            for line in output.read_text().splitlines():
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # incomplete concurrent last line, retry on next poll
            return result
        start = time.perf_counter()
        with log.open("w") as logging:
            process = subprocess.Popen([sys.executable, __file__, "--child", str(root), str(output)],
                                       stdout=logging, stderr=logging, env={**os.environ, "PATHWAY_THREADS":"1"})
        try:
            ready = wait_for(lambda: next((r for r in records() if "ready" in r), None))
            startup = (ready["ready"]-start)*1000
            native_start = time.perf_counter()
            adapter = FilesystemSource(root)
            native_startup = (time.perf_counter()-native_start)*1000
            rows = []
            path = root / "a.txt"
            previous_hash = None
            for action, payload in (("create", b"first source"), ("update", b"second changed source"), ("delete", None)):
                before_count = len(records())
                mutate = time.perf_counter()
                if payload is None:
                    path.unlink()
                else:
                    path.write_bytes(payload)
                stamp = time.perf_counter()
                current = adapter.scan()
                native_ms = (time.perf_counter()-stamp)*1000
                expected = hashlib.sha256(payload).hexdigest() if payload is not None else previous_hash
                match = wait_for(lambda: next((r for r in records()[before_count:]
                    if r.get("sha256") == expected and r["addition"] == (payload is not None)), None))
                # Allow removal and addition events in the same source batch to settle.
                time.sleep(.15)
                received = records()[before_count:]
                rows.append({"action":action, "native_scan_ms":native_ms,
                             "native_desired_present":bool(current),
                             "pathway_detection_ms":(match["time"]-mutate)*1000,
                             "signed_events":received})
                previous_hash = expected
            distributions = list(importlib.metadata.distributions())
            size = sum(p.stat().st_size for p in Path("/usr/local/lib/python3.12/site-packages").rglob("*") if p.is_file())
            return {"version":"1", "pathway_version":pw_version(), "native_startup_ms":native_startup,
                    "pathway_startup_ms":startup, "pathway_import_setup_ms":ready["import_setup_ms"],
                    "pathway_autocommit_ms":100, "native_detection_bound":"configured poll interval + scan duration",
                    "installed_distribution_count":len(distributions), "site_packages_bytes":size,
                    "rows":rows, "production_slo":None,
                    "limitations":"one file, one sequence; native scan synchronous; Pathway streaming poll includes scheduling; no durable Pathway persistence configured"}
        except Exception:
            print(log.read_text()[-4000:], file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def pw_version():
    return importlib.metadata.version("pathway")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        pathway_child(sys.argv[2], sys.argv[3])
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("--output", required=True)
        args = parser.parse_args()
        report = benchmark()
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
