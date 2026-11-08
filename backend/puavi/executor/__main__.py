"""Punto de entrada del proceso ejecutor: ``python -m puavi.executor``."""

from __future__ import annotations

import logging
import signal
import time

import psycopg
from psycopg.rows import dict_row

from puavi.core.config import ExecutorSettings
from puavi.core.services import build_storage
from puavi.executor.handlers import build_registry
from puavi.executor.runner import run_pending
from puavi.integrations.brevo import BrevoClient
from puavi.integrations.instagram import InstagramClient
from puavi.integrations.meta_ads import MetaAdsClient
from puavi.integrations.shopify import ShopifyClient
from puavi.integrations.tiktok import TikTokClient

_stop = False


def _handle_stop(*_: object) -> None:
    global _stop
    _stop = True


def main() -> None:
    s = ExecutorSettings.load()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("puavi.executor")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    meta = s.meta_access_token.get_secret_value() if s.meta_access_token else None
    conn: psycopg.Connection | None = None
    log.info("Ejecutor iniciado (dry_run=%s)", s.dry_run)
    while not _stop:
        try:
            if conn is None or conn.closed:
                conn = psycopg.connect(s.executor_db_url.get_secret_value(), row_factory=dict_row)
                # Conexión aparte en autocommit para marcar contenido publicado.
                marker = psycopg.connect(s.executor_db_url.get_secret_value(), autocommit=True)
                registry = build_registry(
                    conn=marker,
                    shopify=ShopifyClient(
                        s.shopify_store_domain,
                        s.shopify_write_token.get_secret_value(),
                        s.shopify_api_version,
                    )
                    if s.shopify_store_domain and s.shopify_write_token
                    else None,
                    instagram=InstagramClient(meta, s.instagram_user_id)
                    if meta and s.instagram_user_id
                    else None,
                    tiktok=TikTokClient(s.tiktok_access_token.get_secret_value())
                    if s.tiktok_access_token
                    else None,
                    tiktok_mode=s.tiktok_mode,
                    storage=build_storage(s),
                    meta_ads=MetaAdsClient(meta, s.meta_ad_account_id)
                    if meta and s.meta_ad_account_id
                    else None,
                    brevo=BrevoClient(s.brevo_api_key.get_secret_value(), s.brevo_sender_email)
                    if s.brevo_api_key and s.brevo_sender_email
                    else None,
                )
            for proposal_id, result in run_pending(conn, registry, dry_run=s.dry_run):
                log.info("Propuesta %s -> %s", proposal_id, result)
        except psycopg.OperationalError:
            log.exception("Conexión perdida; reintentando")
            conn = None
        except Exception:  # noqa: BLE001 - el bucle no debe morir por un fallo puntual
            log.exception("Error en el ciclo del ejecutor")
        time.sleep(s.poll_seconds)


if __name__ == "__main__":
    main()
