"""Agente Principal: planifica el día, reparte trabajo y redacta el informe diario."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from puavi.agents.base import AgentContext, job, system_prompt
from puavi.agents.schemas import DailyReportOutput
from puavi.core import jobs

ROLE = """Agente Principal (coordinador). Revisas el trabajo del día de todos los agentes,
detectas problemas y redactas un informe diario claro y breve para la dueña/el dueño de PUAVI,
con las prioridades concretas para hoy. No inventes cifras: usa solo los datos proporcionados."""

# (agente, tipo, minutos de espera, prioridad)
DAILY_PLAN: list[tuple[str, str, int, int]] = [
    ("analitico", "metrics.daily", 0, 20),
    ("marketing", "trends.daily", 0, 30),
    ("investigacion", "research.daily", 5, 40),
    ("shopify", "shopify.audit", 10, 50),
    ("creativo", "content.scripts", 30, 30),
    ("supervisor", "review.pending", 45, 20),
    ("creativo", "video.render", 60, 40),
    ("supervisor", "review.pending", 90, 20),
    ("principal", "daily.report", 120, 10),
]


@job("principal", "daily.plan")
def daily_plan(ctx: AgentContext) -> dict[str, Any]:
    day = ctx.payload.get("date") or ctx.today
    created = []
    for i, (agent_id, kind, minutes, prio) in enumerate(DAILY_PLAN):
        jid = jobs.enqueue(
            ctx.conn,
            agent_id,
            kind,
            {"date": day},
            run_after=ctx.now + timedelta(minutes=minutes),
            priority=prio,
            dedupe_key=f"{kind}:{day}:{i}",
            parent_job_id=ctx.job_id,
        )
        created.append({"kind": kind, "job_id": jid})
    return {"date": day, "jobs": created}


def _gather(ctx: AgentContext, day: str) -> dict[str, Any]:
    q = ctx.conn.execute
    since = f"{day} 00:00:00+00"
    return {
        "metricas": q(
            "select source, metrics from public.metrics_daily where day >= %s::date - 1"
            " order by day desc",
            (day,),
        ).fetchall(),
        "tendencias": q(
            "select title, body from public.content_items where kind = 'trend'"
            " and created_at >= %s order by created_at desc limit 10",
            (since,),
        ).fetchall(),
        "contenido": q(
            "select kind, status, count(*) as n from public.content_items"
            " where created_at >= %s group by kind, status",
            (since,),
        ).fetchall(),
        "productos_investigados": q(
            "select name, score, estimated_margin_pct, rationale"
            " from public.research_products where created_at >= %s"
            " order by score desc nulls last limit 5",
            (since,),
        ).fetchall(),
        "competencia": q(
            "select c.name, s.summary from public.competitor_snapshots s"
            " join public.competitors c on c.id = s.competitor_id"
            " where s.created_at >= %s",
            (since,),
        ).fetchall(),
        "aprobaciones_pendientes": q(
            "select action_type, title, risk_level from public.proposals"
            " where status = 'pending_approval'"
        ).fetchall(),
        "trabajos_fallidos": q(
            "select kind, last_error from public.jobs where status = 'failed' and created_at >= %s",
            (since,),
        ).fetchall(),
        "gasto_ia_hoy_usd": q(
            "select global_daily_spent from public.check_budget('principal')"
        ).fetchone()["global_daily_spent"],
    }


@job("principal", "daily.report")
def daily_report(ctx: AgentContext) -> dict[str, Any]:
    day = ctx.payload.get("date") or ctx.today
    data = _gather(ctx, day)
    model, effort = ctx.agent_config("principal")
    prompt = (
        f"Fecha: {day}. Datos del día (JSON):\n"
        f"{json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        "Redacta el informe diario en Markdown (máx. 400 palabras) con estas secciones: "
        "Resumen, Ventas y tráfico, Contenido, Investigación y competencia, "
        "Pendiente de tu aprobación, Incidencias. Después indica de 1 a 5 prioridades "
        "concretas para hoy (prioridad 1 = urgente)."
    )
    result = ctx.llm.run(
        ctx.conn,
        agent_id="principal",
        model=model,
        effort=effort,
        system=system_prompt(ROLE),
        prompt=prompt,
        output_model=DailyReportOutput,
        job_id=ctx.job_id,
        summary=f"Informe diario {day}",
    )
    out = result.output
    report_id = ctx.conn.execute(
        "select public.agent_save_report('principal', %s, 'daily', %s, %s, %s) as id",
        (day, out.title, out.summary_md, json.dumps(data, default=str)),
    ).fetchone()["id"]
    for p in out.priorities[:5]:
        ctx.conn.execute(
            "select public.agent_create_task('principal', %s, %s, %s, null, %s::date)",
            (p.title[:200], p.description, p.priority, day),
        )
    return {"report_id": str(report_id), "priorities": len(out.priorities)}
