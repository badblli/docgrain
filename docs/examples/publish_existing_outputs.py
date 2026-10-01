"""Explicit output backfill for existing verified canonical heads; no parsing/re-ingestion/model."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

import psycopg
from docgrain_api.canonical_repository import CanonicalRepository
from docgrain_worker.main import db_url, storage
from docgrain_worker.output_writer import publish_outputs, verified_object


def run(workspace, bucket, report):
    repo = CanonicalRepository(lambda:psycopg.connect(db_url()))
    repo.initialize()
    client = storage()
    with psycopg.connect(db_url()) as connection,connection.cursor() as cursor:
        cursor.execute("SELECT document_id,latest_revision_id FROM document_knowledge_heads WHERE workspace_id=%s ORDER BY document_id",(workspace,))
        heads = cursor.fetchall()
    results = []
    for document_id,revision_id in heads:
        snapshot = repo.get_snapshot(revision_id)
        before = repo._hash(snapshot.model_dump(mode="json"))
        source = snapshot.source_version
        verified_object(client,bucket,source.storage_uri,source.content_sha256,source.byte_size)
        output,publication,inserted = publish_outputs(repo,snapshot,client,bucket)
        assert repo._hash(repo.get_snapshot(revision_id).model_dump(mode="json")) == before
        assert repo.get_heads(document_id)[0] == revision_id
        results.append({"document_id":document_id,"revision_id":revision_id,"filename":source.filename,
            "canonical_sha256":before,"canonical_unchanged":True,"inserted":inserted,
            "publication_id":publication.revision.id,"format":output.format,"version":output.version,
            "quality":output.quality.model_dump(mode="json")})
        destination = report.parent / document_id
        destination.mkdir(parents=True,exist_ok=True)
        for file in publication.files:
            data = verified_object(client,bucket,file.storage_uri,file.content_sha256,file.byte_size)
            assert sha256(data).hexdigest() == file.content_sha256
            (destination/file.name).write_bytes(data)
    report.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps([{k:row[k] for k in ("document_id","filename","version","canonical_unchanged","quality")} for row in results],ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",required=True)
    parser.add_argument("--bucket",required=True)
    parser.add_argument("--report",type=Path,required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    run(args.workspace,args.bucket,args.report)
