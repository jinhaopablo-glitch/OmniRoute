"""Proceso worker de agentes: ``python -m puavi.worker``."""

from __future__ import annotations

import logging
import signal
import time

import anthropic
import psycopg
from psycopg.rows import dict_row

from puavi.agents.base import Services
from puavi.core.config import AgentSettings
from puavi.core.services import build_storage
from puavi.integrations.elevenlabs import ElevenLabsClient
from puavi.integrations.instagram import InstagramClient
from puavi.integrations.shopify import ShopifyClient
from puavi.integrations.tiktok import TikTokClient
from puavi.llm.client import AgentLLM
from puavi.worker.runner import run_once

_stop = False


def _handle_stop(*_: object) -> None:
    global _stop
    _stop = True


def build_services(s: AgentSettings) -> Services:
    return Services(
        shopify=ShopifyClient(
            s.shopify_store_domain, s.shopify_read_token.get_secret_value(), s.shopify_api_version
        )
        if s.shopify_store_domain and s.shopify_read_token
        else None,
        instagram=InstagramClient(s.meta_read_token.get_secret_value(), s.instagram_user_id)
        if s.meta_read_token and s.instagram_user_id
        else None,
        tiktok=TikTokClient(s.tiktok_read_token.get_secret_value())
        if s.tiktok_read_token
        else None,
        tts=ElevenLabsClient(s.elevenlabs_api_key.get_secret_value(), s.elevenlabs_voice_id)
        if s.elevenlabs_api_key and s.elevenlabs_voice_id
        else None,
        storage=build_storage(s),
    )


def _connect(url) -> psycopg.Connection:
    return psycopg.connect(url.get_secret_value(), autocommit=True, row_factory=dict_row)


def main() -> None:
    settings = AgentSettings.load()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    log = logging.getLogger("puavi.worker")
    if not settings.anthropic_api_key:
        raise SystemExit("Falta ANTHROPIC_API_KEY")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    llm = AgentLLM(
        client=anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    )
    services = build_services(settings)
    log.info(
        "Worker %s iniciado · shopify=%s instagram=%s tiktok=%s voz=%s almacenamiento=%s",
        settings.worker_id,
        bool(services.shopify),
        bool(services.instagram),
        bool(services.tiktok),
        bool(services.tts),
        type(services.storage).__name__,
    )
    conn = sup = None
    while not _stop:
        try:
            if conn is None or conn.closed:
                conn = _connect(settings.agent_db_url)
            if sup is None or sup.closed:
                sup = _connect(settings.supervisor_db_url)
            done = run_once(
                conn=conn, sup_conn=sup, llm=llm, services=services, worker_id=settings.worker_id
            )
            if done:
                log.info("Trabajos procesados: %s", done)
                continue
        except psycopg.OperationalError:
            log.exception("Conexión a la base de datos perdida; reintentando")
            conn = sup = None
        except Exception:  # noqa: BLE001 - el bucle no debe morir
            log.exception("Error en el ciclo del worker")
        time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    main()
