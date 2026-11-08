"""Clientes Python (propuestas, presupuesto, cola, ejecutor) contra Postgres real."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from puavi.core import budget, jobs
from puavi.core.audit import log_event
from puavi.core.proposals import ActionType, submit_proposal
from puavi.executor.registry import ExecutionResult, HandlerRegistry
from puavi.executor.runner import execute_one, run_pending

pytestmark = pytest.mark.db

PRICE = {
    "product_id": "gid://shopify/Product/7",
    "variant_id": "gid://shopify/ProductVariant/7",
    "current_price": "10.00",
    "new_price": "15.00",
    "reason": "Margen insuficiente",
}


def _submit(agent, payload=None) -> str:
    return submit_proposal(
        agent,
        agent_id="shopify",
        action=ActionType.CHANGE_PRICE,
        title="Subir precio comedero",
        summary="Margen actual 12 %",
        payload=payload or PRICE,
        idempotency_key=f"py-{uuid.uuid4()}",
        risk="low",
    )


def _approve(admin, supervisor, make_human, pid: str) -> None:
    supervisor.execute("select public.supervisor_review(%s, 'ok', '')", (pid,))
    _, owner = make_human("owner")
    h = admin.execute("select payload_hash from public.proposals where id = %s", (pid,)).fetchone()
    owner.execute("select public.approve_proposal(%s, %s)", (pid, h["payload_hash"]))


def test_python_submit_validates_and_raises_risk(admin, agent):
    pid = _submit(agent)
    row = admin.execute("select risk_level from public.proposals where id = %s", (pid,)).fetchone()
    # +50 % de precio => riesgo alto aunque el agente pidiera 'low'.
    assert row["risk_level"] == "high"


def test_python_submit_rejects_invalid_payload(agent):
    with pytest.raises(ValidationError):
        _submit(agent, {**PRICE, "new_price": "10.00"})
    with pytest.raises(ValidationError):
        _submit(agent, {**PRICE, "extra": "campo no permitido"})


def test_budget_and_jobs_clients(agent):
    status = budget.check_budget(agent, "marketing")
    assert status.allowed
    jid = jobs.enqueue(agent, "marketing", "trends.weekly", {"x": 1}, priority=1)
    claimed = jobs.claim(agent, "py-worker", 20, ["marketing"])
    assert jid in [str(j["id"]) for j in claimed]
    jobs.complete(agent, jid, "py-worker", {"ok": True})
    assert log_event(agent, "agent", "marketing", "trends.done", "job", jid) > 0


def test_executor_dry_run_does_not_consume_approval(admin, agent, supervisor, executor, make_human):
    pid = _submit(agent)
    _approve(admin, supervisor, make_human, pid)
    executor.autocommit = False
    results = dict(run_pending(executor, HandlerRegistry(), dry_run=True, limit=100))
    executor.autocommit = True
    assert pid in results and results[pid] is None
    assert (
        admin.execute("select status from public.proposals where id = %s", (pid,)).fetchone()[
            "status"
        ]
        == "approved"
    )


def test_executor_runs_registered_handler(admin, agent, supervisor, executor, make_human):
    pid = _submit(agent)
    _approve(admin, supervisor, make_human, pid)
    calls = []

    def handler(payload, ctx):
        calls.append((payload["new_price"], ctx.idempotency_key))
        return ExecutionResult(True, {"shopify": "actualizado"})

    registry = HandlerRegistry()
    registry.register(ActionType.CHANGE_PRICE, handler)
    executor.autocommit = False
    result = execute_one(executor, pid, registry)
    executor.autocommit = True
    assert result.success and len(calls) == 1
    assert (
        admin.execute("select status from public.proposals where id = %s", (pid,)).fetchone()[
            "status"
        ]
        == "executed"
    )


def test_executor_without_handler_fails_safely(admin, agent, supervisor, executor, make_human):
    pid = _submit(agent)
    _approve(admin, supervisor, make_human, pid)
    executor.autocommit = False
    result = execute_one(executor, pid, HandlerRegistry())
    executor.autocommit = True
    assert result.success is False
    assert result.details["error"] == "no_handler"


def test_executor_handler_exception_is_contained(admin, agent, supervisor, executor, make_human):
    pid = _submit(agent)
    _approve(admin, supervisor, make_human, pid)

    def boom(payload, ctx):
        raise TimeoutError("Shopify no responde")

    registry = HandlerRegistry()
    registry.register(ActionType.CHANGE_PRICE, boom)
    executor.autocommit = False
    result = execute_one(executor, pid, registry)
    executor.autocommit = True
    assert result.details == {"error": "TimeoutError"}
    assert (
        admin.execute("select status from public.proposals where id = %s", (pid,)).fetchone()[
            "status"
        ]
        == "failed"
    )
