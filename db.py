"""
PostgreSQL კავშირის ფენა (Phase 1).

გამოიყენება მხოლოდ მაშინ, როცა `config.DATA_BACKEND == "postgres"`
(იხ. sheets.py-ს dispatcher-ი). ნაგულისხმევ რეჟიმში (DATA_BACKEND
დაყენებული არაა) ეს მოდული საერთოდ არ იტვირთება და bot.py-ს ძველი,
Google Sheets-ზე მომუშავე ქცევა ბრუნდება უცვლელად.

დამოკიდებულება: psycopg2-binary (იხ. requirements.txt). ეს პაკეტი
Railway-ს build-ის დროს ავტომატურად დაინსტალირდება (`pip install -r
requirements.txt`) — ცალკე არაფრის კეთება არ სჭირდება.
"""

from __future__ import annotations

import logging
import os
import threading

import psycopg2
import psycopg2.extras
import psycopg2.pool

import config

log = logging.getLogger("safehome-crm-db")

_pool: "psycopg2.pool.ThreadedConnectionPool | None" = None
_pool_lock = threading.Lock()

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def _get_pool() -> "psycopg2.pool.ThreadedConnectionPool":
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                if not config.DATABASE_URL:
                    raise RuntimeError(
                        "DATABASE_URL ცარიელია — Postgres backend-ს სჭირდება "
                        "environment variable DATABASE_URL (Railway-ს Postgres "
                        "add-on ავტომატურად გამოგიმუშავებთ ამას)."
                    )
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1, maxconn=10, dsn=config.DATABASE_URL,
                )
    return _pool


class _ConnCtx:
    """`with get_conn() as conn:` — connection-ს ავტომატურად აბრუნებს
    pool-ში, commit/rollback-ს კეთილსინდისიერად ასრულებს."""

    def __enter__(self):
        self._pool = _get_pool()
        self._conn = self._pool.getconn()
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._pool.putconn(self._conn)
        return False


def get_conn() -> _ConnCtx:
    return _ConnCtx()


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    """SELECT, რომელიც ბრუნდება dict-ების სია (იგივე ფორმა, რასაც
    gspread-ის get_all_records() აბრუნებდა)."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> int:
    """INSERT/UPDATE/DELETE. აბრუნებს დაზარალებული (affected) სტრიქონების
    რაოდენობას."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def init_schema() -> None:
    """ქმნის ყველა ცხრილს, თუ არ არსებობს (idempotent — უსაფრთხოა
    ყოველ ჯერზე bot-ის გაშვებისას გამოძახება, ისე როგორც ensure_sheets()
    Google Sheets-ის ვერსიაში)."""
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    log.info("Postgres სქემა მზადაა (init_schema)")
