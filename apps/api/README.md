# API service

The FastAPI application exposes Docgrain's public HTTP API: document registration,
local-development uploads, job status, document versions, artifacts, chunks and retry controls.

Local Docker uploads are proxied through the API into MinIO because this local
MinIO profile does not provide browser CORS support. Production object storage
uses the same boundary but can return a direct signed upload URL instead.

The API must only orchestrate durable work. It must never run extraction, rendering, embedding or index writes in an in-process background task.

Initial implementation order:

1. health endpoint and OpenAPI metadata;
2. PostgreSQL migrations and document/job/version models;
3. source registration and object-storage upload flow;
4. queue dispatch and job-status endpoints;
5. authorization, workspace isolation and signed artifact URLs.
