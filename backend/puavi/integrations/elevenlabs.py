"""ElevenLabs Text-to-Speech (oficial) para las voces en off."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from puavi.integrations.http import new_client, request

API = "https://api.elevenlabs.io/v1"


@dataclass
class ElevenLabsClient:
    api_key: str
    voice_id: str
    model_id: str = "eleven_multilingual_v2"
    http: httpx.Client | None = None

    def __post_init__(self) -> None:
        self.http = self.http or new_client(timeout=120)

    def tts(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("Texto vacío para la voz en off")
        resp = request(
            self.http,
            "ElevenLabs",
            "POST",
            f"{API}/text-to-speech/{self.voice_id}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
            json={"text": text[:5000], "model_id": self.model_id},
        )
        return resp.content
