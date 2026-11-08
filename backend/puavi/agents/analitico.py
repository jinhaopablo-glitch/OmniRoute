"""Agente Analítico: recoge métricas diarias de ventas y redes (sin coste de IA)."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from puavi.agents.base import AgentContext, job

log = logging.getLogger("puavi.agents.analitico")


@job("analitico", "metrics.daily")
def metrics_daily(ctx: AgentContext) -> dict[str, Any]:
    day = date.fromisoformat(ctx.payload.get("date") or ctx.today) - timedelta(days=1)
    saved: dict[str, Any] = {"day": day.isoformat()}
    sources = {
        "shopify": (lambda: ctx.services.shopify.orders_summary(day))
        if ctx.services.shopify
        else None,
        "instagram": (lambda: ctx.services.instagram.daily_insights(day))
        if ctx.services.instagram
        else None,
        "tiktok": (lambda: ctx.services.tiktok.user_stats()) if ctx.services.tiktok else None,
    }
    errors = {}
    for name, fetch in sources.items():
        if fetch is None:
            saved[name] = "no configurado"
            continue
        try:
            metrics = fetch()
        except Exception as exc:  # noqa: BLE001 - una fuente caída no detiene las demás
            log.warning("Métricas %s fallaron: %s", name, exc)
            errors[name] = str(exc)[:300]
            continue
        ctx.conn.execute(
            "select public.agent_save_metrics(%s, %s, %s)",
            (day, name, json.dumps(metrics, default=str)),
        )
        saved[name] = "ok"
    if errors and len(errors) == sum(1 for f in sources.values() if f):
        raise RuntimeError(f"Todas las fuentes de métricas fallaron: {errors}")
    saved["errors"] = errors
    return saved
