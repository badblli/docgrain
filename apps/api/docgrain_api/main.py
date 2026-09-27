"""Docgrain HTTP API.

Boundary rule: this process orchestrates, it does not extract. Every endpoint
either reads stored artifacts or dispatches work for the worker; crash recovery is not implemented.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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
        "Document-to-knowledge engine under development. Current live ingestion: "
        "PDF upload, page rendering and provider-specific JSON/Markdown extraction. "
        "Canonical knowledge, chunking, indexing and crash recovery are not implemented. "
        "USE_FIXTURES enables read-only demo data; X-Docgrain-Mode identifies responses."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "documents", "description": "Registration, listing, versions."},
        {"name": "jobs", "description": "Job status; stage retry is not implemented."},
        {"name": "versions", "description": "Page renders and counts; demo-only tables/assets/chunks."},
        {"name": "chunks", "description": "Demo-only chunk and simulated neighbor inspection."},
        {"name": "providers", "description": "Configuration inventory, not connectivity probes."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Docgrain-Mode"],
)


@app.middleware("http")
async def identify_mode(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Docgrain-Mode"] = "demo" if get_settings().use_fixtures else "live"
    return response

for module in (documents, jobs, versions, chunks, providers):
    app.include_router(module.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {
        "status": "ok", "env": settings.docgrain_env,
        "fixtures": str(settings.use_fixtures),
        "mode": "demo" if settings.use_fixtures else "live",
    }
