"""Agente de Investigación: productos, proveedores, competencia española y márgenes."""

from __future__ import annotations

import json
from typing import Any

from puavi.agents.base import AgentContext, job, system_prompt
from puavi.agents.schemas import ResearchOutput

ROLE = """Agente de Investigación. Buscas productos para perros y gatos con potencial para
PUAVI (calidad buena, precio medio, buen margen), analizas proveedores fiables y la competencia
española (precios, promociones, novedades). Calcula precios con IVA incluido (21 %). Usa solo
fuentes públicas. Nunca compres ni contactes con nadie."""


@job("investigacion", "research.daily")
def research_daily(ctx: AgentContext) -> dict[str, Any]:
    competitors = ctx.conn.execute(
        "select name, website from public.competitors order by name limit 10"
    ).fetchall()
    known = ctx.conn.execute(
        "select name from public.research_products order by created_at desc limit 50"
    ).fetchall()
    model, effort = ctx.agent_config("investigacion")
    prompt = (
        f"Hoy es {ctx.today}.\n"
        "1) Propón 3-5 productos para perros o gatos que PUAVI podría vender, con proveedor, "
        "coste unitario estimado, precio de venta sugerido (IVA incl.), precio de la competencia "
        "y una puntuación 0-100 de potencial. Indica fuentes.\n"
        "2) Revisa la competencia española y resume novedades, promociones y precios notables.\n"
        f"Competidores de referencia: {json.dumps(competitors, ensure_ascii=False)}. "
        "Si la lista está vacía, elige 3 tiendas online españolas relevantes.\n"
        f"No repitas estos productos: {json.dumps([k['name'] for k in known], ensure_ascii=False)}"
    )
    result = ctx.llm.run(
        ctx.conn,
        agent_id="investigacion",
        model=model,
        effort=effort,
        system=system_prompt(ROLE),
        prompt=prompt,
        output_model=ResearchOutput,
        web_search=True,
        max_searches=8,
        job_id=ctx.job_id,
        summary="Investigación diaria",
    )
    out = result.output
    for p in out.products[:5]:
        ctx.conn.execute(
            "select public.agent_save_research_product('investigacion', %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s)",
            (
                p.name[:200],
                p.category,
                p.pet,
                p.supplier,
                p.supplier_url or None,
                p.unit_cost_eur,
                p.suggested_price_eur,
                p.competitor_price_eur,
                p.score,
                p.rationale,
                json.dumps(p.sources),
            ),
        )
    for c in out.competitors[:6]:
        ctx.conn.execute(
            "select public.agent_save_competitor_snapshot('investigacion', %s, %s, %s, %s, %s)",
            (
                c.name[:200],
                c.website or None,
                c.summary,
                json.dumps(
                    {"promotions": c.promotions, "prices": c.notable_prices}, ensure_ascii=False
                ),
                json.dumps(c.sources),
            ),
        )
    return {"products": len(out.products[:5]), "competitors": len(out.competitors[:6])}
