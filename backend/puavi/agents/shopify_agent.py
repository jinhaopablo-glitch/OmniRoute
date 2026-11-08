"""Agente Shopify: auditoría de fichas y propuestas de mejora de conversión."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from puavi.agents.base import AgentContext, job, system_prompt
from puavi.agents.schemas import ShopifyAuditOutput
from puavi.core.proposals import ActionType, submit_proposal

ROLE = """Agente Shopify. Analizas fichas de producto (título, descripción, SEO, imágenes,
precios, stock) y propones mejoras de conversión concretas y realistas. Las descripciones deben
ser claras, útiles y con tono PUAVI, en HTML simple (<p>, <ul>, <li>, <strong>). No inventes
características: usa solo lo que aparece en la ficha. Solo sugiere cambios de precio con un
motivo sólido (competencia, margen, rotación)."""

_ALLOWED_TAGS = re.compile(r"</?(p|ul|ol|li|strong|em|br|h3)\s*/?>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")


def clean_html(html: str) -> str:
    """Deja solo etiquetas simples y seguras."""
    return _ANY_TAG.sub(lambda m: m.group(0) if _ALLOWED_TAGS.fullmatch(m.group(0)) else "", html)


@job("shopify", "shopify.audit")
def shopify_audit(ctx: AgentContext) -> dict[str, Any]:
    if ctx.services.shopify is None:
        return {"skipped": "Shopify no configurado"}
    products = ctx.services.shopify.list_products(
        limit=int(ctx.payload.get("limit", 6)), query="status:active"
    )
    if not products:
        return {"products": 0}
    by_id = {p["id"]: p for p in products}
    model, effort = ctx.agent_config("shopify")
    result = ctx.llm.run(
        ctx.conn,
        agent_id="shopify",
        model=model,
        effort=effort,
        system=system_prompt(ROLE),
        prompt="Audita estas fichas. Deja vacíos los campos que no cambiarías.\n"
        + json.dumps(products, ensure_ascii=False),
        output_model=ShopifyAuditOutput,
        job_id=ctx.job_id,
        summary=f"Auditoría de {len(products)} fichas",
    )
    stats = {"modify": 0, "price": 0, "tasks": 0}
    for f in result.output.findings:
        product = by_id.get(f.product_id)
        if product is None:
            continue
        changes: dict[str, Any] = {}
        if f.new_title and f.new_title != product["title"]:
            changes["title"] = f.new_title[:255]
        if f.new_description_html:
            changes["description_html"] = clean_html(f.new_description_html)[:20000]
        if f.new_seo_title:
            changes["seo_title"] = f.new_seo_title[:70]
        if f.new_seo_description:
            changes["seo_description"] = f.new_seo_description[:320]
        if changes:
            submit_proposal(
                ctx.conn,
                agent_id="shopify",
                action=ActionType.MODIFY_PRODUCT,
                title=f"Mejorar ficha: {product['title']}"[:200],
                summary="Problemas detectados: " + "; ".join(f.issues)[:3500],
                payload={
                    "product_id": f.product_id,
                    "changes": changes,
                    "reason": ("; ".join(f.issues) or "Mejora de conversión")[:1000],
                },
                idempotency_key=f"shopify-modify:{ctx.today}:{f.product_id}",
            )
            stats["modify"] += 1
        variants = {v["id"]: v for v in product["variants"]["nodes"]}
        variant = variants.get(f.price_variant_id)
        if f.price_suggestion_eur and variant and f.price_reason:
            current = Decimal(variant["price"])
            new = Decimal(str(f.price_suggestion_eur)).quantize(Decimal("0.01"))
            if new > 0 and new != current:
                submit_proposal(
                    ctx.conn,
                    agent_id="shopify",
                    action=ActionType.CHANGE_PRICE,
                    title=f"Precio {product['title']}: {current} € → {new} €"[:200],
                    summary=f.price_reason[:4000],
                    payload={
                        "product_id": f.product_id,
                        "variant_id": variant["id"],
                        "current_price": str(current),
                        "new_price": str(new),
                        "reason": f.price_reason[:1000],
                    },
                    idempotency_key=f"shopify-price:{ctx.today}:{variant['id']}",
                )
                stats["price"] += 1
        for t in f.manual_tasks[:3]:
            ctx.conn.execute(
                "select public.agent_create_task('shopify', %s, %s, 3, null, null)",
                (f"{product['title']}: {t}"[:200], t),
            )
            stats["tasks"] += 1
    return stats
