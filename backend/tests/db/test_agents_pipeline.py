"""Flujo completo de los agentes contra Postgres real, con la IA simulada.

tendencias -> ideas -> guiones -> supervisor -> vídeo (FFmpeg real) -> propuestas ->
supervisor -> aprobación humana -> ejecutor -> publicado. Y el resto de agentes.
"""

from __future__ import annotations

import shutil
import uuid

import pytest

from puavi.agents.base import Services
from puavi.agents.schemas import (
    ContentIdea,
    DailyReportOutput,
    Priority,
    ProductFinding,
    ReviewItem,
    ReviewOutput,
    Scene,
    Script,
    ScriptsOutput,
    ShopifyAuditOutput,
    Trend,
    TrendsOutput,
)
from puavi.core import jobs
from puavi.executor.handlers import build_registry
from puavi.executor.runner import execute_one
from puavi.integrations.storage import LocalStorage
from puavi.llm.client import AgentLLM
from puavi.worker.runner import process_job
from tests.fakes import FakeAnthropic, FakeInstagram, FakeShopify, product

pytestmark = pytest.mark.db
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin FFmpeg")


def _trends(_):
    return TrendsOutput(
        trends=[
            Trend(
                title=f"Paseos de otoño {uuid.uuid4().hex[:4]}",
                description="Auge",
                platform="tiktok",
                relevance=80,
                evidence_urls=["https://ejemplo.es"],
            )
        ],
        ideas=[
            ContentIdea(
                title=f"Arnés en 3 pasos {uuid.uuid4().hex[:4]}",
                platform="both",
                format="reel",
                hook="¿Tu perro se escapa?",
                why="Útil",
            )
        ],
        injection_warnings=[],
    )


def _scripts(kwargs):
    # El prompt incluye las ideas en JSON; extraemos los ids reales.
    import re

    prompt = kwargs["messages"][0]["content"]
    ids = re.findall(r'"id": "([0-9a-f-]{36})"', prompt)
    return ScriptsOutput(
        scripts=[
            Script(
                idea_id=i,
                title="Arnés en 3 pasos",
                platform="both",
                hook="¿Se escapa?",
                scenes=[
                    Scene(seconds=2, visual="perro", voiceover="", on_screen_text="¿Se escapa?"),
                    Scene(seconds=2, visual="arnés", voiceover="", on_screen_text="Así no"),
                ],
                caption="Paseos tranquilos 🐶",
                hashtags=["perros", "#puavi"],
                product_handle="arnes-acolchado",
            )
            for i in ids
        ]
    )


def _review_all_ok(kwargs):
    import re

    ids = re.findall(r'"item_id": "([0-9a-f-]{36})"', kwargs["messages"][0]["content"])
    return ReviewOutput(
        reviews=[ReviewItem(item_id=i, verdict="ok", issues=[], notes="OK") for i in ids]
    )


@pytest.fixture
def llm():
    return AgentLLM(
        client=FakeAnthropic(
            {
                TrendsOutput: _trends,
                ScriptsOutput: _scripts,
                ReviewOutput: _review_all_ok,
                DailyReportOutput: lambda _: DailyReportOutput(
                    title="Informe",
                    summary_md="## Resumen\nTodo bien",
                    priorities=[
                        Priority(title="Revisar aprobaciones", description="Hay vídeos", priority=1)
                    ],
                ),
                ShopifyAuditOutput: lambda kw: ShopifyAuditOutput(
                    findings=[
                        ProductFinding(
                            product_id="gid://shopify/Product/1",
                            score=55,
                            issues=["Descripción pobre"],
                            new_description_html=(
                                "<p>Arnés <strong>acolchado</strong></p><script>x</script>"
                            ),
                            price_suggestion_eur=22.9,
                            price_variant_id="gid://shopify/ProductVariant/1",
                            price_reason="Competencia a 22,50 €",
                            manual_tasks=["Añadir foto con perro"],
                        )
                    ]
                ),
            }
        )
    )


