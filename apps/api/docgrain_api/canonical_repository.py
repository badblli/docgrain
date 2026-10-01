"""Canonical revision storage; callers verify source bytes and object version."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import psycopg
from docgrain_domain.canonical import CanonicalKnowledgeSnapshot, SourceVersion
from docgrain_domain.canonical.entities import RegisteredSchema, validate_entity_data
from docgrain_domain.canonical.identity import canonical_json_bytes
from docgrain_domain.canonical.lineage import DerivedManifest, LineageGraph
from docgrain_domain.canonical.models import SchemaEntity
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
                    workspace_id TEXT NOT NULL,
                    schema_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, schema_id, version)
                )
            """).format(self._table("domain_schema_registry")))
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
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES {}(id),
                    workspace_id TEXT NOT NULL,
                    processing_revision_id TEXT NOT NULL REFERENCES {}(id),
                    payload JSONB NOT NULL,
                    payload_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """).format(self._table("derived_revisions"), self._table("documents"),
                         self._table("knowledge_revisions")))
            cursor.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (processing_revision_id)")
                           .format(sql.Identifier("derived_revisions_processing_idx"),
                                   self._table("derived_revisions")))
            for name in ("source_versions", "knowledge_revisions", "derived_revisions", "domain_schema_registry"):
                cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS reject_mutation ON {}")
                               .format(self._table(name)))
                cursor.execute(sql.SQL("""
                    CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON {}
                    FOR EACH ROW EXECUTE FUNCTION {}()
                """).format(self._table(name), sql.Identifier(self._schema, "reject_canonical_mutation")))
            from .index_repository import initialize_index_tables

            initialize_index_tables(self, cursor)
            from .retrieval_repository import initialize_contexts

            initialize_contexts(self, cursor)
            from .source_repository import initialize_source_visibility

            initialize_source_visibility(self, cursor)

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
            self._validate_entities(cursor, snapshot)

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
            from .retrieval_repository import append_context

            append_context(self, cursor, snapshot)
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
            self._validate_entities(cursor, snapshot)
            if any(record.validation.status == "invalid" for record in snapshot.records):
                raise CanonicalConflict("revision contains invalid domain records")
            if any(isinstance(entity, SchemaEntity) and entity.review_status != "accepted" for entity in snapshot.entities):
                raise CanonicalConflict("revision contains schema entities awaiting acceptance or rejected")
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

    def get_source(self, source_id: str) -> SourceVersion | None:
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT payload FROM {} WHERE id = %s")
                           .format(self._table("source_versions")), (source_id,))
            row = cursor.fetchone()
            return SourceVersion.model_validate(row["payload"]) if row else None

    def register_schema(self, schema: RegisteredSchema) -> bool:
        schema = RegisteredSchema.model_validate(schema.model_dump(mode="json"))
        payload = schema.model_dump(mode="json")
        payload_hash = self._hash(payload)
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("""
                INSERT INTO {} (workspace_id, schema_id, version, payload, payload_hash)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """).format(self._table("domain_schema_registry")), (
                schema.workspace_id, schema.reference.id, schema.reference.version, Jsonb(payload), payload_hash))
            inserted = cursor.rowcount == 1
            cursor.execute(sql.SQL("SELECT payload_hash FROM {} WHERE workspace_id=%s AND schema_id=%s AND version=%s")
                           .format(self._table("domain_schema_registry")),
                           (schema.workspace_id, schema.reference.id, schema.reference.version))
            if cursor.fetchone()["payload_hash"] != payload_hash:
                raise CanonicalConflict("schema ID/version already has different immutable content")
            return inserted

    def get_schema(self, workspace_id: str, schema_id: str, version: str) -> RegisteredSchema | None:
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            return self._get_schema(cursor, workspace_id, schema_id, version)

    def _get_schema(self, cursor, workspace_id, schema_id, version):
        cursor.execute(sql.SQL("SELECT payload FROM {} WHERE workspace_id=%s AND schema_id=%s AND version=%s")
                       .format(self._table("domain_schema_registry")), (workspace_id, schema_id, version))
        row = cursor.fetchone()
        return RegisteredSchema.model_validate(row["payload"]) if row else None

    def _validate_entities(self, cursor, snapshot):
        schemas = {ref.id: ref for ref in snapshot.domain_schemas}
        for entity in snapshot.entities:
            if not isinstance(entity, SchemaEntity):
                continue
            registered = self._get_schema(cursor, snapshot.workspace_id, entity.schema_id, entity.schema_version)
            if registered is None or registered.reference != schemas[entity.schema_id]:
                raise CanonicalConflict("entity schema is not registered with this checksum in this workspace")
            actual = validate_entity_data(entity.data, registered)
            if actual != entity.validation:
                raise CanonicalConflict("entity validation differs from registered schema validation")

    def get_derivation(self, revision_id: str) -> DerivedManifest | None:
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT payload FROM {} WHERE id = %s")
                           .format(self._table("derived_revisions")), (revision_id,))
            row = cursor.fetchone()
            return DerivedManifest.model_validate(row["payload"]) if row else None

    def _lineage(self, cursor, snapshot: CanonicalKnowledgeSnapshot) -> LineageGraph:
        cursor.execute(sql.SQL("SELECT payload FROM {} WHERE processing_revision_id = %s")
                       .format(self._table("derived_revisions")), (snapshot.knowledge_revision.id,))
        manifests = [DerivedManifest.model_validate(row["payload"]) for row in cursor.fetchall()]
        from docgrain_domain.canonical.indexing import IndexGeneration

        cursor.execute(sql.SQL("SELECT payload FROM {} WHERE processing_revision_id = %s")
                       .format(self._table("index_generations")), (snapshot.knowledge_revision.id,))
        manifests.extend(manifest for row in cursor.fetchall()
                         for manifest in IndexGeneration.model_validate(row["payload"]).manifests())
        unique = {}
        for manifest in manifests:
            if manifest.revision.id in unique and unique[manifest.revision.id] != manifest:
                raise CanonicalConflict("registered lineage manifests disagree")
            unique[manifest.revision.id] = manifest
        order = {"projection": 0, "chunking": 1, "embedding": 2, "indexing": 3}
        graph = LineageGraph(snapshot)
        for manifest in sorted(unique.values(), key=lambda m: (order[m.revision.stage], m.revision.id)):
            graph.extend(manifest)
        return graph

    def get_lineage(self, processing_revision_id: str) -> LineageGraph | None:
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT snapshot FROM {} WHERE id = %s")
                           .format(self._table("knowledge_revisions")), (processing_revision_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._lineage(cursor, CanonicalKnowledgeSnapshot.model_validate(row["snapshot"]))

    def append_derived(self, manifest: DerivedManifest) -> bool:
        """Atomic immutable manifest publication; validate registered dependencies under lock."""
        manifest = DerivedManifest.model_validate(manifest.model_dump(mode="json"))
        revision = manifest.revision
        payload = manifest.model_dump(mode="json")
        payload_hash = self._hash(payload)
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT * FROM {} WHERE document_id = %s FOR UPDATE")
                           .format(self._table("document_knowledge_heads")), (revision.document_id,))
            head = cursor.fetchone()
            if head is None or head["workspace_id"] != revision.workspace_id:
                raise CanonicalConflict("derived document/workspace scope mismatch")
            cursor.execute(sql.SQL("SELECT snapshot FROM {} WHERE id = %s")
                           .format(self._table("knowledge_revisions")), (revision.processing_revision_id,))
            row = cursor.fetchone()
            if row is None:
                raise CanonicalConflict("derived processing revision not found")
            snapshot = CanonicalKnowledgeSnapshot.model_validate(row["snapshot"])
            if (snapshot.document_id, snapshot.workspace_id) != (revision.document_id, revision.workspace_id):
                raise CanonicalConflict("derived processing revision scope mismatch")
            if manifest.schema_version == "0.3.0" and revision.stage == "chunking":
                from docgrain_domain.canonical.chunking import ChunkingSpec, derive_chunks

                expected = derive_chunks(snapshot, ChunkingSpec.model_validate(revision.configuration))
                if canonical_json_bytes(expected.model_dump(mode="json")) != canonical_json_bytes(payload):
                    raise CanonicalConflict("chunk manifest differs from canonical strategy derivation")
            for artifact in manifest.projections:
                dependencies = [edge.upstream for edge in manifest.edges if edge.downstream.key == artifact.object_ref.key]
                entity = next((item for item in snapshot.entities if len(dependencies) == 1
                               and dependencies[0].object_id == item.id
                               and dependencies[0].revision_id == snapshot.knowledge_revision.id), None)
                if not isinstance(entity, SchemaEntity) or entity.review_status != "accepted":
                    raise CanonicalConflict("entity projection requires exactly one accepted schema entity")
                try:
                    projection_data = json.loads(artifact.text)
                except ValueError as exc:
                    raise CanonicalConflict("entity projection text is not valid JSON") from exc
                if canonical_json_bytes(projection_data) != canonical_json_bytes(entity.data):
                    raise CanonicalConflict("entity projection JSON differs from canonical entity data")
            cursor.execute(sql.SQL("SELECT payload_hash FROM {} WHERE id = %s")
                           .format(self._table("derived_revisions")), (revision.id,))
            existing = cursor.fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise CanonicalConflict("derived revision ID already has different immutable payload")
                return False
            graph = self._lineage(cursor, snapshot)
            graph.extend(manifest)
            cursor.execute(sql.SQL("""
                INSERT INTO {} (id, document_id, workspace_id, processing_revision_id, payload, payload_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
            """).format(self._table("derived_revisions")), (
                revision.id, revision.document_id, revision.workspace_id,
                revision.processing_revision_id, Jsonb(payload), payload_hash,
            ))
            return True
