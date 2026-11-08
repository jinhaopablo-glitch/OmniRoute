"""Propuestas de acciones sensibles.

Los agentes nunca ejecutan acciones sensibles: crean una propuesta con un
contenido validado por esquema. La base de datos la hace inmutable, el
supervisor la revisa y solo un humano (owner) puede aprobarla.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ActionType(StrEnum):
    PUBLISH_CONTENT = "publish_content"
    CHANGE_PRICE = "change_price"
    MODIFY_PRODUCT = "modify_product"
    LAUNCH_AD = "launch_ad"
    SPEND_MONEY = "spend_money"
    SEND_COMMERCIAL_COMM = "send_commercial_comm"
    OTHER_SENSITIVE = "other_sensitive"


Risk = Literal["low", "medium", "high"]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublishContentPayload(_Payload):
    platform: Literal["instagram", "tiktok"]
    content_item_id: str = Field(min_length=1, max_length=64)
    caption: str = Field(min_length=1, max_length=2200)
    scheduled_for: str | None = None  # ISO 8601
    media_paths: list[str] = Field(min_length=1, max_length=10)


class ChangePricePayload(_Payload):
    product_id: str = Field(min_length=1, max_length=100)
    variant_id: str = Field(min_length=1, max_length=100)
    current_price: Money
    new_price: Money
    currency: Literal["EUR"] = "EUR"
    reason: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def _check_change(self) -> ChangePricePayload:
        if self.new_price == self.current_price:
            raise ValueError("El precio nuevo es igual al actual")
        if self.new_price <= 0:
            raise ValueError("El precio debe ser mayor que 0")
        return self

    @property
    def change_ratio(self) -> Decimal:
        if self.current_price == 0:
            return Decimal("1")
        return abs(self.new_price - self.current_price) / self.current_price


class ModifyProductPayload(_Payload):
    product_id: str = Field(min_length=1, max_length=100)
    changes: dict[
        Literal["title", "description_html", "seo_title", "seo_description", "tags"],
        Any,
    ] = Field(min_length=1)
    reason: str = Field(min_length=5, max_length=1000)


class LaunchAdPayload(_Payload):
    platform: Literal["meta", "tiktok"]
    campaign_name: str = Field(min_length=3, max_length=200)
    daily_budget_eur: Money
    total_budget_eur: Money
    start_date: str
    end_date: str
    creative_ids: list[str] = Field(min_length=1, max_length=10)
    targeting_summary: str = Field(min_length=5, max_length=2000)


class SpendMoneyPayload(_Payload):
    concept: str = Field(min_length=5, max_length=500)
    amount_eur: Money
    vendor: str = Field(min_length=2, max_length=200)
    url: HttpUrl | None = None


class SendCommercialCommPayload(_Payload):
    channel: Literal["email", "sms", "whatsapp"]
    audience_segment: str = Field(min_length=2, max_length=200)
    subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=10, max_length=20000)
    send_at: str | None = None


class OtherSensitivePayload(_Payload):
    description: str = Field(min_length=10, max_length=4000)
    details: dict[str, Any] = Field(default_factory=dict)


PAYLOAD_MODELS: dict[ActionType, type[_Payload]] = {
    ActionType.PUBLISH_CONTENT: PublishContentPayload,
    ActionType.CHANGE_PRICE: ChangePricePayload,
    ActionType.MODIFY_PRODUCT: ModifyProductPayload,
    ActionType.LAUNCH_AD: LaunchAdPayload,
    ActionType.SPEND_MONEY: SpendMoneyPayload,
    ActionType.SEND_COMMERCIAL_COMM: SendCommercialCommPayload,
    ActionType.OTHER_SENSITIVE: OtherSensitivePayload,
}

# Riesgo mínimo por tipo de acción (el agente puede subirlo, nunca bajarlo).
MIN_RISK: dict[ActionType, Risk] = {
    ActionType.PUBLISH_CONTENT: "medium",
    ActionType.CHANGE_PRICE: "medium",
    ActionType.MODIFY_PRODUCT: "low",
    ActionType.LAUNCH_AD: "high",
    ActionType.SPEND_MONEY: "high",
    ActionType.SEND_COMMERCIAL_COMM: "high",
    ActionType.OTHER_SENSITIVE: "medium",
}
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
LARGE_PRICE_CHANGE = Decimal("0.30")


def validate_payload(action: ActionType, payload: dict[str, Any]) -> _Payload:
    """Valida el contenido de una propuesta con su esquema estricto."""
    return PAYLOAD_MODELS[action].model_validate(payload)


def effective_risk(action: ActionType, requested: Risk, payload: _Payload) -> Risk:
    risk = max(requested, MIN_RISK[action], key=_RISK_ORDER.__getitem__)
    if isinstance(payload, ChangePricePayload) and payload.change_ratio >= LARGE_PRICE_CHANGE:
        risk = "high"
    return risk


def estimated_cost(payload: _Payload) -> Decimal:
    if isinstance(payload, LaunchAdPayload):
        return payload.total_budget_eur
    if isinstance(payload, SpendMoneyPayload):
        return payload.amount_eur
    return Decimal("0")


def submit_proposal(
    conn: psycopg.Connection,
    *,
    agent_id: str,
    action: ActionType,
    title: str,
    summary: str,
    payload: dict[str, Any],
    idempotency_key: str,
    risk: Risk = "medium",
    source_run_id: str | None = None,
) -> str:
    """Valida y registra una propuesta. Devuelve su id (idempotente)."""
    model = validate_payload(action, payload)
    final_risk = effective_risk(action, risk, model)
    row = conn.execute(
        "select public.agent_submit_proposal(%s, %s::public.action_type, %s, %s, %s, %s, %s, %s,"
        " %s) as id",
        (
            agent_id,
            action.value,
            title,
            summary,
            Jsonb(model.model_dump(mode="json")),
            final_risk,
            estimated_cost(model),
            idempotency_key,
            source_run_id,
        ),
    ).fetchone()
    return str(row["id"])
