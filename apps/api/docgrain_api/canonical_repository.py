"""Canonical revision storage; callers verify source bytes and object version."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import psycopg
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.identity import canonical_json_bytes
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class CanonicalConflict(ValueError):
    """An immutable identity or compare-and-swap head conflicts with stored state."""


class CanonicalRepository:
    """Additive schema; caller controls connection and explicit initialization.

    Source metadata is immutable here, but current MinIO upload keys can be overwritten.
    Callers must verify source bytes and stable object identity before using this store.
    M1b callers may persist only a verified, version-addressed source object.
    """

    def __init__(self, connect: Callable[[], psycopg.Connection], schema: str = "public") -> None:
        self._connect = connect
        self._schema = schema

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self._schema, name)

    def initialize(self) -> None:
        """Additive DDL foundation, not a production migration lifecycle."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES {}(id),
                    workspace_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """).format(self._table("source_versions"), self._table("documents")))
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES {}(id),
                    workspace_id TEXT NOT NULL,
                    source_version_id TEXT NOT NULL REFERENCES {}(id),
                    parent_revision_id TEXT REFERENCES {}(id),
                    snapshot JSONB NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """).format(
                self._table("knowledge_revisions"), self._table("documents"),
                self._table("source_versions"), self._table("knowledge_revisions"),
            ))
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    document_id TEXT PRIMARY KEY REFERENCES {}(id),
                    workspace_id TEXT NOT NULL,
                    latest_revision_id TEXT REFERENCES {}(id),
                    approved_revision_id TEXT REFERENCES {}(id)
                )
            """).format(
                self._table("document_knowledge_heads"), self._table("documents"),
                self._table("knowledge_revisions"), self._table("knowledge_revisions"),
            ))
            cursor.execute(sql.SQL("""
                CREATE OR REPLACE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $body$
                BEGIN
                    RAISE EXCEPTION 'canonical source and revision rows are immutable';
                END
                $body$
            """).format(sql.Identifier(self._schema, "reject_canonical_mutation")))
            for name in ("source_versions", "knowledge_revisions"):
                cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS reject_mutation ON {}")
                               .format(self._table(name)))
                cursor.execute(sql.SQL("""
                    CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON {}
                    FOR EACH ROW EXECUTE FUNCTION {}()
                """).format(self._table(name), sql.Identifier(self._schema, "reject_canonical_mutation")))

    @staticmethod
    def _hash(payload: dict[str, object]) -> str:
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()

    def append(
        self, snapshot: CanonicalKnowledgeSnapshot, *, expected_latest_revision_id: str | None
    ) -> bool:
        """Append one revision and CAS latest head. True=inserted, False=idempotent replay."""
        # Revalidate because model_copy(update=...) bypasses Pydantic validators.
        snapshot = CanonicalKnowledgeSnapshot.model_validate(snapshot.model_dump(mode="json"))
        source = snapshot.source_version
        revision = snapshot.knowledge_revision
        if revision.parent_revision_id != expected_latest_revision_id:
            raise CanonicalConflict("parent revision must equal expected latest head")
        source_payload = source.model_dump(mode="json")
        snapshot_payload = snapshot.model_dump(mode="json")
        source_hash = self._hash(source_payload)
        snapshot_hash = self._hash(snapshot_payload)

        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT workspace_id FROM {} WHERE id = %s")
                           .format(self._table("documents")), (snapshot.document_id,))
            document = cursor.fetchone()
            if document is None or document["workspace_id"] != snapshot.workspace_id:
                raise CanonicalConflict("document/workspace scope mismatch")

            cursor.execute(sql.SQL("""
                INSERT INTO {} (id, document_id, workspace_id, payload, payload_hash)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
            """).format(self._table("source_versions")), (
                source.id, source.document_id, source.workspace_id, Jsonb(source_payload), source_hash,
            ))
            cursor.execute(sql.SQL("SELECT payload_hash FROM {} WHERE id = %s")
                           .format(self._table("source_versions")), (source.id,))
            if cursor.fetchone()["payload_hash"] != source_hash:
                raise CanonicalConflict("source ID already has different immutable payload")

            cursor.execute(sql.SQL("""
                INSERT INTO {} (document_id, workspace_id) VALUES (%s, %s)
                ON CONFLICT (document_id) DO NOTHING
            """).format(self._table("document_knowledge_heads")),
                           (snapshot.document_id, snapshot.workspace_id))
            cursor.execute(sql.SQL("SELECT * FROM {} WHERE document_id = %s FOR UPDATE")
                           .format(self._table("document_knowledge_heads")), (snapshot.document_id,))
            head = cursor.fetchone()
            if head["workspace_id"] != snapshot.workspace_id:
                raise CanonicalConflict("head workspace mismatch")
            cursor.execute(sql.SQL("SELECT snapshot_hash FROM {} WHERE id = %s")
                           .format(self._table("knowledge_revisions")), (revision.id,))
            existing = cursor.fetchone()
            if existing is not None:
                if existing["snapshot_hash"] != snapshot_hash:
                    raise CanonicalConflict("revision ID already has different immutable snapshot")
                return False
            if head["latest_revision_id"] != expected_latest_revision_id:
                raise CanonicalConflict("latest head changed concurrently")
            if expected_latest_revision_id is not None:
                cursor.execute(sql.SQL("""
                    SELECT document_id, workspace_id FROM {} WHERE id = %s
                """).format(self._table("knowledge_revisions")), (expected_latest_revision_id,))
                parent = cursor.fetchone()
                if parent is None or (parent["document_id"], parent["workspace_id"]) != (
                    snapshot.document_id, snapshot.workspace_id
                ):
                    raise CanonicalConflict("parent revision scope mismatch")
            cursor.execute(sql.SQL("""
                INSERT INTO {} (id, document_id, workspace_id, source_version_id,
                                parent_revision_id, snapshot, snapshot_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """).format(self._table("knowledge_revisions")), (
                revision.id, snapshot.document_id, snapshot.workspace_id, source.id,
                revision.parent_revision_id, Jsonb(snapshot_payload), snapshot_hash,
            ))
            cursor.execute(sql.SQL("""
                UPDATE {} SET latest_revision_id = %s WHERE document_id = %s
            """).format(self._table("document_knowledge_heads")),
                           (revision.id, snapshot.document_id))
            return True

    def approve(
        self, document_id: str, workspace_id: str, revision_id: str, *,
        expected_approved_revision_id: str | None,
    ) -> None:
        """Explicit compare-and-swap approval pointer; never automatic on append."""
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT * FROM {} WHERE document_id = %s FOR UPDATE")
                           .format(self._table("document_knowledge_heads")), (document_id,))
            head = cursor.fetchone()
            if head is None or head["workspace_id"] != workspace_id:
                raise CanonicalConflict("head document/workspace scope mismatch")
            if head["approved_revision_id"] != expected_approved_revision_id:
                raise CanonicalConflict("approved head changed concurrently")
            cursor.execute(sql.SQL("SELECT snapshot, workspace_id, document_id FROM {} WHERE id = %s")
                           .format(self._table("knowledge_revisions")), (revision_id,))
            row = cursor.fetchone()
            if row is None or (row["document_id"], row["workspace_id"]) != (
                document_id, workspace_id
            ):
                raise CanonicalConflict("approved revision scope mismatch")
            snapshot = CanonicalKnowledgeSnapshot.model_validate(row["snapshot"])
            if any(record.validation.status == "invalid" for record in snapshot.records):
                raise CanonicalConflict("revision contains invalid domain records")
            cursor.execute(sql.SQL("UPDATE {} SET approved_revision_id = %s WHERE document_id = %s")
                           .format(self._table("document_knowledge_heads")), (revision_id, document_id))

    def get_heads(self, document_id: str) -> tuple[str | None, str | None] | None:
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("""
                SELECT latest_revision_id, approved_revision_id FROM {} WHERE document_id = %s
            """).format(self._table("document_knowledge_heads")), (document_id,))
            row = cursor.fetchone()
            return (row["latest_revision_id"], row["approved_revision_id"]) if row else None

    def get_snapshot(self, revision_id: str) -> CanonicalKnowledgeSnapshot | None:
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT snapshot FROM {} WHERE id = %s")
                           .format(self._table("knowledge_revisions")), (revision_id,))
            row = cursor.fetchone()
            return CanonicalKnowledgeSnapshot.model_validate(row["snapshot"]) if row else None