def _run(admin, agent, supervisor, llm, services, agent_id, kind, payload=None):
    jid = jobs.enqueue(agent, agent_id, kind, payload or {}, priority=0)
    job = admin.execute("select * from public.jobs where id = %s", (jid,)).fetchone()
    admin.execute(
        "update public.jobs set status = 'running', locked_by = 'test',"
        " locked_at = now(), attempts = 1 where id = %s",
        (jid,),
    )
    status = process_job(
        job, conn=agent, sup_conn=supervisor, llm=llm, services=services, worker_id="test"
    )
    row = admin.execute(
        "select status, last_error, result from public.jobs where id = %s", (jid,)
    ).fetchone()
    assert status == "done", row
    return row["result"]


def test_daily_plan_enqueues_all_agents(admin, agent, supervisor, llm):
    res = _run(
        admin, agent, supervisor, llm, Services(), "principal", "daily.plan", {"date": "2030-01-01"}
    )
    kinds = [j["kind"] for j in res["jobs"]]
    assert {
        "metrics.daily",
        "trends.daily",
        "research.daily",
        "shopify.audit",
        "content.scripts",
        "video.render",
        "review.pending",
        "daily.report",
    } <= set(kinds)


@needs_ffmpeg
def test_full_content_pipeline_to_publication(
    admin, agent, supervisor, executor, llm, tmp_path, make_human
):
    shop = FakeShopify([product()])
    storage = LocalStorage(tmp_path)
    services = Services(shopify=shop, storage=storage)

    r = _run(admin, agent, supervisor, llm, services, "marketing", "trends.daily")
    assert r == {"trends": 1, "ideas": 1}
    r = _run(admin, agent, supervisor, llm, services, "creativo", "content.scripts")
    assert r["scripts"] >= 1
    r = _run(admin, agent, supervisor, llm, services, "supervisor", "review.pending")
    assert r["scripts_ok"] >= 1

    r = _run(admin, agent, supervisor, llm, services, "creativo", "video.render")
    assert r["videos"], "debería renderizar al menos un vídeo"
    video_id = r["videos"][0]
    video = admin.execute(
        "select media_paths, body from public.content_items where id = %s", (video_id,)
    ).fetchone()
    assert (tmp_path / video["media_paths"][0]).stat().st_size > 10_000
    assert video["body"]["duration_s"] >= 3

    # El vídeo genera propuestas de publicación (Instagram y TikTok), pendientes de revisión.
    props = admin.execute(
        "select id, payload, status from public.proposals where payload->>'content_item_id' = %s",
        (video_id,),
    ).fetchall()
    assert {p["payload"]["platform"] for p in props} == {"instagram", "tiktok"}
    assert all(p["status"] == "pending_review" for p in props)

    _run(admin, agent, supervisor, llm, services, "supervisor", "review.pending")
    ig = next(p for p in props if p["payload"]["platform"] == "instagram")
    assert (
        admin.execute("select status from public.proposals where id = %s", (ig["id"],)).fetchone()[
            "status"
        ]
        == "pending_approval"
    )

    # Sin aprobación humana, el ejecutor no puede hacer nada.
    insta = FakeInstagram()
    registry = build_registry(conn=executor, instagram=insta, storage=storage)
    executor.autocommit = False
    assert execute_one(executor, str(ig["id"]), registry) is None
    executor.autocommit = True
    assert insta.published == []

    _, owner = make_human("owner")
    h = admin.execute(
        "select payload_hash from public.proposals where id = %s", (ig["id"],)
    ).fetchone()["payload_hash"]
    owner.execute("select public.approve_proposal(%s, %s)", (ig["id"], h))
    executor.autocommit = False
    result = execute_one(executor, str(ig["id"]), registry)
    executor.autocommit = True
    assert result.success and len(insta.published) == 1
    assert "#perros" in insta.published[0][1]
    row = admin.execute(
        "select status, published_url from public.content_items where id = %s", (video_id,)
    ).fetchone()
    assert row == {"status": "published", "published_url": "https://www.instagram.com/reel/abc/"}


