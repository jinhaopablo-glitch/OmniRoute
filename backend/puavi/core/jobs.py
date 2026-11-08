"""Cliente de la cola de trabajos (tabla public.jobs)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def enqueue(
    conn: psycopg.Connection,
    agent_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_after: datetime | None = None,
    priority: int = 100,
    dedupe_key: str | None = None,
    parent_job_id: str | None = None,
) -> str:
    row = conn.execute(
        "select public.enqueue_job(%s, %s, %s, coalesce(%s, now()), %s, %s, %s) as id",
        (agent_id, kind, Jsonb(payload or {}), run_after, priority, dedupe_key, parent_job_id),
    ).fetchone()
    return str(row["id"])


def claim(
    conn: psycopg.Connection, worker_id: str, limit: int = 1, agent_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            "select * from public.claim_jobs(%s, %s, %s)", (worker_id, limit, agent_ids)
        ).fetchall()
    )


def complete(
    conn: psycopg.Connection, job_id: str, worker_id: str, result: dict | None = None
) -> None:
    conn.execute(
        "select public.complete_job(%s, %s, %s)",
        (job_id, worker_id, Jsonb(result) if result is not None else None),
    )


def fail(conn: psycopg.Connection, job_id: str, worker_id: str, error: str) -> str:
    row = conn.execute(
        "select public.fail_job(%s, %s, %s) as status", (job_id, worker_id, error)
    ).fetchone()
    return str(row["status"])
