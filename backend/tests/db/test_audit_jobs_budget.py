"""Auditoría inalterable, cola de trabajos, presupuesto y tareas."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors

pytestmark = pytest.mark.db


# --- Auditoría -------------------------------------------------------------------


def test_actions_are_audited(admin, submit):
    pid = submit()
    rows = admin.execute(
        "select actor_type, actor_id, action from public.audit_log where entity_id = %s",
        (pid,),
    ).fetchall()
    assert {"actor_type": "agent", "actor_id": "shopify", "action": "proposal.created"} in rows


def test_audit_log_cannot_be_modified_even_by_admin(admin, submit):
    submit()
    with pytest.raises(errors.InsufficientPrivilege):
        admin.execute("update public.audit_log set actor_id = 'otro'")
    with pytest.raises(errors.InsufficientPrivilege):
        admin.execute("delete from public.audit_log")
    with pytest.raises(errors.InsufficientPrivilege):
        admin.execute("truncate public.audit_log")


def test_processes_cannot_insert_audit_rows_directly(agent, executor):
    for conn in (agent, executor):
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(
                "insert into public.audit_log (actor_type, actor_id, action, entity_type,"
                " prev_hash, hash) values ('human', 'x', 'fake.action', 'x', '', '')"
            )


def test_process_cannot_log_as_human(agent):
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("select public.log_event('human', 'x', 'fake.action', 'x')")


def test_chain_verifies_and_detects_tampering(admin, agent, db_dsn):
    agent.execute("select public.log_event('agent', 'marketing', 'trend.found', 'trend', '1')")
    assert admin.execute("select * from public.audit_verify_chain()").fetchone()["ok"] is True

    # Manipulación simulada saltándose los triggers (solo posible para un superusuario).
    with psycopg.connect(db_dsn, autocommit=False) as raw:
        raw.execute("set session_replication_role = replica")
        raw.execute(
            "update public.audit_log set actor_id = 'manipulado'"
            " where id = (select min(id) from public.audit_log)"
        )
        raw.commit()
        result = raw.execute("select ok, first_broken_id from public.audit_verify_chain()")
        ok, broken = result.fetchone()
        raw.rollback()
    assert ok is False and broken is not None


def test_human_task_changes_are_audited_as_human(admin, make_human):
    uid, owner = make_human("owner")
    tid = owner.execute(
        "insert into public.tasks (title) values ('Revisar fotos del comedero') returning id"
    ).fetchone()["id"]
    row = admin.execute(
        "select actor_type, actor_id from public.audit_log"
        " where entity_type = 'tasks' and entity_id = %s",
        (str(tid),),
    ).fetchone()
    assert row == {"actor_type": "human", "actor_id": uid}


# --- Panel: RLS ------------------------------------------------------------------


def test_viewer_reads_but_cannot_write(make_human):
    _, viewer = make_human("viewer")
    assert viewer.execute("select count(*) as n from public.agents").fetchone()["n"] == 7
    with pytest.raises(errors.InsufficientPrivilege):
        viewer.execute("insert into public.tasks (title) values ('No debería')")


def test_user_without_profile_sees_nothing(make_human):
    _, stranger = make_human(None)
    assert stranger.execute("select count(*) as n from public.agents").fetchone()["n"] == 0


def test_owner_can_toggle_kill_switch(admin, make_human):
    uid, owner = make_human("owner")
    owner.execute(
        "update public.settings set value = 'true', updated_by = %s where key = 'kill_switch'",
        (uid,),
    )
    try:
        assert (
            admin.execute("select (public.check_budget('marketing')).allowed").fetchone()["allowed"]
            is False
        )
    finally:
        admin.execute("update public.settings set value = 'false' where key = 'kill_switch'")


def test_no_grants_to_anon_anywhere(admin):
    tables = admin.execute(
        "select count(*) as n from information_schema.role_table_grants"
        " where grantee = 'anon' and table_schema = 'public'"
    ).fetchone()["n"]
    funcs = admin.execute(
        "select count(*) as n from information_schema.role_routine_grants"
        " where grantee in ('anon', 'PUBLIC') and routine_schema = 'public'"
    ).fetchone()["n"]
    assert tables == 0 and funcs == 0


def test_authenticated_can_only_execute_allowlisted_functions(admin):
    rows = admin.execute(
        "select distinct routine_name from information_schema.role_routine_grants"
        " where grantee = 'authenticated' and routine_schema = 'public'"
    ).fetchall()
    assert {r["routine_name"] for r in rows} == {
        "current_human_role",
        "approve_proposal",
        "reject_proposal",
        "audit_verify_chain",
    }


# --- Cola de trabajos --------------------------------------------------------------


def test_job_queue_lifecycle(admin, agent):
    jid = agent.execute(
        "select public.enqueue_job('marketing', 'trends.daily', '{}', now(), 1, null, null) as id"
    ).fetchone()["id"]
    claimed = agent.execute(
        "select * from public.claim_jobs('w1', 5, array['marketing'])"
    ).fetchall()
    assert jid in [j["id"] for j in claimed]
    # Otro worker no puede tomar el mismo trabajo.
    other = agent.execute(
        "select id from public.claim_jobs('w2', 20, array['marketing'])"
    ).fetchall()
    assert jid not in [j["id"] for j in other]
    agent.execute("select public.complete_job(%s, 'w1', '{\"ideas\": 3}')", (jid,))
    assert (
        admin.execute("select status from public.jobs where id = %s", (jid,)).fetchone()["status"]
        == "done"
    )


def test_job_retry_then_fail(admin, agent):
    jid = agent.execute(
        "select public.enqueue_job('analitico', 'metrics.daily', '{}', now(), 1, null, null) as id"
    ).fetchone()["id"]
    admin.execute("update public.jobs set max_attempts = 2 where id = %s", (jid,))
    for expected in ("queued", "failed"):
        admin.execute("update public.jobs set run_after = now() where id = %s", (jid,))
        agent.execute("select * from public.claim_jobs('w1', 20, array['analitico'])")
        status = agent.execute(
            "select public.fail_job(%s, 'w1', 'timeout') as s", (jid,)
        ).fetchone()["s"]
        assert status == expected


def test_dedupe_key(agent):
    q = (
        "select public.enqueue_job('principal', 'daily.plan', '{}', now(), 10, 'daily:x', null)"
        " as id"
    )
    assert agent.execute(q).fetchone()["id"] == agent.execute(q).fetchone()["id"]


def test_agent_cannot_write_jobs_directly(agent):
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("insert into public.jobs (agent_id, kind) values ('marketing', 'x.y.z')")


# --- Presupuesto ---------------------------------------------------------------------


def test_budget_blocks_when_limit_reached(admin, agent):
    admin.execute(
        "insert into public.budget_limits (scope, period, limit_usd)"
        " values ('creativo', 'daily', 0.50)"
    )
    assert agent.execute("select (public.check_budget('creativo')).allowed").fetchone()["allowed"]
    agent.execute(
        "select public.record_agent_run('creativo', null, 'claude-opus-5-5', 1000, 1000, 0, 0, 0,"
        " 0.60, 'ok', 'guiones', null)"
    )
    row = agent.execute("select * from public.check_budget('creativo')").fetchone()
    assert row["allowed"] is False and "agente" in row["reason"]


def test_disabled_agent_has_no_budget(admin, agent):
    admin.execute("update public.agents set enabled = false where id = 'investigacion'")
    try:
        row = agent.execute("select * from public.check_budget('investigacion')").fetchone()
        assert row["allowed"] is False
    finally:
        admin.execute("update public.agents set enabled = true where id = 'investigacion'")


# --- Tareas de agentes -----------------------------------------------------------------


def test_agent_tasks_scoped_to_agent(agent):
    tid = agent.execute(
        "select public.agent_create_task('marketing', 'Preparar campaña otoño', '', 2, 'creativo',"
        " null) as id"
    ).fetchone()["id"]
    agent.execute("select public.agent_update_task_status('creativo', %s, 'in_progress')", (tid,))
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("select public.agent_update_task_status('analitico', %s, 'done')", (tid,))