def test_shopify_audit_creates_proposals_and_tasks(admin, agent, supervisor, llm):
    shop = FakeShopify([product()])
    r = _run(admin, agent, supervisor, llm, Services(shopify=shop), "shopify", "shopify.audit")
    assert r == {"modify": 1, "price": 1, "tasks": 1}
    modify = admin.execute(
        "select payload from public.proposals where action_type = 'modify_product'"
        " order by created_at desc limit 1"
    ).fetchone()["payload"]
    assert "<script>" not in modify["changes"]["description_html"]
    assert "<strong>acolchado</strong>" in modify["changes"]["description_html"]
    assert shop.updates == []  # el agente nunca escribe en Shopify


def test_metrics_and_daily_report(admin, agent, supervisor, llm):
    services = Services(shopify=FakeShopify([]), instagram=FakeInstagram())
    r = _run(
        admin,
        agent,
        supervisor,
        llm,
        services,
        "analitico",
        "metrics.daily",
        {"date": "2030-02-02"},
    )
    assert r["shopify"] == "ok" and r["instagram"] == "ok" and r["tiktok"] == "no configurado"
    r = _run(
        admin, agent, supervisor, llm, services, "principal", "daily.report", {"date": "2030-02-02"}
    )
    report = admin.execute(
        "select title, body_md from public.reports where id = %s", (r["report_id"],)
    ).fetchone()
    assert report["title"] == "Informe"
    assert (
        admin.execute(
            "select count(*) as n from public.tasks where created_by = 'principal'"
        ).fetchone()["n"]
        >= 1
    )


def test_agent_runs_record_cost(admin):
    row = admin.execute(
        "select count(*) as n, sum(cost_usd) as c from public.agent_runs where status = 'ok'"
    ).fetchone()
    assert row["n"] >= 1 and row["c"] > 0


def test_budget_blocks_llm_jobs(admin, agent, supervisor, llm):
    admin.execute("update public.settings set value = 'true' where key = 'kill_switch'")
    try:
        jid = jobs.enqueue(agent, "marketing", "trends.daily", {}, priority=0)
        job = admin.execute("select * from public.jobs where id = %s", (jid,)).fetchone()
        admin.execute(
            "update public.jobs set status = 'running', locked_by = 'test',"
            " locked_at = now(), attempts = 1 where id = %s",
            (jid,),
        )
        status = process_job(
            job, conn=agent, sup_conn=supervisor, llm=llm, services=Services(), worker_id="test"
        )
        assert status == "queued"
        err = admin.execute("select last_error from public.jobs where id = %s", (jid,)).fetchone()[
            "last_error"
        ]
        assert "emergencia" in err
        assert llm.client.messages.calls == []  # no se gastó nada
    finally:
        admin.execute("update public.settings set value = 'false' where key = 'kill_switch'")


def test_owner_request_run(admin, make_human, agent):
    _, owner = make_human("owner")
    jid = owner.execute("select public.request_run('trends.daily') as id").fetchone()["id"]
    assert (
        admin.execute("select agent_id from public.jobs where id = %s", (jid,)).fetchone()[
            "agent_id"
        ]
        == "marketing"
    )
    _, viewer = make_human("viewer")
    from psycopg import errors

    with pytest.raises(errors.InsufficientPrivilege):
        viewer.execute("select public.request_run('trends.daily')")
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("select public.request_run('trends.daily')")


def test_agents_cannot_publish_content(agent, admin):
    from psycopg import errors

    cid = agent.execute(
        "select public.agent_save_content('creativo', 'post', 'instagram', 'Post', '{}', null,"
        " '{}', null, null, 'draft') as id"
    ).fetchone()["id"]
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("select public.agent_update_content('creativo', %s, 'published')", (cid,))
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("select public.executor_mark_published(%s, 'x')", (cid,))
