"""Control de gasto: se consulta ANTES de cada llamada a la IA."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import psycopg


class BudgetExceededError(RuntimeError):
    """El agente no puede gastar más ahora (límite, desactivado o emergencia)."""


@dataclass(frozen=True)
class BudgetStatus:
    allowed: bool
    reason: str
    global_daily_spent: Decimal
    global_monthly_spent: Decimal
    agent_daily_spent: Decimal


def check_budget(conn: psycopg.Connection, agent_id: str) -> BudgetStatus:
    row = conn.execute("select * from public.check_budget(%s)", (agent_id,)).fetchone()
    return BudgetStatus(
        allowed=bool(row["allowed"]),
        reason=row["reason"],
        global_daily_spent=Decimal(row["global_daily_spent"]),
        global_monthly_spent=Decimal(row["global_monthly_spent"]),
        agent_daily_spent=Decimal(row["agent_daily_spent"]),
    )


def require_budget(conn: psycopg.Connection, agent_id: str) -> BudgetStatus:
    status = check_budget(conn, agent_id)
    if not status.allowed:
        raise BudgetExceededError(status.reason)
    return status
