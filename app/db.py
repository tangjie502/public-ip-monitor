from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit

import pymysql
from pymysql.cursors import DictCursor

from .config import settings

Row = dict[str, Any]


def _is_mysql() -> bool:
    return settings.effective_database_url.startswith(("mysql://", "mysql+pymysql://"))


def _sqlite_path() -> str:
    prefix = "sqlite:///"
    if not settings.effective_database_url.startswith(prefix):
        raise RuntimeError("仅支持 sqlite:/// 或 mysql:// 数据库连接")
    return settings.effective_database_url[len(prefix) :]


def _mysql_connect() -> pymysql.connections.Connection:
    parsed = urlsplit(settings.effective_database_url)
    database = parsed.path.lstrip("/")
    if not database:
        raise RuntimeError("MySQL DATABASE_URL 缺少数据库名")
    return pymysql.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=unquote(database),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def _sqlite_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_sqlite_path(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def _connect() -> Any:
    if _is_mysql():
        return _mysql_connect()
    return _sqlite_connect()


@contextmanager
def get_connection() -> Iterator[Any]:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    if _is_mysql():
        _init_mysql_db()
        return
    path = Path(_sqlite_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    _init_sqlite_db()


def _init_sqlite_db() -> None:
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


def _init_mysql_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ip_changes (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    ip_address VARCHAR(64) NOT NULL,
                    changed_at VARCHAR(64) NOT NULL,
                    source TEXT NOT NULL,
                    notification_status VARCHAR(32) NOT NULL,
                    notification_error TEXT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_state (
                    `key` VARCHAR(191) PRIMARY KEY,
                    `value` TEXT NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )


def get_state(key: str) -> str | None:
    with get_connection() as connection:
        if _is_mysql():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT `value` FROM monitor_state WHERE `key` = %s",
                    (key,),
                )
                row = cursor.fetchone()
        else:
            row = connection.execute(
                "SELECT value FROM monitor_state WHERE key = ?",
                (key,),
            ).fetchone()
    return _row_value(row, "value")


def set_state(key: str, value: str) -> None:
    with get_connection() as connection:
        if _is_mysql():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO monitor_state(`key`, `value`)
                    VALUES(%s, %s)
                    ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
                    """,
                    (key, value),
                )
            return
        connection.execute(
            """
            INSERT INTO monitor_state(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def set_many_state(values: dict[str, str]) -> None:
    if not values:
        return
    with get_connection() as connection:
        if _is_mysql():
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO monitor_state(`key`, `value`)
                    VALUES(%s, %s)
                    ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
                    """,
                    list(values.items()),
                )
            return
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
        if _is_mysql():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ip_changes (
                        ip_address,
                        changed_at,
                        source,
                        notification_status,
                        notification_error
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (ip_address, changed_at, source, notification_status, notification_error),
                )
            return
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


def list_changes(limit: int = 100) -> list[Row]:
    query = """
        SELECT id, ip_address, changed_at, source, notification_status, notification_error
        FROM ip_changes
        ORDER BY changed_at DESC
        LIMIT {limit_placeholder}
    """
    return _fetch_all(query, (limit,))


def list_changes_page(*, page: int, page_size: int) -> list[Row]:
    offset = max(page - 1, 0) * page_size
    query = """
        SELECT id, ip_address, changed_at, source, notification_status, notification_error
        FROM ip_changes
        ORDER BY changed_at DESC
        LIMIT {limit_placeholder} OFFSET {offset_placeholder}
    """
    return _fetch_all(query, (page_size, offset))


def list_all_changes() -> list[Row]:
    query = """
        SELECT id, ip_address, changed_at, source, notification_status, notification_error
        FROM ip_changes
        ORDER BY changed_at DESC
    """
    return _fetch_all(query, ())


def count_changes() -> int:
    with get_connection() as connection:
        if _is_mysql():
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM ip_changes")
                row = cursor.fetchone()
        else:
            row = connection.execute("SELECT COUNT(*) AS total FROM ip_changes").fetchone()
    value = _row_value(row, "total")
    return int(value) if value is not None else 0


def _fetch_all(query: str, params: tuple[Any, ...]) -> list[Row]:
    with get_connection() as connection:
        if _is_mysql():
            mysql_query = query.format(limit_placeholder="%s", offset_placeholder="%s")
            with connection.cursor() as cursor:
                cursor.execute(mysql_query, params)
                rows = cursor.fetchall()
            return [dict(row) for row in rows]
        sqlite_query = query.format(limit_placeholder="?", offset_placeholder="?")
        rows = connection.execute(sqlite_query, params).fetchall()
    return [dict(row) for row in rows]


def _row_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[key]
