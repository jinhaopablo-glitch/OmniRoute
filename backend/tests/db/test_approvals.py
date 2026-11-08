"""Garantías de la bandeja de aprobaciones, comprobadas contra Postgres real."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors

pytestmark = pytest.mark.db


def _status(admin: psycopg.Connection, pid: str) -> str:
    return admin.execute("select status from public.proposals where id = %s", (pid,)).fetchone()[
        "status"
    ]


def _hash(admin: psycopg.Connection, pid: str) -> str:
    return admin.execute(
        "select payload_hash from public.proposals where id = %s", (pid,)
    ).fetchone()["payload_hash"]


def _claim(executor: psycopg.Connection, pid: str) -> list:
    return executor.execute("select * from public.executor_claim_proposal(%s)", (pid,)).fetchall()


def _to_pending_approval(supervisor: psycopg.Connection, pid: str) -> None:
    supervisor.execute("select public.supervisor_review(%s, 'ok', 'Correcto')", (pid,))


# --- Creación -----------------------------------------------------------------


def test_agent_proposal_starts_pending_review_with_server_hash(admin, submit):
    pid = submit()
    row = admin.execute(
        "select status, payload_hash, public.payload_digest(payload) as h, decided_by"
        " from public.proposals where id = %s",
        (pid,),
    ).fetchone()
    assert row["status"] == "pending_review"
    assert row["payload_hash"] == row["h"]
    assert row["decided_by"] is None


def test_submit_is_idempotent(agent):
    args = ("shopify", '{"description": "Acción de prueba idempotente"}', "idem-key-0001")
    q = (
        "select public.agent_submit_proposal(%s, 'other_sensitive', 'Prueba', '', %s::jsonb,"
        " 'medium', 0, %s) as id"
    )
    first = agent.execute(q, args).fetchone()["id"]
    second = agent.execute(q, args).fetchone()["id"]
    assert first == second


def test_supervisor_cannot_create_proposals(supervisor):
    with pytest.raises(errors.InsufficientPrivilege):
        supervisor.execute(
            "select public.agent_submit_proposal('shopify', 'other_sensitive', 'x', '', '{}',"
            " 'low', 0, 'k-supervisor-01')"
        )


def test_agent_cannot_impersonate_supervisor(agent):
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute(
            "select public.agent_submit_proposal('supervisor', 'other_sensitive', 'Prueba', '',"
            " '{\"description\": \"intento de suplantación\"}', 'low', 0, 'k-impersonate-1')"
        )


# --- Los agentes no pueden aprobar --------------------------------------------


def test_agent_cannot_update_proposals_directly(agent, submit):
    pid = submit()
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("update public.proposals set status = 'approved' where id = %s", (pid,))


def test_agent_cannot_call_approve(agent, submit):
    pid = submit()
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("select public.approve_proposal(%s, 'x')", (pid,))


def test_supervisor_cannot_call_approve(supervisor, submit):
    pid = submit()
    with pytest.raises(errors.InsufficientPrivilege):
        supervisor.execute("select public.approve_proposal(%s, 'x')", (pid,))


def test_executor_cannot_call_approve_or_review(executor, submit):
    pid = submit()
    with pytest.raises(errors.InsufficientPrivilege):
        executor.execute("select public.approve_proposal(%s, 'x')", (pid,))
    with pytest.raises(errors.InsufficientPrivilege):
        executor.execute("select public.supervisor_review(%s, 'ok', '')", (pid,))


def test_anon_has_no_access(anon, submit):
    pid = submit()
    with pytest.raises(errors.InsufficientPrivilege):
        anon.execute("select * from public.proposals")
    with pytest.raises(errors.InsufficientPrivilege):
        anon.execute("select public.approve_proposal(%s, 'x')", (pid,))


# --- Supervisor -----------------------------------------------------------------


def test_supervisor_ok_moves_to_pending_approval(admin, supervisor, submit):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    assert _status(admin, pid) == "pending_approval"


def test_supervisor_reject(admin, supervisor, submit):
    pid = submit()
    supervisor.execute("select public.supervisor_review(%s, 'rejected', 'Tono incorrecto')", (pid,))
    assert _status(admin, pid) == "rejected"


def test_supervisor_cannot_review_twice(supervisor, submit):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    with pytest.raises(errors.CheckViolation):
        _to_pending_approval(supervisor, pid)


def test_supervisor_cannot_review_own_proposal(admin, supervisor):
    # Aunque una propuesta del supervisor llegara a existir (insertada por admin),
    # no podría revisarla.
    pid = admin.execute(
        "insert into public.proposals (action_type, title, payload, payload_hash,"
        " proposed_by_agent, idempotency_key, expires_at) values ('other_sensitive', 'Propia',"
        " '{}', '', 'supervisor', 'k-own-proposal-1', now() + interval '1 day') returning id"
    ).fetchone()["id"]
    with pytest.raises(errors.InsufficientPrivilege):
        _to_pending_approval(supervisor, str(pid))


# --- Humanos ------------------------------------------------------------------


def test_owner_approves_with_correct_hash(admin, supervisor, submit, make_human):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    uid, owner = make_human("owner")
    owner.execute("select public.approve_proposal(%s, %s, 'Adelante')", (pid, _hash(admin, pid)))
    row = admin.execute(
        "select status, decided_by::text, approved_hash = payload_hash as same"
        " from public.proposals where id = %s",
        (pid,),
    ).fetchone()
    assert row == {"status": "approved", "decided_by": uid, "same": True}


def test_owner_cannot_skip_supervisor(admin, submit, make_human):
    pid = submit()
    _, owner = make_human("owner")
    with pytest.raises(errors.CheckViolation):
        owner.execute("select public.approve_proposal(%s, %s)", (pid, _hash(admin, pid)))


def test_wrong_hash_is_rejected(supervisor, submit, make_human):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    _, owner = make_human("owner")
    with pytest.raises(errors.CheckViolation):
        owner.execute("select public.approve_proposal(%s, %s)", (pid, "0" * 64))


def test_viewer_and_unknown_users_cannot_approve(admin, supervisor, submit, make_human):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    h = _hash(admin, pid)
    for role in ("viewer", None):
        _, human = make_human(role)
        with pytest.raises(errors.InsufficientPrivilege):
            human.execute("select public.approve_proposal(%s, %s)", (pid, h))
    assert _status(admin, pid) == "pending_approval"


def test_owner_cannot_update_proposals_directly(supervisor, submit, make_human):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    _, owner = make_human("owner")
    with pytest.raises(errors.InsufficientPrivilege):
        owner.execute("update public.proposals set status = 'approved' where id = %s", (pid,))


def test_expired_proposal_cannot_be_approved(admin, supervisor, submit, make_human):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    admin.execute(
        "update public.proposals set expires_at = now() - interval '1 minute' where id = %s",
        (pid,),
    )
    _, owner = make_human("owner")
    with pytest.raises(errors.CheckViolation):
        owner.execute("select public.approve_proposal(%s, %s)", (pid, _hash(admin, pid)))


def test_owner_reject(admin, submit, make_human):
    pid = submit()
    _, owner = make_human("owner")
    owner.execute("select public.reject_proposal(%s, 'No encaja con la marca')", (pid,))
    assert _status(admin, pid) == "rejected"


# --- Inmutabilidad (incluso para el administrador) --------------------------------


def test_payload_is_immutable_even_for_admin(admin, submit):
    pid = submit()
    with pytest.raises(errors.CheckViolation):
        admin.execute(
            'update public.proposals set payload = \'{"new_price": "0.01"}\' where id = %s',
            (pid,),
        )


def test_invalid_transition_blocked_even_for_admin(admin, submit):
    pid = submit()
    with pytest.raises(errors.CheckViolation):
        admin.execute("update public.proposals set status = 'executing' where id = %s", (pid,))


def test_admin_cannot_approve_without_owner_and_hash(admin, submit, supervisor):
    pid = submit()
    _to_pending_approval(supervisor, pid)
    with pytest.raises(errors.CheckViolation):
        admin.execute("update public.proposals set status = 'approved' where id = %s", (pid,))


def test_proposals_cannot_be_deleted(admin, submit):
    pid = submit()
    with pytest.raises(errors.InsufficientPrivilege):
        admin.execute("delete from public.proposals where id = %s", (pid,))


# --- Ejecutor -----------------------------------------------------------------


@pytest.fixture
def approved(admin, supervisor, submit, make_human):
    def _approved() -> tuple[str, str]:
        pid = submit()
        _to_pending_approval(supervisor, pid)
        uid, owner = make_human("owner")
        owner.execute("select public.approve_proposal(%s, %s)", (pid, _hash(admin, pid)))
        return pid, uid

    return _approved


def test_executor_cannot_claim_unapproved(admin, executor, supervisor, submit):
    pid = submit()
    assert _claim(executor, pid) == []
    _to_pending_approval(supervisor, pid)
    assert _claim(executor, pid) == []
    assert _status(admin, pid) == "pending_approval"


def test_executor_claims_once_and_completes(admin, executor, approved):
    pid, _ = approved()
    rows = _claim(executor, pid)
    assert len(rows) == 1 and rows[0]["attempt"] == 1
    assert _claim(executor, pid) == []
    executor.execute("select public.executor_complete(%s, true, '{\"ok\": true}')", (pid,))
    assert _status(admin, pid) == "executed"


def test_executor_refuses_if_approver_lost_owner_role(admin, executor, approved):
    pid, uid = approved()
    admin.execute("update public.profiles set role = 'viewer' where user_id = %s", (uid,))
    assert _claim(executor, pid) == []
    assert _status(admin, pid) == "approved"


def test_executor_cannot_read_or_write_tables_directly(executor, approved):
    pid, _ = approved()
    with pytest.raises(errors.InsufficientPrivilege):
        executor.execute("select * from public.proposals")
    with pytest.raises(errors.InsufficientPrivilege):
        executor.execute("update public.proposals set status = 'executed' where id = %s", (pid,))


def test_failed_execution_can_retry_up_to_three(admin, executor, approved):
    pid, _ = approved()
    for attempt in (1, 2, 3):
        rows = executor.execute(
            "select * from public.executor_claim_proposal(%s)", (pid,)
        ).fetchall()
        assert rows[0]["attempt"] == attempt
        executor.execute("select public.executor_complete(%s, false, '{}')", (pid,))
    assert _claim(executor, pid) == []
    assert _status(admin, pid) == "failed"


def test_expire_proposals(admin, submit):
    pid = submit()
    admin.execute(
        "update public.proposals set expires_at = now() - interval '1 minute' where id = %s",
        (pid,),
    )
    admin.execute("select public.expire_proposals()")
    assert _status(admin, pid) == "expired"
