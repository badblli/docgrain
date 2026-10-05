"""Real PostgreSQL + loopback HTTP latency matrix in a disposable benchmark schema."""

import argparse
import json
import os
import platform
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter, sleep
from urllib.request import Request, urlopen

import psycopg
import uvicorn
from docgrain_api.canonical_repository import CanonicalRepository
from docgrain_api.index_repository import IndexRepository
from docgrain_api.main import app
from docgrain_api.routers import retrieval as routes
from docgrain_api.settings import get_settings
from docgrain_domain.canonical import deterministic_item_id
from docgrain_domain.canonical.lifecycle import entity_id
from docgrain_worker.index_lifecycle import refresh_index
from psycopg import sql

from tests.fixtures.incremental import FixtureEmbedder, index_spec, revised
from tests.integration.test_m2b_repository import accepted


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered)-1)*fraction
    lower = int(position)
    return ordered[lower] + (ordered[min(lower+1, len(ordered)-1)]-ordered[lower])*(position-lower)


def profile(snapshot, count):
    def mutate(value):
        template = value["structure"][-1]
        nodes, entities = [], []
        entity_template = value["entities"][0]
        for index in range(count):
            node = json.loads(json.dumps(template))
            node["identity_key"] = f"benchmark-{index}"
            node["id"] = deterministic_item_id(snapshot.document_id, "text_block", node["identity_key"], policy_version="0.2.0")
            node["text"] = (f"needle_{index} Benchmark item {index} exact source text. " * 3)
            node["role"] = "paragraph" if index % 2 else "other"
            nodes.append(node)
            entity = json.loads(json.dumps(entity_template))
            entity["identity_key"] = f"benchmark-entity-{index}"
            entity["id"] = entity_id(snapshot.document_id, entity["schema_id"], entity["identity_key"])
            entity["data"] = {"name": f"Benchmark item {index}", "capacity": index % 10 + 1}
            entities.append(entity)
        value["structure"] = [value["structure"][0], *nodes]
        value["structure"][0]["children"] = [node["id"] for node in nodes]
        value["entities"] = entities
    return revised(snapshot, mutate, version=f"latency-benchmark-{count}")


