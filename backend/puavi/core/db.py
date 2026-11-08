"""Conexiones a Postgres (Supabase) por rol técnico."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from pydantic import SecretStr


@contextmanager
def connect(url: SecretStr | str) -> Iterator[psycopg.Connection]:
    """Abre una conexión transaccional. Commit al salir bien, rollback si falla."""
    dsn = url.get_secret_value() if isinstance(url, SecretStr) else url
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
