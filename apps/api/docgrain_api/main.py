"""Docgrain HTTP API.

Boundary rule: this process orchestrates, it does not extract. Every endpoint
reads stored artifacts, dispatches worker jobs, or publishes explicit manual review
revisions and their pure derived projections; ingestion crash recovery is not implemented.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .canonical_repository import CanonicalRepository
from .repository import initialize
from .routers import (
    canonical_chunks,
    chat,
    chunks,
    documents,
    entities,
    incremental,
    jobs,
    knowledge,
    lineage,
    local_visuals,
    outputs,
    providers,
    records,
    retrieval,
    reviews,
    versions,
)
from .settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize()
    if not settings.use_fixtures and settings.canonical_persistence_enabled:
        CanonicalRepository(lambda: psycopg.connect(
            settings.database_url.replace("postgresql+psycopg://", "postgresql://")
        )).initialize()
    yield


app = FastAPI(
    title="Docgrain API",
    version="0.0.1",
    summary="Structured knowledge from every document.",
    description=(
        "Document-to-knowledge engine under development. Current live ingestion accepts "
        "PDF, DOCX, TXT, XLSX, PNG and JPEG. PDF retains page rendering and provider-specific legacy extraction. "
        "Versioned sources automatically publish canonical JSON, common ai.json, readable Markdown, chunks and a verified manifest. "
        "Bounded source-checked manual reviews append immutable child revisions and refreshed outputs atomically. "
        "Automated visual reconciliation, live embedding/Qdrant adapters and ingestion crash recovery are not implemented. "
        "Explicit worker index lifecycle supports checkpoint reuse and atomic PostgreSQL generations; HTTP lifecycle inspection is read-only. "
        "Canonical chunk derivation runs at ingestion write time; queries read immutable artifacts. "
        "USE_FIXTURES enables read-only demo data; X-Docgrain-Mode identifies responses."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "documents", "description": "Registration, listing, versions."},
        {"name": "jobs", "description": "Job status; stage retry is not implemented."},
        {"name": "versions", "description": "Page renders and counts; demo-only tables/assets/chunks."},
        {"name": "knowledge", "description": "Read-only canonical knowledge revisions."},
        {"name": "chat", "description": "Explicit experimental Gemini Q&A over a pinned revision; no canonical writes or embeddings."},
        {"name": "review", "description": "Source reading, pure typed preview and explicit immutable manual revision publication."},
        {"name": "chunks", "description": "Demo-only chunk and simulated neighbor inspection."},
        {"name": "canonical-chunks", "description": "Revision-scoped canonical derivation and reads; Unicode character budgets."},
        {"name": "providers", "description": "Configuration inventory, not connectivity probes."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Docgrain-Mode", "X-Docgrain-Serialization-Ms", "X-Docgrain-Service-Ms",
                    "ETag", "X-Docgrain-Workspace", "X-Docgrain-Revision",
                    "X-Docgrain-Schema-Version", "X-Docgrain-Publication-Mode"],
)


@app.middleware("http")
async def identify_mode(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Docgrain-Mode"] = "demo" if get_settings().use_fixtures else "live"
    return response

for module in (documents, jobs, versions, chunks, providers, lineage, entities, canonical_chunks, incremental, retrieval, outputs):
    app.include_router(module.router)
app.include_router(reviews.router)
app.include_router(records.router)
app.include_router(chat.router)
app.include_router(local_visuals.router)
app.include_router(knowledge.document_router)
app.include_router(knowledge.revision_router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {
        "status": "ok", "env": settings.docgrain_env,
        "fixtures": str(settings.use_fixtures),
        "mode": "demo" if settings.use_fixtures else "live",
    }
