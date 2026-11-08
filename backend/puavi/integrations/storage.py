"""Almacenamiento de archivos (vídeos, audio, imágenes).

* ``SupabaseStorage``: bucket privado ``media``. El proceso inicia sesión como un
  usuario técnico de Supabase Auth registrado en ``storage_service_users``; ese
  usuario no tiene perfil, así que no puede ver datos del panel ni aprobar nada.
* ``LocalStorage``: carpeta local, para desarrollo y pruebas.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from puavi.integrations.http import IntegrationError, new_client, request

_SAFE_PATH = re.compile(r"^[a-zA-Z0-9_\-/.]{1,300}$")


def check_path(path: str) -> str:
    if not _SAFE_PATH.match(path) or ".." in path or path.startswith("/"):
        raise ValueError(f"Ruta de almacenamiento no válida: {path!r}")
    return path


class Storage(Protocol):
    def upload(self, path: str, data: bytes, content_type: str) -> str: ...
    def download(self, path: str) -> bytes: ...
    def signed_url(self, path: str, expires_in: int = 3600) -> str: ...


@dataclass
class LocalStorage:
    root: Path

    def _p(self, path: str) -> Path:
        return self.root / check_path(path)

    def upload(self, path: str, data: bytes, content_type: str) -> str:
        target = self._p(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return path

    def download(self, path: str) -> bytes:
        return self._p(path).read_bytes()

    def signed_url(self, path: str, expires_in: int = 3600) -> str:
        return self._p(path).resolve().as_uri()


@dataclass
class SupabaseStorage:
    url: str
    anon_key: str
    email: str
    password: str
    bucket: str = "media"
    http: httpx.Client | None = None
    _token: str | None = field(default=None, repr=False)
    _expires_at: float = 0.0

    def __post_init__(self) -> None:
        self.url = self.url.rstrip("/")
        self.http = self.http or new_client(timeout=300)

    def _auth(self) -> dict[str, str]:
        if not self._token or time.time() > self._expires_at - 60:
            body = request(
                self.http,
                "Supabase Auth",
                "POST",
                f"{self.url}/auth/v1/token",
                params={"grant_type": "password"},
                headers={"apikey": self.anon_key},
                json={"email": self.email, "password": self.password},
            ).json()
            self._token = body["access_token"]
            self._expires_at = time.time() + int(body.get("expires_in", 3600))
        return {"apikey": self.anon_key, "Authorization": f"Bearer {self._token}"}

    def upload(self, path: str, data: bytes, content_type: str) -> str:
        request(
            self.http,
            "Supabase Storage",
            "POST",
            f"{self.url}/storage/v1/object/{self.bucket}/{check_path(path)}",
            content=data,
            headers={**self._auth(), "Content-Type": content_type, "x-upsert": "false"},
        )
        return path

    def download(self, path: str) -> bytes:
        return request(
            self.http,
            "Supabase Storage",
            "GET",
            f"{self.url}/storage/v1/object/authenticated/{self.bucket}/{check_path(path)}",
            headers=self._auth(),
        ).content

    def signed_url(self, path: str, expires_in: int = 3600) -> str:
        body = request(
            self.http,
            "Supabase Storage",
            "POST",
            f"{self.url}/storage/v1/object/sign/{self.bucket}/{check_path(path)}",
            headers=self._auth(),
            json={"expiresIn": int(expires_in)},
        ).json()
        signed = body.get("signedURL") or body.get("signedUrl")
        if not signed:
            raise IntegrationError("Supabase Storage", "no se obtuvo URL firmada")
        return f"{self.url}/storage/v1{signed}" if signed.startswith("/") else signed
