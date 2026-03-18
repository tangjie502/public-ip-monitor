from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


@dataclass(slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Public IP Monitor")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = _get_int("APP_PORT", 8000)
    base_url: str = os.getenv("BASE_URL", "")
    timezone_label: str = os.getenv("TIMEZONE_LABEL", "Asia/Shanghai")
    database_url: str = os.getenv("DATABASE_URL", "")
    mysql_host: str = os.getenv("MYSQL_HOST", "mysql")
    mysql_port: int = _get_int("MYSQL_PORT", 3306)
    database_path: str = os.getenv("DATABASE_PATH", "/data/public_ip_monitor.db")
    check_interval_seconds: int = _get_int("CHECK_INTERVAL_SECONDS", 300)
    request_timeout_seconds: int = _get_int("REQUEST_TIMEOUT_SECONDS", 10)
    startup_check_enabled: bool = _get_bool("STARTUP_CHECK_ENABLED", True)
    public_ip_services: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "PUBLIC_IP_SERVICES",
            "https://api.ipify.org,"
            "https://ipv4.icanhazip.com,"
            "https://ifconfig.me/ip,"
            "http://cip.cc",
        ).split(",")
        if item.strip()
    )

    default_smtp_host: str = os.getenv("SMTP_HOST", "")
    default_smtp_port: int = _get_int("SMTP_PORT", 587)
    default_smtp_username: str = os.getenv("SMTP_USERNAME", "")
    default_smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    default_smtp_starttls: bool = _get_bool("SMTP_STARTTLS", True)
    default_smtp_ssl: bool = _get_bool("SMTP_SSL", False)
    default_mail_from: str = os.getenv("MAIL_FROM", "")
    default_mail_to: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv("MAIL_TO", "").split(",") if item.strip()
    )
    default_subject_prefix: str = os.getenv("MAIL_SUBJECT_PREFIX", "[Public IP Monitor]")
    default_message_push_enabled: bool = _get_bool("MESSAGE_PUSH_ENABLED", False)
    default_message_push_user_id: str = os.getenv("MESSAGE_PUSH_USER_ID", "")
    default_message_push_user_key: str = os.getenv("MESSAGE_PUSH_USER_KEY", "")

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_label)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @property
    def effective_database_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()
        mysql_database = os.getenv("MYSQL_DATABASE", "").strip()
        mysql_user = os.getenv("MYSQL_USER", "").strip()
        mysql_password = os.getenv("MYSQL_PASSWORD", "").strip()
        if mysql_database and mysql_user:
            return (
                f"mysql://{mysql_user}:{mysql_password}"
                f"@{self.mysql_host}:{self.mysql_port}/{mysql_database}"
            )
        return f"sqlite:///{self.database_path}"


settings = Settings()
