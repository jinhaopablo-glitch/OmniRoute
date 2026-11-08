"""Brevo (oficial) para emails comerciales a listas con consentimiento."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from puavi.integrations.http import new_client, request

API = "https://api.brevo.com/v3"


@dataclass
class BrevoClient:
    api_key: str
    sender_email: str
    sender_name: str = "PUAVI"
    http: httpx.Client | None = None

    def __post_init__(self) -> None:
        self.http = self.http or new_client()

    def send_campaign(self, *, name: str, subject: str, html: str, list_id: int) -> dict:
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        created = request(
            self.http,
            "Brevo",
            "POST",
            f"{API}/emailCampaigns",
            headers=headers,
            json={
                "name": name,
                "subject": subject,
                "sender": {"name": self.sender_name, "email": self.sender_email},
                "htmlContent": html,
                "recipients": {"listIds": [list_id]},
            },
        ).json()
        request(
            self.http,
            "Brevo",
            "POST",
            f"{API}/emailCampaigns/{created['id']}/sendNow",
            headers=headers,
        )
        return {"campaign_id": created["id"]}
