"""Docgrain HTTP API.

Boundary rule: this process orchestrates, it does not extract. Every endpoint
either reads stored artifacts or enqueues durable work for the worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .repository import initialize
from .routers import chunks, documents, jobs, providers, versions
from .settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize()
    yield


app = FastAPI(
    title="Docgrain API",
    version="0.0.1",
    summary="Structured knowledge from every document.",
    description=(
        "Document ingestion as a durable, inspectable pipeline. "
        "Consumers register sources, poll job status and read versioned "
        "artifacts: pages, tables, assets, chunks and their provenance."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "documents", "description": "Registration, listing, versions."},
        {"name": "jobs", "description": "Ten-stage pipeline status and retries."},
        {"name": "versions", "description": "Pages, tables, assets, chunks, diff."},
        {"name": "chunks", "description": "Retrieval units and their neighbours."},
        {"name": "providers", "description": "Which adapters are wired in."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (documents, jobs, versions, chunks, providers):
    app.include_router(module.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "env": settings.docgrain_env, "fixtures": str(settings.use_fixtures)}
