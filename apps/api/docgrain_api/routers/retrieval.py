"""Consumer retrieval API; no parser or embedding provider on the online path."""

from time import perf_counter

from docgrain_domain.canonical.retrieval import (
    CapabilityUnavailable,
    RetrievalQuery,
    RetrievalResult,
    retrieve,
)
from fastapi import APIRouter, HTTPException

from ..retrieval_repository import RetrievalRepository
from .lineage import lifecycle_repository

router = APIRouter(prefix="/v1/knowledge", tags=["retrieval"])


@router.post("/retrieve", response_model=RetrievalResult)
def retrieve_knowledge(request: RetrievalQuery):
    started = perf_counter()
    source = lifecycle_repository()
    repository = RetrievalRepository(source._connect, source._schema)
    try:
        views = repository.read_views(request)
        loaded = perf_counter()
        result = retrieve(views, request)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except CapabilityUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finished = perf_counter()
    result.timings_ms = {"backend": (loaded-started)*1000, "query": (finished-loaded)*1000,
                         "embed": 0, "rerank": result.timings_ms.get("rerank", 0), "service": (finished-started)*1000}
    return result
