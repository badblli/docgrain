"""Opt-in real PostgreSQL M1 tests in a uniquely named, disposable schema."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from docgrain_api.canonical_repository import CanonicalConflict, CanonicalRepository
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from psycopg import sql

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "canonical" / "generic-pdf.json"
DOMAIN_FIXTURE = FIXTURE.with_name("domain-example.json")


def snapshot(revision_id: str = "revision-pdf", parent_id: str | None = None) -> CanonicalKnowledgeSnapshot:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["knowledge_revision"]["id"] = revision_id
    value["knowledge_revision"]["parent_revision_id"] = parent_id
    return CanonicalKnowledgeSnapshot.model_validate(value)


@pytest.fixture
def store():
    database_url = os.environ.get("DOCGRAIN_M1_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set DOCGRAIN_M1_TEST_DATABASE_URL for isolated real PostgreSQL tests")
    schema = "m1_test_" + uuid.uuid4().hex

    def connect():
        return psycopg.connect(database_url)

    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}") .format(sql.Identifier(schema)))
        cursor.execute(sql.SQL("CREATE TABLE {} (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL)")
                       .format(sql.Identifier(schema, "documents")))
        cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s, %s)")
                       .format(sql.Identifier(schema, "documents")),
                       ("document-generic-pdf", "workspace-synthetic"))
    repository = CanonicalRepository(connect, schema=schema)
    try:
        repository.initialize()
        yield repository, connect, schema
    finally:
        # Only this test-created namespace is removed; existing user/smoke data is untouched.
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_append_idempotency_immutability_and_heads(store) -> None:
    repository, connect, schema = store
    first = snapshot()
    assert repository.append(first, expected_latest_revision_id=None) is True
    assert repository.append(first, expected_latest_revision_id=None) is False
    assert repository.get_heads(first.document_id) == ("revision-pdf", None)
    assert repository.get_snapshot("revision-pdf") == first

    source_changed = first.model_dump(mode="json")
    source_changed["source_version"]["storage_uri"] = "fixture://different"
    source_changed["knowledge_revision"]["id"] = "revision-next"
    source_changed["knowledge_revision"]["parent_revision_id"] = "revision-pdf"
    with pytest.raises(CanonicalConflict, match="source ID"):
        repository.append(CanonicalKnowledgeSnapshot.model_validate(source_changed),
                          expected_latest_revision_id="revision-pdf")

    revision_changed = first.model_dump(mode="json")
    revision_changed["structure"][2]["text"] = "Different payload"
    with pytest.raises(CanonicalConflict, match="revision ID"):
        repository.append(CanonicalKnowledgeSnapshot.model_validate(revision_changed),
                          expected_latest_revision_id=None)

    for table in ("source_versions", "knowledge_revisions"):
        for operation in ("UPDATE", "DELETE"):
            with (
                pytest.raises(psycopg.errors.RaiseException),
                connect() as connection,
                connection.cursor() as cursor,
            ):
                if operation == "UPDATE":
                    cursor.execute(sql.SQL("UPDATE {} SET workspace_id = workspace_id")
                                   .format(sql.Identifier(schema, table)))
                else:
                    cursor.execute(sql.SQL("DELETE FROM {}")
                                   .format(sql.Identifier(schema, table)))

    second = snapshot("revision-second", "revision-pdf")
    assert repository.append(second, expected_latest_revision_id="revision-pdf") is True
    assert repository.get_heads(first.document_id) == ("revision-second", None)
    repository.approve(first.document_id, first.workspace_id, "revision-pdf",
                       expected_approved_revision_id=None)
    assert repository.get_heads(first.document_id) == ("revision-second", "revision-pdf")
    with pytest.raises(CanonicalConflict, match="approved head changed"):
        repository.approve(first.document_id, first.workspace_id, "revision-second",
                           expected_approved_revision_id=None)


def test_concurrent_head_cas_scope_and_core_invalid_guard(store) -> None:
    repository, _, _ = store
    first = snapshot()
    invalid = first.model_copy(update={"root_node_id": "missing"})
    with pytest.raises(ValueError, match="root"):
        repository.append(invalid, expected_latest_revision_id=None)
    assert repository.append(first, expected_latest_revision_id=None)
    candidates = [snapshot("revision-a", "revision-pdf"),
                  snapshot("revision-b", "revision-pdf")]

    def attempt(item):
        try:
            return repository.append(item, expected_latest_revision_id="revision-pdf")
        except CanonicalConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, candidates))
    assert outcomes.count(True) == 1
    assert repository.get_heads(first.document_id)[0] in {"revision-a", "revision-b"}
    with pytest.raises(CanonicalConflict, match="head document/workspace scope"):
        repository.approve(first.document_id, "wrong-workspace", "revision-pdf",
                           expected_approved_revision_id=None)


def test_invalid_domain_record_can_persist_but_cannot_be_approved(store) -> None:
    repository, connect, schema = store
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s, %s)")
                       .format(sql.Identifier(schema, "documents")),
                       ("document-domain-example", "workspace-synthetic"))
    value = json.loads(DOMAIN_FIXTURE.read_text(encoding="utf-8"))
    value["records"][0]["validation"] = {"status": "invalid", "errors": ["/count: below minimum"]}
    domain_snapshot = CanonicalKnowledgeSnapshot.model_validate(value)
    assert repository.append(domain_snapshot, expected_latest_revision_id=None)
    with pytest.raises(CanonicalConflict, match="invalid domain records"):
        repository.approve("document-domain-example", "workspace-synthetic", "revision-sheet",
                           expected_approved_revision_id=None)
