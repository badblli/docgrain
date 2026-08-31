"""Chunk lookup and nearest-neighbour inspection."""

from __future__ import annotations

from docgrain_domain import Chunk, Neighbor
from fastapi import APIRouter, HTTPException, status

from .. import fixtures

router = APIRouter(prefix="/v1/chunks", tags=["chunks"])


@router.get("/{chunk_id}", response_model=Chunk)
def get_chunk(chunk_id: str) -> Chunk:
    chunk = next((c for c in fixtures.CHUNKS if c.id == chunk_id), None)
    if chunk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chunk not found")
    return chunk


@router.get("/{chunk_id}/neighbors", response_model=list[Neighbor])
def chunk_neighbors(chunk_id: str, limit: int = 5) -> list[Neighbor]:
    if not any(c.id == chunk_id for c in fixtures.CHUNKS):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chunk not found")
    return fixtures.neighbors(chunk_id, limit=limit)
