"""Claim pipeline jobs from Redis and persist the first state transition."""

from __future__ import annotations

import os
from contextlib import closing

import psycopg
import redis

QUEUE_NAME = "docgrain:pipeline"


def database_url() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def claim(job_id: str) -> None:
    with closing(psycopg.connect(database_url())) as connection, connection.cursor() as cursor:
        cursor.execute(
            """UPDATE jobs SET status = 'running', started_at = COALESCE(started_at, NOW())
            WHERE id = %s AND status = 'queued'""",
            (job_id,),
        )
        connection.commit()


def run() -> None:
    # Redis' socket read timeout must stay disabled while BRPOP is blocking.
    # Supplying a short BRPOP timeout makes redis-py turn the expected idle wait
    # into a socket TimeoutError and terminates the worker.
    client = redis.Redis.from_url(
        os.environ["REDIS_URL"], decode_responses=True, socket_timeout=None
    )
    while True:
        message = client.brpop(QUEUE_NAME, timeout=0)
        _, job_id = message
        claim(job_id)


if __name__ == "__main__":
    run()
