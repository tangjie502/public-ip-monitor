from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(settings.database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ip_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                source TEXT NOT NULL,
                notification_status TEXT NOT NULL,
                notification_error TEXT
            );

            CREATE TABLE IF NOT EXISTS monitor_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


def get_state(key: str) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM monitor_state WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO monitor_state(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def set_many_state(values: dict[str, str]) -> None:
    with get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO monitor_state(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            list(values.items()),
        )


def insert_change(
    *,
    ip_address: str,
    changed_at: str,
    source: str,
    notification_status: str,
    notification_error: str | None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO ip_changes (
                ip_address,
                changed_at,
                source,
                notification_status,
                notification_error
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (ip_address, changed_at, source, notification_status, notification_error),
        )


def list_changes(limit: int = 100) -> list[sqlite3.Row]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, ip_address, changed_at, source, notification_status, notification_error
            FROM ip_changes
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows


def list_changes_page(*, page: int, page_size: int) -> list[sqlite3.Row]:
    offset = max(page - 1, 0) * page_size
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, ip_address, changed_at, source, notification_status, notification_error
            FROM ip_changes
            ORDER BY changed_at DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
    return rows


def list_all_changes() -> list[sqlite3.Row]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, ip_address, changed_at, source, notification_status, notification_error
            FROM ip_changes
            ORDER BY changed_at DESC
            """
        ).fetchall()
    return rows


def count_changes() -> int:
    with get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS total FROM ip_changes").fetchone()
    return int(row["total"]) if row else 0
