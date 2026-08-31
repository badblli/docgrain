"""Durable Redis queue boundary."""

from __future__ import annotations

from functools import lru_cache

import redis

from .settings import get_settings

QUEUE_NAME = "docgrain:pipeline"


@lru_cache
def queue_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def enqueue(job_id: str) -> None:
    queue_client().lpush(QUEUE_NAME, job_id)
