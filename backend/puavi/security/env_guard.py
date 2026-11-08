"""Comprobaciones de entorno para aplicar permisos mínimos."""

from __future__ import annotations

import os

# Variables que SOLO puede tener el proceso ejecutor.
WRITE_CREDENTIAL_VARS: tuple[str, ...] = (
    "SHOPIFY_WRITE_TOKEN",
    "META_ACCESS_TOKEN",
    "TIKTOK_ACCESS_TOKEN",
    "PUAVI_EXECUTOR_DB_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
)


class ForbiddenCredentialError(RuntimeError):
    """Un proceso tiene credenciales que no le corresponden."""


def assert_no_write_credentials(env: dict[str, str] | None = None) -> None:
    """Falla si el proceso actual tiene credenciales de escritura cargadas."""
    source = os.environ if env is None else env
    present = sorted(name for name in WRITE_CREDENTIAL_VARS if source.get(name))
    if present:
        raise ForbiddenCredentialError(
            "Este proceso de agentes no puede tener credenciales de escritura: "
            + ", ".join(present)
        )
