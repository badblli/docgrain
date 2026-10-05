"""Immutable publication pointer becomes visible only after verified output files exist."""

from hashlib import sha256

from docgrain_domain.canonical.ai_output import MIME, OutputPublication, output_bundle
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .canonical_repository import CanonicalConflict, CanonicalRepository


def initialize_outputs(repository, cursor):
    cursor.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {} (
        revision_id TEXT NOT NULL REFERENCES {}(id), version TEXT NOT NULL,
        payload JSONB NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(revision_id,version))""")
        .format(repository._table("knowledge_outputs"), repository._table("knowledge_revisions")))
    cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS reject_mutation ON {}").format(repository._table("knowledge_outputs")))
    cursor.execute(sql.SQL("CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON {} FOR EACH ROW EXECUTE FUNCTION {}()")
        .format(repository._table("knowledge_outputs"), sql.Identifier(repository._schema,"reject_canonical_mutation")))


class OutputRepository(CanonicalRepository):
    def get_outputs(self, revision_id):
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("SELECT payload FROM {} WHERE revision_id=%s AND version='1.0.0'")
                           .format(self._table("knowledge_outputs")), (revision_id,))
            row = cursor.fetchone()
            return OutputPublication.model_validate(row["payload"]) if row else None

    def publish_outputs(self, publication: OutputPublication):
        publication = OutputPublication.model_validate(publication.model_dump(mode="json"))
        revision_id = publication.revision.processing_revision_id
        snapshot = self.get_snapshot(revision_id)
        if snapshot is None:
            raise ValueError("canonical revision not found")
        _, _, revision, files = output_bundle(snapshot)
        if publication.revision != revision or len(publication.files) != len(files):
            raise CanonicalConflict("output identity/configuration differs from canonical projection")
        if {f.name for f in publication.files} != set(files):
            raise CanonicalConflict("output set is incomplete or duplicated")
        for item in publication.files:
            body = files[item.name]
            if (item.content_sha256,item.byte_size,item.mime_type) != (sha256(body).hexdigest(),len(body),MIME[item.name]):
                raise CanonicalConflict("output checksum differs from canonical projection")
        payload = publication.model_dump(mode="json")
        checksum = self._hash(payload)
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING")
                           .format(self._table("knowledge_outputs")), (revision_id,publication.version,Jsonb(payload),checksum))
            inserted = cursor.rowcount == 1
            cursor.execute(sql.SQL("SELECT payload_hash FROM {} WHERE revision_id=%s AND version=%s")
                           .format(self._table("knowledge_outputs")), (revision_id,publication.version))
            if cursor.fetchone()["payload_hash"] != checksum:
                raise CanonicalConflict("output version already has different immutable publication")
            return inserted
