"""Durable complete observation cursor and immutable at-least-once change outbox."""

from collections.abc import Callable

from docgrain_domain.canonical.live_sources import SourceChange, SourceObservation, changes
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .canonical_repository import CanonicalConflict, CanonicalRepository


def initialize_source_visibility(repository, cursor):
    cursor.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {} (
        workspace_id TEXT NOT NULL, document_id TEXT NOT NULL,
        event_id TEXT NOT NULL, deleted BOOLEAN NOT NULL,
        PRIMARY KEY(workspace_id,document_id))""").format(repository._table("source_document_states")))


def check_source_visibility(repository, cursor, request):
    cursor.execute(sql.SQL("""SELECT document_id FROM {} WHERE workspace_id=%s
        AND document_id=ANY(%s) AND deleted""").format(repository._table("source_document_states")),
        (request.workspace_id, request.document_ids))
    if cursor.fetchone() is not None:
        raise LookupError("document source deleted in requested workspace")


class SourceRepository(CanonicalRepository):
    def initialize(self):
        # Standalone connector ledger; does not initialize or mutate canonical data.
        with self._connect() as connection, connection.cursor() as cursor:
            initialize_source_visibility(self, cursor)
            cursor.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {} (
                workspace_id TEXT NOT NULL, connector_id TEXT NOT NULL,
                generation BIGINT NOT NULL, observations JSONB NOT NULL,
                PRIMARY KEY (workspace_id, connector_id))""").format(self._table("source_cursors")))
            cursor.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {} (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, connector_id TEXT NOT NULL,
                generation BIGINT NOT NULL, source_key TEXT NOT NULL, payload JSONB NOT NULL)
                """).format(self._table("source_changes")))
            cursor.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {} (
                event_id TEXT PRIMARY KEY REFERENCES {}(id), outcome TEXT NOT NULL,
                acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
                .format(self._table("source_acknowledgements"), self._table("source_changes")))
            cursor.execute(sql.SQL("""CREATE OR REPLACE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $body$
                BEGIN RAISE EXCEPTION 'source events and acknowledgements are immutable'; END
                $body$""").format(sql.Identifier(self._schema, "reject_source_mutation")))
            for name in ("source_changes", "source_acknowledgements"):
                cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS reject_mutation ON {}").format(self._table(name)))
                cursor.execute(sql.SQL("""CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON {}
                    FOR EACH ROW EXECUTE FUNCTION {}()""").format(self._table(name),
                    sql.Identifier(self._schema, "reject_source_mutation")))

    def _lock(self, cursor, workspace, connector):
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                       (f"{self._schema}:source:{workspace}:{connector}",))

    def _read(self, cursor, workspace, connector):
        cursor.execute(sql.SQL("SELECT generation, observations FROM {} WHERE workspace_id=%s AND connector_id=%s")
                       .format(self._table("source_cursors")), (workspace, connector))
        row = cursor.fetchone()
        if row is None:
            return 0, {}
        return row["generation"], {k: SourceObservation.model_validate(v) for k, v in row["observations"].items()}

    def state(self, workspace: str, connector: str):
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            return self._read(cursor, workspace, connector)

    def reconcile(self, workspace: str, connector: str, observations: dict[str, SourceObservation], *,
                  expected_generation: int) -> list[SourceChange]:
        if not workspace or not connector:
            raise ValueError("scope required")
        observations = {k: SourceObservation.model_validate(v.model_dump(mode="json"))
                        for k, v in observations.items()}
        if any(k != v.source_key for k, v in observations.items()):
            raise ValueError("observation key mismatch")
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            self._lock(cursor, workspace, connector)
            generation, previous = self._read(cursor, workspace, connector)
            if previous == observations:
                return []  # successful complete-scan replay, no head regression
            if generation != expected_generation:
                raise CanonicalConflict("source cursor changed concurrently")
            events = changes(workspace, connector, generation + 1, previous, observations)
            for event in events:
                cursor.execute(sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s,%s,%s)")
                    .format(self._table("source_changes")), (event.id, workspace, connector,
                    event.generation, event.source_key, Jsonb(event.model_dump(mode="json"))))
            payload = {k: v.model_dump(mode="json") for k, v in observations.items()}
            cursor.execute(sql.SQL("""INSERT INTO {} VALUES (%s,%s,%s,%s)
                ON CONFLICT (workspace_id,connector_id) DO UPDATE
                SET generation=EXCLUDED.generation, observations=EXCLUDED.observations""")
                .format(self._table("source_cursors")), (workspace, connector, generation+1, Jsonb(payload)))
            return events

    def dispatch(self, workspace: str, connector: str, handler: Callable[[SourceChange], None]) -> int:
        """Coalesce unacknowledged keys to latest desired state under connector lock.

        Callback MUST be lifecycle-idempotent. It can commit publication separately;
        a crash before acknowledgement replays it. Failure rolls back all acks.
        Connector lock serializes reconcile/dispatch; slow parsing blocks that connector.
        """
        with self._connect() as connection, connection.cursor(row_factory=dict_row) as cursor:
            self._lock(cursor, workspace, connector)
            cursor.execute(sql.SQL("""SELECT c.payload FROM {} c LEFT JOIN {} a ON a.event_id=c.id
                WHERE c.workspace_id=%s AND c.connector_id=%s AND a.event_id IS NULL
                ORDER BY c.generation,c.source_key""").format(self._table("source_changes"),
                self._table("source_acknowledgements")), (workspace, connector))
            pending = [SourceChange.model_validate(row["payload"]) for row in cursor.fetchall()]
            latest = {e.source_key: e for e in pending}
            for event in latest.values():
                handler(event)
                cursor.execute(sql.SQL("""INSERT INTO {} VALUES (%s,%s,%s,%s)
                    ON CONFLICT (workspace_id,document_id) DO UPDATE
                    SET event_id=EXCLUDED.event_id, deleted=EXCLUDED.deleted""")
                    .format(self._table("source_document_states")),
                    (workspace,event.document_id,event.id,event.action == "delete"))
            for event in pending:
                outcome = "applied" if latest[event.source_key].id == event.id else "superseded"
                cursor.execute(sql.SQL("INSERT INTO {} (event_id,outcome) VALUES (%s,%s)")
                               .format(self._table("source_acknowledgements")), (event.id, outcome))
            return len(latest)
