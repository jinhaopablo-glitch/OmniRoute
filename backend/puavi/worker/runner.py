"""Ejecución de trabajos de la cola por parte de los agentes."""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg

from puavi.agents import REGISTRY
from puavi.agents.base import AgentContext, Services
from puavi.core import jobs
from puavi.core.budget import BudgetExceededError
from puavi.llm.client import AgentLLM

log = logging.getLogger("puavi.worker")


def process_job(
    job: dict[str, Any],
    *,
    conn: psycopg.Connection,
    sup_conn: psycopg.Connection,
    llm: AgentLLM,
    services: Services,
    worker_id: str,
) -> str:
    """Ejecuta un trabajo ya reclamado. Devuelve 'done', 'queued' o 'failed'."""
    spec = REGISTRY.get(job["kind"])
    if spec is None or spec.agent_id != job["agent_id"]:
        return jobs.fail(
            conn, str(job["id"]), worker_id, f"Tipo de trabajo desconocido: {job['kind']}"
        )
    ctx = AgentContext(conn=conn, sup_conn=sup_conn, llm=llm, job=job, services=services)
    try:
        result = spec.handler(ctx)
    except BudgetExceededError as exc:
        log.warning("Trabajo %s bloqueado por presupuesto: %s", job["id"], exc)
        return jobs.fail(conn, str(job["id"]), worker_id, f"Presupuesto: {exc}")
    except Exception as exc:  # noqa: BLE001 - se registra y reintenta
        log.exception("Trabajo %s (%s) falló", job["id"], job["kind"])
        return jobs.fail(conn, str(job["id"]), worker_id, f"{type(exc).__name__}: {exc}"[:2000])
    jobs.complete(conn, str(job["id"]), worker_id, json.loads(json.dumps(result, default=str)))
    conn.execute(
        "select public.log_event('agent', %s, 'job.completed', 'job', %s, %s)",
        (spec.agent_id, str(job["id"]), json.dumps({"kind": job["kind"]})),
    )
    return "done"


def run_once(
    *,
    conn: psycopg.Connection,
    sup_conn: psycopg.Connection,
    llm: AgentLLM,
    services: Services,
    worker_id: str,
    limit: int = 1,
) -> list[str]:
    claimed = jobs.claim(conn, worker_id, limit)
    return [
        process_job(
            j, conn=conn, sup_conn=sup_conn, llm=llm, services=services, worker_id=worker_id
        )
        for j in claimed
    ]
