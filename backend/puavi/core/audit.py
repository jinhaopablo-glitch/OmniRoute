"""Registro de acciones de procesos en el audit_log inalterable."""

from __future__ import annotations

import re
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb

ProcessActor = Literal["agent", "supervisor", "executor", "system"]
_ACTION_RE = re.compile(r"^[a-z_.]{3,64}$")


def log_event(
    conn: psycopg.Connection,
    actor_type: ProcessActor,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str = "",
    details: dict[str, Any] | None = None,
) -> int:
    if not _ACTION_RE.match(action):
        raise ValueError(f"Nombre de acción inválido: {action!r}")
    row = conn.execute(
        "select public.log_event(%s::public.actor_type, %s, %s, %s, %s, %s) as id",
        (actor_type, actor_id, action, entity_type, entity_id, Jsonb(details or {})),
    ).fetchone()
    return int(row["id"])
