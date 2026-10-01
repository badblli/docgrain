"""Docgrain HTTP API.

Boundary rule: this process orchestrates, it does not extract. Every endpoint
either reads stored artifacts or dispatches work for the worker; crash recovery is not implemented.
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
    chunks,
    documents,
    entities,
    incremental,
    jobs,
    lineage,
    providers,
    retrieval,
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
        "PDF, DOCX, TXT and XLSX. PDF retains page rendering and provider-specific legacy extraction. "
        "Versioned sources can produce structural canonical DB revisions; canonical artifact publication, "
        "Vision reconciliation, live embedding/Qdrant adapters and ingestion crash recovery are not implemented. "
        "Explicit worker index lifecycle supports checkpoint reuse and atomic PostgreSQL generations; HTTP lifecycle inspection is read-only. "
        "Canonical chunks use explicit revision-scoped derivation; ingestion does not generate them automatically. "
        "USE_FIXTURES enables read-only demo data; X-Docgrain-Mode identifies responses."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "documents", "description": "Registration, listing, versions."},
        {"name": "jobs", "description": "Job status; stage retry is not implemented."},
        {"name": "versions", "description": "Page renders and counts; demo-only tables/assets/chunks."},
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
    expose_headers=["X-Docgrain-Mode", "X-Docgrain-Serialization-Ms", "X-Docgrain-Service-Ms"],
)


@app.middleware("http")
async def identify_mode(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Docgrain-Mode"] = "demo" if get_settings().use_fixtures else "live"
    return response

for module in (documents, jobs, versions, chunks, providers, lineage, entities, canonical_chunks, incremental, retrieval):
    app.include_router(module.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {
        "status": "ok", "env": settings.docgrain_env,
        "fixtures": str(settings.use_fixtures),
        "mode": "demo" if settings.use_fixtures else "live",
    }
