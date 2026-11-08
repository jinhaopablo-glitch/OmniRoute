"""Configuración por proceso, leída solo de variables de entorno.

Cada proceso carga únicamente los secretos que necesita (permisos mínimos):

* ``AgentSettings``: worker de agentes. Credenciales de SOLO lectura.
* ``ExecutorSettings``: ejecutor. Único proceso con credenciales de escritura.

Los secretos son ``SecretStr``: nunca aparecen en ``repr``, logs ni excepciones.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from puavi.security.env_guard import assert_no_write_credentials


class _Base(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    environment: str = Field(default="development", alias="PUAVI_ENV")
    log_level: str = Field(default="INFO", alias="PUAVI_LOG_LEVEL")


class AgentSettings(_Base):
    """Worker de agentes (incluye al supervisor, con su propia conexión)."""

    agent_db_url: SecretStr = Field(alias="PUAVI_AGENT_DB_URL")
    supervisor_db_url: SecretStr = Field(alias="PUAVI_SUPERVISOR_DB_URL")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    shopify_store_domain: str | None = Field(default=None, alias="SHOPIFY_STORE_DOMAIN")
    shopify_read_token: SecretStr | None = Field(default=None, alias="SHOPIFY_READ_TOKEN")
    worker_id: str = Field(default="worker-1", alias="PUAVI_WORKER_ID")

    @classmethod
    def load(cls) -> AgentSettings:
        # Un worker de agentes jamás debe tener credenciales de escritura.
        assert_no_write_credentials()
        return cls()  # type: ignore[call-arg]


class ExecutorSettings(_Base):
    """Ejecutor de acciones aprobadas."""

    executor_db_url: SecretStr = Field(alias="PUAVI_EXECUTOR_DB_URL")
    dry_run: bool = Field(default=True, alias="PUAVI_EXECUTOR_DRY_RUN")
    shopify_store_domain: str | None = Field(default=None, alias="SHOPIFY_STORE_DOMAIN")
    shopify_write_token: SecretStr | None = Field(default=None, alias="SHOPIFY_WRITE_TOKEN")
    meta_access_token: SecretStr | None = Field(default=None, alias="META_ACCESS_TOKEN")
    tiktok_access_token: SecretStr | None = Field(default=None, alias="TIKTOK_ACCESS_TOKEN")
    poll_seconds: int = Field(default=30, ge=5, le=3600, alias="PUAVI_EXECUTOR_POLL_SECONDS")

    @classmethod
    def load(cls) -> ExecutorSettings:
        return cls()  # type: ignore[call-arg]
