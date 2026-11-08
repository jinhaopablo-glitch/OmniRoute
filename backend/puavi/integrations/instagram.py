"""Instagram Graph API (oficial). Requiere cuenta Business/Creator vinculada a una página.

* Lectura (agentes): token con instagram_basic + instagram_manage_insights.
* Publicación (solo ejecutor): token con instagram_content_publish.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from puavi.integrations.http import IntegrationError, new_client, request

# Versión de la Graph API configurable (Meta retira cada versión unos 2 años después).
GRAPH = "https://graph.facebook.com/" + os.environ.get("META_GRAPH_API_VERSION", "v23.0")


@dataclass
class InstagramClient:
    token: str
    ig_user_id: str
    http: httpx.Client | None = None
    poll_seconds: float = 10.0
    max_polls: int = 60

    def __post_init__(self) -> None:
        self.http = self.http or new_client()

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        return request(
            self.http,
            "Instagram",
            "GET",
            f"{GRAPH}/{path}",
            params=params,
            headers={"Authorization": f"Bearer {self.token}"},
        ).json()

    def _post(self, path: str, data: dict[str, Any]) -> dict:
        return request(
            self.http,
            "Instagram",
            "POST",
            f"{GRAPH}/{path}",
            data=data,
            headers={"Authorization": f"Bearer {self.token}"},
        ).json()

    def publish_reel(self, video_url: str, caption: str) -> dict[str, str]:
        container = self._post(
            f"{self.ig_user_id}/media",
            {"media_type": "REELS", "video_url": video_url, "caption": caption},
        )["id"]
        for _ in range(self.max_polls):
            status = self._get(container, {"fields": "status_code"}).get("status_code")
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                raise IntegrationError("Instagram", f"el vídeo no se pudo procesar ({status})")
            time.sleep(self.poll_seconds)
        else:
            raise IntegrationError("Instagram", "tiempo de procesamiento agotado")
        media_id = self._post(f"{self.ig_user_id}/media_publish", {"creation_id": container})["id"]
        link = self._get(media_id, {"fields": "permalink"}).get("permalink", "")
        return {"media_id": media_id, "url": link}

    def daily_insights(self, day: date) -> dict[str, Any]:
        since = int(time.mktime(day.timetuple()))
        data = self._get(
            f"{self.ig_user_id}/insights",
            {
                "metric": "reach,profile_views,accounts_engaged",
                "period": "day",
                "metric_type": "total_value",
                "since": since,
                "until": since + 86400,
            },
        ).get("data", [])
        out: dict[str, Any] = {}
        for m in data:
            value = m.get("total_value", {}).get("value")
            if value is None and m.get("values"):
                value = m["values"][-1].get("value")
            out[m["name"]] = value
        account = self._get(self.ig_user_id, {"fields": "followers_count,media_count"})
        out["followers"] = account.get("followers_count")
        out["media_count"] = account.get("media_count")
        return out
