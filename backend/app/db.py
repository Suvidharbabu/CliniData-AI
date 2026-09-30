"""Postgres (Supabase) access through the transaction pooler.

The pooler (port 6543) does not support server-side prepared statements, so
`prepare_threshold=None` is required. The pool is opened lazily so that a cold
serverless start does not pay for connections it never uses.
"""
import atexit
from contextlib import contextmanager
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_settings().database_url,
            min_size=0,
            max_size=5,
            kwargs={"prepare_threshold": None, "row_factory": dict_row, "autocommit": True},
            open=True,
            timeout=10,
        )
        atexit.register(_pool.close)
    return _pool


@contextmanager
def connection() -> Iterator[Any]:
    with _get_pool().connection() as conn:
        yield conn


def fetch_all(sql: str, params: tuple | dict | None = None) -> list[dict]:
    with connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: tuple | dict | None = None) -> dict | None:
    with connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: tuple | dict | None = None) -> None:
    with connection() as conn:
        conn.execute(sql, params)
