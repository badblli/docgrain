"""PostgreSQL checkpoint cache and atomic, immutable document index generations."""

from contextlib import contextmanager
from hashlib import sha256

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.chunking import derive_chunk_set
from docgrain_domain.canonical.indexing import IndexGeneration, embedding_cache_key
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .canonical_repository import CanonicalConflict, CanonicalRepository


def initialize_index_tables(repository, cursor):
    table = repository._table
    cursor.execute(sql.SQL("""
        CREATE TABLE IF NOT EXISTS {} (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES {}(id),
            processing_revision_id TEXT NOT NULL REFERENCES {}(id), index_name TEXT NOT NULL,
            payload JSONB NOT NULL, payload_hash TEXT NOT NULL
        )
    """).format(table("index_generations"), table("documents"), table("knowledge_revisions")))
    cursor.execute(sql.SQL("""
        CREATE TABLE IF NOT EXISTS {} (
            workspace_id TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES {}(id), index_name TEXT NOT NULL,
            generation_id TEXT REFERENCES {}(id), PRIMARY KEY (workspace_id, document_id, index_name)
        )
    """).format(table("document_index_heads"), table("documents"), table("index_generations")))
    cursor.execute(sql.SQL("""
        CREATE TABLE IF NOT EXISTS {} (id TEXT PRIMARY KEY, vector JSONB NOT NULL, payload_hash TEXT NOT NULL)
    """).format(table("embedding_checkpoints")))
    cursor.execute(sql.SQL("CREATE INDEX IF NOT EXISTS index_generations_processing_idx ON {} (processing_revision_id)")
                   .format(table("index_generations")))
    for name in ("index_generations", "embedding_checkpoints"):
        cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS reject_mutation ON {}").format(table(name)))
        cursor.execute(sql.SQL("""
            CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON {}
            FOR EACH ROW EXECUTE FUNCTION {}()
        """).format(table(name), sql.Identifier(repository._schema, "reject_canonical_mutation")))


class IndexRepository(CanonicalRepository):
    @contextmanager
    def build_lock(self, workspace_id, document_id):
        # Session lock survives individual checkpoint transactions; release even on provider error.
        key = int.from_bytes(sha256(f"{self._schema}:{workspace_id}:{document_id}".encode()).digest()[:8],
                             "big", signed=True)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (key,))
            try:
                yield
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (key,))

    def get_checkpoint(self, key):
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT vector FROM {} WHERE id=%s").format(self._table("embedding_checkpoints")), (key,))
            row = cursor.fetchone()
            return row["vector"] if row else None

    def checkpoint(self, key, vector):
        checksum = self._hash({"vector": vector})
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s,%s,%s) ON CONFLICT DO NOTHING")
                           .format(self._table("embedding_checkpoints")), (key, Jsonb(vector), checksum))
            cursor.execute(sql.SQL("SELECT payload_hash FROM {} WHERE id=%s")
                           .format(self._table("embedding_checkpoints")), (key,))
            if cursor.fetchone()["payload_hash"] != checksum:
                raise CanonicalConflict("pinned embedding configuration produced different immutable vectors")

    def get_generation(self, generation_id):
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT payload FROM {} WHERE id=%s").format(self._table("index_generations")), (generation_id,))
            row = cursor.fetchone()
            return IndexGeneration.model_validate(row["payload"]) if row else None

    def get_active(self, workspace_id, document_id, index_name="default"):
        # One statement pins the head and complete entry set to the same MVCC snapshot.
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("""
                SELECT g.payload FROM {} h JOIN {} g ON g.id=h.generation_id
                WHERE h.workspace_id=%s AND h.document_id=%s AND h.index_name=%s
            """).format(self._table("document_index_heads"), self._table("index_generations")),
                           (workspace_id, document_id, index_name))
            row = cursor.fetchone()
            return IndexGeneration.model_validate(row["payload"]) if row else None

    def publish(self, generation: IndexGeneration):
        generation = IndexGeneration.model_validate(generation.model_dump(mode="json"))
        revision = generation.revision
        payload = generation.model_dump(mode="json")
        checksum = self._hash(payload)
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT * FROM {} WHERE document_id=%s FOR UPDATE")
                           .format(self._table("document_knowledge_heads")), (revision.document_id,))
            head = cursor.fetchone()
            if head is None or head["workspace_id"] != revision.workspace_id:
                raise CanonicalConflict("index workspace/document scope mismatch")
            cursor.execute(sql.SQL("SELECT payload_hash FROM {} WHERE id=%s")
                           .format(self._table("index_generations")), (revision.id,))
            existing = cursor.fetchone()
            if existing:
                if existing["payload_hash"] != checksum:
                    raise CanonicalConflict("index ID already has different immutable payload")
                return False  # Never rewind an active head on replay.
            if head["latest_revision_id"] != revision.processing_revision_id:
                raise CanonicalConflict("target canonical revision is no longer latest")
            cursor.execute(sql.SQL("SELECT snapshot FROM {} WHERE id=%s")
                           .format(self._table("knowledge_revisions")), (revision.processing_revision_id,))
            snapshot = CanonicalKnowledgeSnapshot.model_validate(cursor.fetchone()["snapshot"])
            expected = derive_chunk_set(snapshot, generation.spec.chunking)
            if expected != generation.chunk_set:
                raise CanonicalConflict("index chunks differ from canonical strategy derivation")
            for entry in generation.entries:
                key = embedding_cache_key(revision.workspace_id, revision.document_id, generation.spec.embedding,
                                          entry.chunk.content_sha256)
                cursor.execute(sql.SQL("SELECT vector FROM {} WHERE id=%s")
                               .format(self._table("embedding_checkpoints")), (key,))
                checkpoint = cursor.fetchone()
                if checkpoint is None or checkpoint["vector"] != entry.vector:
                    raise CanonicalConflict("index vector differs from scoped embedding checkpoint")
            cursor.execute(sql.SQL("INSERT INTO {} (workspace_id,document_id,index_name) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING")
                           .format(self._table("document_index_heads")),
                           (revision.workspace_id, revision.document_id, generation.spec.name))
            cursor.execute(sql.SQL("SELECT generation_id FROM {} WHERE workspace_id=%s AND document_id=%s AND index_name=%s FOR UPDATE")
                           .format(self._table("document_index_heads")),
                           (revision.workspace_id, revision.document_id, generation.spec.name))
            if cursor.fetchone()["generation_id"] != generation.base_id:
                raise CanonicalConflict("index head changed concurrently")
            old_ids = set()
            if generation.base_id:
                cursor.execute(sql.SQL("SELECT payload FROM {} WHERE id=%s")
                               .format(self._table("index_generations")), (generation.base_id,))
                previous = IndexGeneration.model_validate(cursor.fetchone()["payload"])
                old_ids = {e.chunk.object_ref.object_id for e in previous.entries}
            current_ids = {e.chunk.object_ref.object_id for e in generation.entries}
            if set(generation.removed_chunk_ids) != old_ids - current_ids:
                raise CanonicalConflict("index deletion accounting differs from previous generation")
            cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s,%s,%s,%s)")
                           .format(self._table("index_generations")),
                           (revision.id, revision.workspace_id, revision.document_id, revision.processing_revision_id,
                            generation.spec.name, Jsonb(payload), checksum))
            cursor.execute(sql.SQL("UPDATE {} SET generation_id=%s WHERE workspace_id=%s AND document_id=%s AND index_name=%s")
                           .format(self._table("document_index_heads")),
                           (revision.id, revision.workspace_id, revision.document_id, generation.spec.name))
            return True
