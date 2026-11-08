"""Punto de entrada del proceso ejecutor: ``python -m puavi.executor``."""

from __future__ import annotations

import logging
import signal
import time

from puavi.core.config import ExecutorSettings
from puavi.core.db import connect
from puavi.executor.registry import HandlerRegistry
from puavi.executor.runner import run_pending

_stop = False


def _handle_stop(*_: object) -> None:
    global _stop
    _stop = True


def build_registry() -> HandlerRegistry:
    # Las integraciones se registran en sus fases (F3 Shopify, F5 redes, F6 anuncios).
    return HandlerRegistry()


def main() -> None:
    settings = ExecutorSettings.load()
    logging.basicConfig(level=settings.log_level)
    log = logging.getLogger("puavi.executor")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    registry = build_registry()
    log.info("Ejecutor iniciado (dry_run=%s)", settings.dry_run)
    while not _stop:
        try:
            with connect(settings.executor_db_url) as conn:
                for proposal_id, result in run_pending(conn, registry, dry_run=settings.dry_run):
                    log.info("Propuesta %s -> %s", proposal_id, result)
        except Exception:  # noqa: BLE001 - el bucle no debe morir por un fallo puntual
            log.exception("Error en el ciclo del ejecutor")
        time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    main()
