"""Meta Marketing API (oficial): crea campañas SIEMPRE en pausa.

Aunque la propuesta esté aprobada, la campaña se crea pausada para que puedas
revisar la vista previa en el Administrador de anuncios y activarla tú.
El gasto real nunca empieza sin una acción humana en Meta.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

from puavi.integrations.http import new_client, request

GRAPH = "https://graph.facebook.com/v21.0"


@dataclass
class MetaAdsClient:
    token: str
    ad_account_id: str  # sin el prefijo act_
    http: httpx.Client | None = None

    def __post_init__(self) -> None:
        self.http = self.http or new_client()

    def _post(self, path: str, data: dict) -> dict:
        return request(
            self.http,
            "Meta Ads",
            "POST",
            f"{GRAPH}/{path}",
            data=data,
            headers={"Authorization": f"Bearer {self.token}"},
        ).json()

    def create_paused_campaign(
        self,
        *,
        name: str,
        daily_budget_eur: Decimal,
        start_date: str,
        end_date: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        campaign = self._post(
            f"act_{self.ad_account_id}/campaigns",
            {
                "name": f"{name} [PUAVI {idempotency_key[:8]}]",
                "objective": "OUTCOME_TRAFFIC",
                "status": "PAUSED",
                "special_ad_categories": "[]",
            },
        )["id"]
        adset = self._post(
            f"act_{self.ad_account_id}/adsets",
            {
                "name": f"{name} · España",
                "campaign_id": campaign,
                "daily_budget": str(int(daily_budget_eur * 100)),
                "billing_event": "IMPRESSIONS",
                "optimization_goal": "LINK_CLICKS",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "targeting": '{"geo_locations":{"countries":["ES"]},"age_min":18}',
                "start_time": start_date,
                "end_time": end_date,
                "status": "PAUSED",
            },
        )["id"]
        return {"campaign_id": campaign, "adset_id": adset, "status": "PAUSED"}
