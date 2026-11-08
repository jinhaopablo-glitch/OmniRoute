"""Manejadores reales del ejecutor. Solo se registran los que tienen credenciales."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from puavi.core.proposals import ActionType
from puavi.executor.registry import ExecutionContext, ExecutionResult, HandlerRegistry
from puavi.integrations.brevo import BrevoClient
from puavi.integrations.instagram import InstagramClient
from puavi.integrations.meta_ads import MetaAdsClient
from puavi.integrations.shopify import ShopifyClient
from puavi.integrations.storage import Storage
from puavi.integrations.tiktok import TikTokClient


def manual_handler(kind: str):
    """Para gastos y otras acciones: nunca se pagan ni compran automáticamente."""

    def handler(payload: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            True,
            {
                "manual": True,
                "mensaje": f"Aprobado. {kind}: realízalo tú manualmente; "
                "PUAVI AI nunca paga ni compra.",
            },
        )

    return handler


def build_registry(
    *,
    conn: psycopg.Connection | None = None,
    shopify: ShopifyClient | None = None,
    instagram: InstagramClient | None = None,
    tiktok: TikTokClient | None = None,
    tiktok_mode: str = "inbox",
    storage: Storage | None = None,
    meta_ads: MetaAdsClient | None = None,
    brevo: BrevoClient | None = None,
) -> HandlerRegistry:
    reg = HandlerRegistry()
    reg.register(ActionType.SPEND_MONEY, manual_handler("Gasto"))
    reg.register(ActionType.OTHER_SENSITIVE, manual_handler("Acción"))

    if shopify:

        def change_price(p: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
            return ExecutionResult(
                True,
                shopify.update_variant_price(
                    p["product_id"], p["variant_id"], Decimal(p["new_price"])
                ),
            )

        def modify_product(p: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
            return ExecutionResult(True, shopify.update_product(p["product_id"], p["changes"]))

        reg.register(ActionType.CHANGE_PRICE, change_price)
        reg.register(ActionType.MODIFY_PRODUCT, modify_product)

    if storage and (instagram or tiktok):

        def publish(p: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
            path = p["media_paths"][0]
            if p["platform"] == "instagram":
                if not instagram:
                    return ExecutionResult(False, {"error": "Instagram no configurado"})
                res = instagram.publish_reel(storage.signed_url(path, 3600), p["caption"])
                url = res.get("url", "")
            else:
                if not tiktok:
                    return ExecutionResult(False, {"error": "TikTok no configurado"})
                with tempfile.TemporaryDirectory() as tmp:
                    video = Path(tmp) / "video.mp4"
                    video.write_bytes(storage.download(path))
                    res = tiktok.upload_video(video, mode=tiktok_mode, caption=p["caption"])
                url = ""
            if conn is not None:
                conn.execute(
                    "select public.executor_mark_published(%s, %s)",
                    (p["content_item_id"], url or None),
                )
            return ExecutionResult(True, res)

        reg.register(ActionType.PUBLISH_CONTENT, publish)

    if meta_ads:

        def launch_ad(p: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
            if p["platform"] != "meta":
                return ExecutionResult(
                    False, {"error": "Solo hay integración de anuncios con Meta"}
                )
            res = meta_ads.create_paused_campaign(
                name=p["campaign_name"],
                daily_budget_eur=Decimal(p["daily_budget_eur"]),
                start_date=p["start_date"],
                end_date=p["end_date"],
                idempotency_key=ctx.idempotency_key,
            )
            res["mensaje"] = (
                "Campaña creada EN PAUSA. Revísala y actívala en el Administrador de anuncios."
            )
            return ExecutionResult(True, res)

        reg.register(ActionType.LAUNCH_AD, launch_ad)

    if brevo:

        def send_comm(p: dict[str, Any], ctx: ExecutionContext) -> ExecutionResult:
            if p["channel"] != "email":
                return ExecutionResult(False, {"error": "Solo hay integración de email (Brevo)"})
            if not p["audience_segment"].isdigit():
                return ExecutionResult(
                    False, {"error": "audience_segment debe ser el ID de lista de Brevo"}
                )
            return ExecutionResult(
                True,
                brevo.send_campaign(
                    name=f"PUAVI {ctx.idempotency_key[:12]}",
                    subject=p.get("subject") or "PUAVI",
                    html=p["body"],
                    list_id=int(p["audience_segment"]),
                ),
            )

        reg.register(ActionType.SEND_COMMERCIAL_COMM, send_comm)

    return reg
