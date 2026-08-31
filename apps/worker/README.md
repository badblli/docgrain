# Worker service

The worker runs durable pipeline jobs. It consumes a job identifier, loads state from PostgreSQL, writes artifacts to object storage, and records each stage transition.

It must be safe to retry a job after process failure. Stages must be idempotent and artifacts must be stored under the immutable document-version identifier.

Initial pipeline stages: render -> extract -> quality check -> normalize -> chunk -> publish.
