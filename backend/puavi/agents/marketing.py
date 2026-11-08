"""Agente de Marketing: tendencias e ideas para TikTok e Instagram."""

from __future__ import annotations

import json
from typing import Any

from puavi.agents.base import AgentContext, job, system_prompt
from puavi.agents.schemas import TrendsOutput

ROLE = """Agente de Marketing. Investigas tendencias actuales en TikTok e Instagram en España
relacionadas con perros, gatos y sus dueños (formatos, sonidos, temas, fechas señaladas) y las
conviertes en ideas de contenido concretas para PUAVI. Prioriza ideas realizables con fotos o
vídeos de producto y mascotas reales, sin presupuesto de producción alto."""


@job("marketing", "trends.daily")
def trends_daily(ctx: AgentContext) -> dict[str, Any]:
    recent = ctx.conn.execute(
        "select title from public.content_items where kind in ('trend', 'idea')"
        " and created_at > now() - interval '14 days' order by created_at desc limit 40"
    ).fetchall()
    model, effort = ctx.agent_config("marketing")
    prompt = (
        f"Hoy es {ctx.today}. Busca en la web tendencias recientes (últimos 14 días) útiles "
        "para PUAVI. Devuelve 3-6 tendencias con URLs de evidencia y 4-6 ideas de contenido. "
        "Evita repetir estos temas ya trabajados:\n"
        + json.dumps([r["title"] for r in recent], ensure_ascii=False)
    )
    result = ctx.llm.run(
        ctx.conn,
        agent_id="marketing",
        model=model,
        effort=effort,
        system=system_prompt(ROLE),
        prompt=prompt,
        output_model=TrendsOutput,
        web_search=True,
        max_searches=6,
        job_id=ctx.job_id,
        summary="Tendencias del día",
    )
    out = result.output
    saved = {"trends": 0, "ideas": 0}
    for t in out.trends[:6]:
        ctx.conn.execute(
            "select public.agent_save_content('marketing', 'trend', %s, %s, %s, null, '{}', null,"
            " %s, 'draft')",
            (t.platform, t.title[:200], json.dumps(t.model_dump(), ensure_ascii=False), ctx.job_id),
        )
        saved["trends"] += 1
    for idea in out.ideas[:6]:
        ctx.conn.execute(
            "select public.agent_save_content('marketing', 'idea', %s, %s, %s, null, '{}', null,"
            " %s, 'draft')",
            (
                idea.platform,
                idea.title[:200],
                json.dumps(idea.model_dump(), ensure_ascii=False),
                ctx.job_id,
            ),
        )
        saved["ideas"] += 1
    if out.injection_warnings:
        ctx.conn.execute(
            "select public.log_event('agent', 'marketing', 'security.injection_warning', 'job', %s,"
            " %s)",
            (ctx.job_id, json.dumps({"warnings": out.injection_warnings[:10]})),
        )
    return saved
