# API service

The FastAPI application exposes Docgrain's public HTTP API: document registration, signed uploads, job status, document versions, artifacts, chunks and retry controls.

The API must only orchestrate durable work. It must never run extraction, rendering, embedding or index writes in an in-process background task.

Initial implementation order:

1. health endpoint and OpenAPI metadata;
2. PostgreSQL migrations and document/job/version models;
3. source registration and object-storage upload flow;
4. queue dispatch and job-status endpoints;
5. authorization, workspace isolation and signed artifact URLs.
