"""Explicit polling/event-hint orchestration; caller supplies lifecycle publisher."""


def sync_source(repository, workspace: str, connector: str, adapter, handler):
    """One complete observation + coalesced outbox delivery.

    Capture the cursor BEFORE scanning: delayed scans cannot overwrite newer scans.
    A polling loop or validated webhook notification can call this same operation.
    Caller owns retry/backoff/scheduling, durable source copies and parser/index providers.
    """
    generation, _ = repository.state(workspace, connector)
    observations = adapter.scan()  # failure never creates deletion or advances cursor
    emitted = repository.reconcile(workspace, connector, observations, expected_generation=generation)
    delivered = repository.dispatch(workspace, connector, handler)
    return {"emitted": len(emitted), "delivered": delivered}