def run(output, runs, concurrency):
    dsn = os.environ.get("DOCGRAIN_M1_TEST_DATABASE_URL")
    if not dsn:
        raise ValueError("DOCGRAIN_M1_TEST_DATABASE_URL is required; only a disposable schema is written")
    schema = "docgrain_latency_" + uuid.uuid4().hex
    def connect():
        return psycopg.connect(dsn)
    report = {"version": "1", "environment": {"platform": platform.platform(), "python": platform.python_version(),
                                                 "cpu_count": os.cpu_count(), "transport": "loopback TCP HTTP + real PostgreSQL"},
              "runs": runs, "concurrency": concurrency, "vector_kind": "test-only SHA256 fixture",
              "cold_definition": "decoded revision cache miss; OS/PostgreSQL caches not flushed",
              "production_slo": None, "results": []}
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(sql.SQL("CREATE TABLE {} (id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL)")
                       .format(sql.Identifier(schema, "documents")))
        cursor.execute(sql.SQL("INSERT INTO {} VALUES ('document-test','workspace-test')").format(sql.Identifier(schema, "documents")))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    try:
        repository = CanonicalRepository(connect, schema)
        repository.initialize()
        *_old, parent = accepted(repository)
        index = IndexRepository(connect, schema)
        get_settings().use_fixtures = False
        routes.lifecycle_repository = lambda: repository
        thread.start()
        for _ in range(100):
            if server.started:
                break
            sleep(0.05)
        if not server.started:
            raise RuntimeError("benchmark HTTP server did not start")
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/v1/knowledge/retrieve"
        active_id = None
        for name, count in (("tiny", 1), ("small", 16), ("medium", 64), ("large", 256)):
            snapshot = profile(parent, count)
            repository.append(snapshot, expected_latest_revision_id=parent.knowledge_revision.id)
            spec = index_spec()
            spec.chunking.max_chars = 256
            generation, _ = refresh_index(index, snapshot.knowledge_revision.id, spec, FixtureEmbedder(), expected_generation_id=active_id)
            active_id, parent = generation.revision.id, snapshot
            query_embedding = {"spec": spec.embedding.model_dump(mode="json"), "vector": generation.entries[0].vector}
            base = {"workspace_id": snapshot.workspace_id, "document_ids": [snapshot.document_id], "limit": 5}
            matrix = {"structured": {"mode": "structured", "predicates": [{"path": "/capacity", "operator": "gte", "value": 3}]},
                      "direct": {"mode": "direct", "direct_max_chars": 1000000},
                      "lexical": {"mode": "lexical", "text": "needle_0"},
                      "vector": {"mode": "vector", "query_embedding": query_embedding},
                      "hybrid": {"mode": "hybrid", "text": "needle_0", "query_embedding": query_embedding},
                      "rerank": {"mode": "hybrid", "text": "needle_0", "query_embedding": query_embedding, "reranking": {}}}
            target = next(e.chunk.object_ref.object_id for e in generation.entries if "needle_0 " in e.chunk.text)
            for path, options in matrix.items():
                body = json.dumps({**base, **options}).encode()
                def query_once(body=body, path=path, target=target, url=url, count=count):
                    started = perf_counter()
                    with urlopen(Request(url, data=body, headers={"Content-Type": "application/json"}), timeout=60) as response:
                        raw = response.read()
                        serialization = float(response.headers["X-Docgrain-Serialization-Ms"])
                        service = float(response.headers["X-Docgrain-Service-Ms"])
                    result = json.loads(raw)
                    elapsed = (perf_counter()-started)*1000
                    result["timings_ms"]["serialization"] = serialization
                    result["timings_ms"]["transport_client"] = max(0, elapsed-service)
                    if result["timings_ms"]["embed"] != 0:
                        raise AssertionError("embedding on online query path")
                    expected_count = min(5, sum(i % 10 + 1 >= 3 for i in range(count)))
                    quality = (len(result["hits"]) == expected_count and all(h["data"]["capacity"] >= 3 for h in result["hits"]) if path == "structured" else
                               len(json.loads(result["hits"][0]["text"])["entities"]) == count if path == "direct" else
                               any(h["object_ref"]["object_id"] == target for h in result["hits"]))
                    return {"elapsed": elapsed, "components": result["timings_ms"], "bytes": len(raw), "quality": quality,
                            "evidence_bytes": sum(len(json.dumps(e).encode()) for h in result["hits"] for e in h["evidence"])}
                for cache_state in ("cold", "warm", "concurrent"):
                    rows = []
                    if cache_state == "concurrent":
                        started = perf_counter()
                        with ThreadPoolExecutor(max_workers=concurrency) as pool:
                            rows = list(pool.map(lambda _, run=query_once: run(), range(runs)))
                        seconds = perf_counter()-started
                    else:
                        started = perf_counter()
                        for _ in range(runs if cache_state == "warm" else min(runs, 3)):
                            if cache_state == "cold":
                                routes.revision_cache.clear()
                            rows.append(query_once())
                        seconds = perf_counter()-started
                    values = [row["elapsed"] for row in rows]
                    report["results"].append({"profile": name, "entity_count": count, "chunk_count": len(generation.entries),
                                              "path": path, "cache": cache_state, "samples": len(rows),
                                              "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95), "p99_ms": percentile(values, .99),
                                              "throughput_rps": len(rows)/seconds, "quality_hit_rate": sum(r["quality"] for r in rows)/len(rows),
                                              "response_bytes": max(r["bytes"] for r in rows), "evidence_bytes": max(r["evidence_bytes"] for r in rows),
                                              "components_p50_ms": {key: percentile([r["components"][key] for r in rows], .5) for key in rows[0]["components"]}})
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"rows": len(report["results"]), "max_p95_ms": max(r["p95_ms"] for r in report["results"]),
                          "warm": [{"profile": r["profile"], "path": r["path"], "p95_ms": round(r["p95_ms"], 2),
                                    "quality": r["quality_hit_rate"]} for r in report["results"] if r["cache"] == "warm"]}))
    finally:
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=10)
        listener.close()
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=__import__("pathlib").Path)
    parser.add_argument("--runs", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.runs < 2 or args.concurrency < 1:
        parser.error("runs >= 2 and concurrency >= 1 required")
    run(args.output, args.runs, args.concurrency)
