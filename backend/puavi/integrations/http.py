"""Cliente HTTP común: tiempos de espera, reintentos y errores sin filtrar secretos."""

from __future__ import annotations

import time
from typing import Any

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class IntegrationError(RuntimeError):
    """Fallo al hablar con un servicio externo. El mensaje nunca incluye credenciales."""

    def __init__(self, service: str, message: str, status: int | None = None):
        super().__init__(f"{service}: {message}" + (f" (HTTP {status})" if status else ""))
        self.service = service
        self.status = status


def request(
    client: httpx.Client,
    service: str,
    method: str,
    url: str,
    *,
    retries: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last = exc
        else:
            if resp.status_code not in RETRY_STATUS:
                if resp.status_code >= 400:
                    raise IntegrationError(service, _safe_body(resp), resp.status_code)
                return resp
            last = IntegrationError(service, _safe_body(resp), resp.status_code)
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                time.sleep(min(int(retry_after), 30))
                continue
        time.sleep(min(2**attempt, 10))
    if isinstance(last, IntegrationError):
        raise last
    raise IntegrationError(service, f"sin respuesta ({type(last).__name__})")


def _safe_body(resp: httpx.Response) -> str:
    text = resp.text[:500]
    # Nunca devolver cabeceras ni la URL completa (pueden contener tokens).
    return text.replace("\n", " ")


def new_client(timeout: float = 60.0, **kwargs: Any) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=False, **kwargs)
