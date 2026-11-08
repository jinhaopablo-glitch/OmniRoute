"""TikTok Content Posting API y Display API (oficiales).

* Modo por defecto ``inbox``: el vídeo se sube como BORRADOR a la bandeja de la app
  de TikTok y se termina de publicar desde el móvil. Funciona sin auditoría de la app.
* Modo ``direct``: publicación directa; requiere que TikTok haya auditado la app
  (hasta entonces solo permite vídeos privados).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from puavi.integrations.http import IntegrationError, new_client, request

API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024


@dataclass
class TikTokClient:
    token: str
    http: httpx.Client | None = None

    def __post_init__(self) -> None:
        self.http = self.http or new_client(timeout=300)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _json(self, method: str, path: str, **kwargs: Any) -> dict:
        body = request(
            self.http, "TikTok", method, f"{API}{path}", headers=self._headers(), **kwargs
        ).json()
        err = body.get("error", {})
        if err.get("code") not in (None, "ok"):
            raise IntegrationError("TikTok", f"{err.get('code')}: {err.get('message', '')}")
        return body.get("data", {})

    def upload_video(
        self,
        video: Path,
        *,
        mode: Literal["inbox", "direct"] = "inbox",
        caption: str = "",
        privacy: str = "SELF_ONLY",
    ) -> dict[str, str]:
        size = video.stat().st_size
        chunk = size if size <= CHUNK else CHUNK
        count = max(1, math.floor(size / chunk))
        source = {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk,
            "total_chunk_count": count,
        }
        if mode == "inbox":
            data = self._json(
                "POST", "/post/publish/inbox/video/init/", json={"source_info": source}
            )
        else:
            data = self._json(
                "POST",
                "/post/publish/video/init/",
                json={
                    "post_info": {"title": caption[:2200], "privacy_level": privacy},
                    "source_info": source,
                },
            )
        upload_url, publish_id = data["upload_url"], data["publish_id"]
        with video.open("rb") as fh:
            for i in range(count):
                start = i * chunk
                end = size - 1 if i == count - 1 else start + chunk - 1
                fh.seek(start)
                part = fh.read(end - start + 1)
                request(
                    self.http,
                    "TikTok",
                    "PUT",
                    upload_url,
                    content=part,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {start}-{end}/{size}",
                    },
                )
        return {"publish_id": publish_id, "mode": mode}

    def user_stats(self) -> dict[str, Any]:
        data = self._json(
            "GET",
            "/user/info/",
            params={"fields": "follower_count,likes_count,video_count"},
        )
        return data.get("user", {})
