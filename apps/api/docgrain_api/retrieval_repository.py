"""Pinned read snapshots and write-time direct-context projection persistence."""

from docgrain_domain.canonical import CanonicalKnowledgeSnapshot
from docgrain_domain.canonical.indexing import IndexGeneration
from docgrain_domain.canonical.retrieval import DocumentView, context_projection
from psycopg import sql
from psycopg.rows import dict_row

from .canonical_repository import CanonicalConflict, CanonicalRepository


def initialize_contexts(repository, cursor):
    cursor.execute(sql.SQL("""
        CREATE TABLE IF NOT EXISTS {} (
            revision_id TEXT NOT NULL REFERENCES {}(id), version TEXT NOT NULL,
            text TEXT NOT NULL, PRIMARY KEY(revision_id,version)
        )
    """).format(repository._table("canonical_contexts"), repository._table("knowledge_revisions")))
    cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS reject_mutation ON {}")
                   .format(repository._table("canonical_contexts")))
    cursor.execute(sql.SQL("CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON {} FOR EACH ROW EXECUTE FUNCTION {}()")
                   .format(repository._table("canonical_contexts"), sql.Identifier(repository._schema, "reject_canonical_mutation")))


def append_context(repository, cursor, snapshot):
    text = context_projection(snapshot)
    cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s,'1',%s) ON CONFLICT DO NOTHING")
                   .format(repository._table("canonical_contexts")), (snapshot.knowledge_revision.id, text))
    cursor.execute(sql.SQL("SELECT text FROM {} WHERE revision_id=%s AND version='1'")
                   .format(repository._table("canonical_contexts")), (snapshot.knowledge_revision.id,))
    row = cursor.fetchone()
    actual = row["text"] if isinstance(row, dict) else row[0]
    if actual != text:
        raise CanonicalConflict("context projection already has different immutable text")


class RetrievalRepository(CanonicalRepository):
    def __init__(self, connect, schema="public", cache=None):
        super().__init__(connect, schema)
        self.cache = cache

    def backfill_context(self, revision_id):
        """Explicit write-time migration for old immutable revisions; never called by queries."""
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT snapshot FROM {} WHERE id=%s")
                           .format(self._table("knowledge_revisions")), (revision_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError("canonical revision not found")
            append_context(self, cursor, CanonicalKnowledgeSnapshot.model_validate(row["snapshot"]))

    def read_views(self, request):
        ranked = request.mode in {"lexical", "vector", "hybrid"}
        if self.cache is not None:
            return self._cached_views(request, ranked)
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            if ranked:
                cursor.execute(sql.SQL("""
                    SELECT d.document_id, r.snapshot, g.payload AS generation, NULL AS context
                    FROM {} d LEFT JOIN {} h ON h.document_id=d.document_id AND h.workspace_id=d.workspace_id AND h.index_name=%s
                    LEFT JOIN {} g ON g.id=h.generation_id LEFT JOIN {} r ON r.id=g.processing_revision_id
                    WHERE d.workspace_id=%s AND d.document_id=ANY(%s) ORDER BY d.document_id
                """).format(self._table("document_knowledge_heads"), self._table("document_index_heads"),
                             self._table("index_generations"), self._table("knowledge_revisions")),
                               (request.index_name, request.workspace_id, request.document_ids))
            else:
                cursor.execute(sql.SQL("""
                    SELECT d.document_id,r.snapshot,NULL AS generation,c.text AS context
                    FROM {} d JOIN {} r ON r.id=d.latest_revision_id
                    LEFT JOIN {} c ON c.revision_id=r.id AND c.version='1'
                    WHERE d.workspace_id=%s AND d.document_id=ANY(%s) ORDER BY d.document_id
                """).format(self._table("document_knowledge_heads"), self._table("knowledge_revisions"),
                             self._table("canonical_contexts")), (request.workspace_id, request.document_ids))
            rows = cursor.fetchall()
            if {row["document_id"] for row in rows} != set(request.document_ids):
                raise LookupError("document knowledge unavailable in requested workspace")
            from docgrain_domain.canonical.retrieval import CapabilityUnavailable
            if any(row["snapshot"] is None for row in rows):
                raise CapabilityUnavailable("active index generation unavailable")
            return [DocumentView(snapshot=CanonicalKnowledgeSnapshot.model_validate(row["snapshot"]),
                                 generation=IndexGeneration.model_validate(row["generation"]) if row["generation"] else None,
                                 context=row["context"]) for row in rows]

    def _cached_views(self, request, ranked):
        from docgrain_domain.canonical.retrieval import CapabilityUnavailable
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute(sql.SQL("""
                SELECT d.document_id,d.latest_revision_id,h.generation_id,g.processing_revision_id
                FROM {} d LEFT JOIN {} h ON h.document_id=d.document_id AND h.workspace_id=d.workspace_id AND h.index_name=%s
                LEFT JOIN {} g ON g.id=h.generation_id
                WHERE d.workspace_id=%s AND d.document_id=ANY(%s) ORDER BY d.document_id
            """).format(self._table("document_knowledge_heads"), self._table("document_index_heads"),
                         self._table("index_generations")), (request.index_name, request.workspace_id, request.document_ids))
            heads = cursor.fetchall()
            if {h["document_id"] for h in heads} != set(request.document_ids):
                raise LookupError("document knowledge unavailable in requested workspace")
            views = []
            info = connection.info
            namespace = (info.host, info.port, info.dbname, info.user, self._schema)
            for head in heads:
                revision = head["processing_revision_id"] if ranked else head["latest_revision_id"]
                generation_id = head["generation_id"] if ranked else None
                if revision is None:
                    raise CapabilityUnavailable("active index generation unavailable")
                key = (*namespace, request.workspace_id, head["document_id"], revision, generation_id, request.index_name, "context-1")
                view = self.cache.get(key)
                if view is None:
                    cursor.execute(sql.SQL("SELECT r.snapshot,c.text AS context FROM {} r LEFT JOIN {} c ON c.revision_id=r.id AND c.version='1' WHERE r.id=%s")
                                   .format(self._table("knowledge_revisions"), self._table("canonical_contexts")), (revision,))
                    row = cursor.fetchone()
                    generation = None
                    if generation_id:
                        cursor.execute(sql.SQL("SELECT payload FROM {} WHERE id=%s").format(self._table("index_generations")), (generation_id,))
                        generation = IndexGeneration.model_validate(cursor.fetchone()["payload"])
                    view = DocumentView(snapshot=CanonicalKnowledgeSnapshot.model_validate(row["snapshot"]),
                                        generation=generation, context=row["context"])
                    self.cache.put(key, view)
                views.append(view)
            return views
