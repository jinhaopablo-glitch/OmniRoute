"""Bucle del ejecutor: el ÚNICO componente que realiza acciones sensibles.

Por cada propuesta aprobada:
  1. La reclama en la base de datos, que revalida estado, caducidad, hash
     aprobado y que el aprobador siga siendo owner.
  2. Vuelve a validar el contenido con el esquema estricto.
  3. Ejecuta el manejador registrado.
  4. Registra el resultado. Los errores nunca dejan la propuesta en un
     estado ambiguo: se marca como fallida con el motivo.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from puavi.core.proposals import ActionType, validate_payload
from puavi.executor.registry import ExecutionContext, ExecutionResult, HandlerRegistry

log = logging.getLogger("puavi.executor")


def _complete(conn: psycopg.Connection, proposal_id: str, result: ExecutionResult) -> None:
    conn.execute(
        "select public.executor_complete(%s, %s, %s)",
        (proposal_id, result.success, Jsonb(result.details)),
    )


def execute_one(
    conn: psycopg.Connection, proposal_id: str, registry: HandlerRegistry
) -> ExecutionResult | None:
    """Reclama y ejecuta una propuesta. Devuelve None si no se pudo reclamar."""
    row = conn.execute(
        "select * from public.executor_claim_proposal(%s)", (proposal_id,)
    ).fetchone()
    # Confirmamos el paso a 'executing' antes de tocar sistemas externos.
    conn.commit()
    if row is None:
        return None

    action = ActionType(row["action_type"])
    payload: dict[str, Any] = row["payload"]
    ctx = ExecutionContext(
        proposal_id=str(row["id"]),
        idempotency_key=row["idempotency_key"],
        attempt=int(row["attempt"]),
    )

    try:
        validate_payload(action, payload)
    except ValidationError as exc:
        result = ExecutionResult(False, {"error": "invalid_payload", "detail": exc.errors()[:5]})
        _complete(conn, ctx.proposal_id, result)
        conn.commit()
        return result

    handler = registry.get(action)
    if handler is None:
        result = ExecutionResult(
            False, {"error": "no_handler", "detail": f"Sin integración para {action.value}"}
        )
    else:
        try:
            result = handler(payload, ctx)
        except Exception as exc:  # noqa: BLE001 - registramos y marcamos como fallida
            log.exception("Fallo ejecutando propuesta %s", ctx.proposal_id)
            result = ExecutionResult(False, {"error": type(exc).__name__})

    _complete(conn, ctx.proposal_id, result)
    conn.commit()
    return result


def run_pending(
    conn: psycopg.Connection, registry: HandlerRegistry, *, dry_run: bool, limit: int = 20
) -> list[tuple[str, ExecutionResult | None]]:
    """Procesa las propuestas listas.

    En ``dry_run`` NO reclama ni modifica nada: solo informa de lo que haría,
    para que una aprobación nunca se consuma sin ejecutarse de verdad.
    """
    ready = conn.execute("select id from public.executor_list_ready(%s)", (limit,)).fetchall()
    conn.commit()
    if dry_run:
        for r in ready:
            log.info("[dry-run] Se ejecutaría la propuesta %s", r["id"])
        return [(str(r["id"]), None) for r in ready]
    return [(str(r["id"]), execute_one(conn, str(r["id"]), registry)) for r in ready]
