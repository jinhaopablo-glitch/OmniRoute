"""Fixtures de base de datos: crea una BD limpia y aplica todas las migraciones.

Requiere ``PUAVI_TEST_ADMIN_DSN`` (superusuario de un Postgres desechable), p. ej.
``postgresql://postgres:postgres@localhost:5432/postgres``. Sin ella, se omiten.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
BOOTSTRAP = ROOT / "supabase" / "tests" / "local_bootstrap.sql"

ADMIN_DSN = os.environ.get("PUAVI_TEST_ADMIN_DSN")

pytestmark = pytest.mark.db


@pytest.fixture(scope="session")
def db_dsn() -> Iterator[str]:
    if not ADMIN_DSN:
        pytest.skip("PUAVI_TEST_ADMIN_DSN no definido: tests de base de datos omitidos")
    name = f"puavi_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(ADMIN_DSN)
    params["dbname"] = name
    dsn = make_conninfo(**params)
    with psycopg.connect(dsn, autocommit=True) as conn:
        for f in [BOOTSTRAP, *MIGRATIONS]:
            conn.execute(f.read_text(encoding="utf-8"))
    yield dsn
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(
            sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name))
        )


@pytest.fixture
def admin(db_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db_dsn, autocommit=True, row_factory=dict_row) as conn:
        yield conn


def _role_conn(dsn: str, role: str, claims: dict | None = None) -> psycopg.Connection:
    conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    if claims is not None:
        conn.execute("select set_config('request.jwt.claims', %s, false)", (json.dumps(claims),))
    conn.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
    return conn


@pytest.fixture
def connect_as(db_dsn: str):
    opened: list[psycopg.Connection] = []

    def _open(role: str, claims: dict | None = None) -> psycopg.Connection:
        conn = _role_conn(db_dsn, role, claims)
        opened.append(conn)
        return conn

    yield _open
    for c in opened:
        c.close()


@pytest.fixture
def make_human(admin: psycopg.Connection, connect_as):
    """Crea un usuario en auth.users (+ perfil opcional) y devuelve su conexión."""

    def _make(role: str | None) -> tuple[str, psycopg.Connection]:
        uid = str(uuid.uuid4())
        admin.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@x.es"))
        if role is not None:
            admin.execute(
                "insert into public.profiles (user_id, display_name, role) values (%s, %s, %s)",
                (uid, f"Usuario {role}", role),
            )
        return uid, connect_as("authenticated", {"sub": uid, "role": "authenticated"})

    return _make


@pytest.fixture
def agent(connect_as) -> psycopg.Connection:
    return connect_as("puavi_agent")


@pytest.fixture
def supervisor(connect_as) -> psycopg.Connection:
    return connect_as("puavi_supervisor")


@pytest.fixture
def executor(connect_as) -> psycopg.Connection:
    return connect_as("puavi_executor")


@pytest.fixture
def anon(connect_as) -> psycopg.Connection:
    return connect_as("anon")


PRICE_PAYLOAD = {
    "product_id": "gid://shopify/Product/1",
    "variant_id": "gid://shopify/ProductVariant/1",
    "current_price": "19.90",
    "new_price": "17.90",
    "currency": "EUR",
    "reason": "Alinear con la competencia",
}


@pytest.fixture
def submit(agent: psycopg.Connection):
    """Crea una propuesta como agente y devuelve su id."""

    def _submit(payload: dict | None = None, agent_id: str = "shopify") -> str:
        row = agent.execute(
            "select public.agent_submit_proposal(%s, 'change_price', 'Bajar precio arnés',"
            " 'Propuesta de prueba', %s::jsonb, 'medium', 0, %s) as id",
            (agent_id, json.dumps(payload or PRICE_PAYLOAD), f"test-{uuid.uuid4()}"),
        ).fetchone()
        return str(row["id"])

    return _submit
