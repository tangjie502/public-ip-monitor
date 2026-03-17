from __future__ import annotations

import csv
import io
import asyncio
import ipaddress
import socket
import smtplib
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .config import settings
from .db import (
    count_changes,
    get_state,
    insert_change,
    list_all_changes,
    list_changes,
    list_changes_page,
    set_many_state,
    set_state,
)


@dataclass(slots=True)
class MailSettings:
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_starttls: bool
    smtp_ssl: bool
    mail_from: str
    mail_to: tuple[str, ...]
    subject_prefix: str

    @property
    def mail_enabled(self) -> bool:
        return bool(
            self.smtp_host
            and self.mail_from
            and self.mail_to
            and ((self.smtp_username and self.smtp_password) or not self.smtp_username)
        )

    def masked(self) -> dict[str, object]:
        return {
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_username": self.smtp_username,
            "smtp_password": self.smtp_password,
            "smtp_starttls": self.smtp_starttls,
            "smtp_ssl": self.smtp_ssl,
            "mail_from": self.mail_from,
            "mail_to": ", ".join(self.mail_to),
            "subject_prefix": self.subject_prefix,
            "mail_enabled": self.mail_enabled,
        }


@dataclass(slots=True)
class MonitorSnapshot:
    current_ip: str | None
    previous_ip: str | None
    last_checked_at: str | None
    last_change_at: str | None
    last_error: str | None
    mail_enabled: bool
    total_changes: int


@dataclass(slots=True)
class Pagination:
    page: int
    page_size: int
    total_items: int
    total_pages: int

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def format_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(settings.timezone).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(slots=True)
class PushSettings:
    enabled: bool
    push_url: str

    @property
    def push_enabled(self) -> bool:
        return self.enabled and bool(self.push_url.strip())

    def masked(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "push_url": self.push_url,
            "push_enabled": self.push_enabled,
        }


class PublicIPMonitor:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    def ensure_default_mail_settings(self) -> None:
        defaults = {
            "smtp_host": settings.default_smtp_host,
            "smtp_port": str(settings.default_smtp_port),
            "smtp_username": settings.default_smtp_username,
            "smtp_password": settings.default_smtp_password,
            "smtp_starttls": str(settings.default_smtp_starttls).lower(),
            "smtp_ssl": str(settings.default_smtp_ssl).lower(),
            "mail_from": settings.default_mail_from,
            "mail_to": ",".join(settings.default_mail_to),
            "subject_prefix": settings.default_subject_prefix,
        }
        values_to_seed: dict[str, str] = {}
        for key, value in defaults.items():
            existing_value = get_state(key)
            if existing_value is None:
                values_to_seed[key] = value
                continue
            if existing_value.strip():
                continue
            if value.strip():
                values_to_seed[key] = value
        if values_to_seed:
            set_many_state(values_to_seed)

    def ensure_default_push_settings(self) -> None:
        defaults = {
            "message_push_enabled": str(settings.default_message_push_enabled).lower(),
            "message_push_url": settings.default_message_push_url,
        }
        values_to_seed: dict[str, str] = {}
        for key, value in defaults.items():
            existing_value = get_state(key)
            if existing_value is None:
                values_to_seed[key] = value
                continue
            if existing_value.strip():
                continue
            if value.strip():
                values_to_seed[key] = value
        if values_to_seed:
            set_many_state(values_to_seed)

    def get_mail_settings(self) -> MailSettings:
        return MailSettings(
            smtp_host=get_state("smtp_host") or "",
            smtp_port=int(get_state("smtp_port") or settings.default_smtp_port),
            smtp_username=get_state("smtp_username") or "",
            smtp_password=get_state("smtp_password") or "",
            smtp_starttls=parse_bool(get_state("smtp_starttls"), settings.default_smtp_starttls),
            smtp_ssl=parse_bool(get_state("smtp_ssl"), settings.default_smtp_ssl),
            mail_from=get_state("mail_from") or "",
            mail_to=tuple(
                item.strip()
                for item in (get_state("mail_to") or "").split(",")
                if item.strip()
            ),
            subject_prefix=get_state("subject_prefix") or settings.default_subject_prefix,
        )

    def update_mail_settings(self, form_data: dict[str, str]) -> MailSettings:
        mail_to = ",".join(
            item.strip() for item in form_data.get("mail_to", "").split(",") if item.strip()
        )
        values = {
            "smtp_host": form_data.get("smtp_host", "").strip(),
            "smtp_port": str(int(form_data.get("smtp_port", "587").strip() or "587")),
            "smtp_username": form_data.get("smtp_username", "").strip(),
            "smtp_password": form_data.get("smtp_password", "").strip(),
            "smtp_starttls": str(parse_bool(form_data.get("smtp_starttls"))).lower(),
            "smtp_ssl": str(parse_bool(form_data.get("smtp_ssl"))).lower(),
            "mail_from": form_data.get("mail_from", "").strip(),
            "mail_to": mail_to,
            "subject_prefix": form_data.get("subject_prefix", "").strip() or settings.default_subject_prefix,
        }
        set_many_state(values)
        return self.get_mail_settings()

    def get_push_settings(self) -> PushSettings:
        return PushSettings(
            enabled=parse_bool(
                get_state("message_push_enabled"),
                settings.default_message_push_enabled,
            ),
            push_url=get_state("message_push_url") or "",
        )

    def update_push_settings(self, form_data: dict[str, str]) -> PushSettings:
        values = {
            "message_push_enabled": str(parse_bool(form_data.get("message_push_enabled"))).lower(),
            "message_push_url": form_data.get("message_push_url", "").strip(),
        }
        set_many_state(values)
        return self.get_push_settings()

    async def fetch_public_ip(self) -> tuple[str, str]:
        timeout = httpx.Timeout(settings.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            errors: list[str] = []
            for service in settings.public_ip_services:
                try:
                    response = await client.get(service)
                    response.raise_for_status()
                    ip_text = response.text.strip()
                    ipaddress.ip_address(ip_text)
                    return ip_text, service
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{service}: {exc}")
            raise RuntimeError("; ".join(errors) or "No public IP service configured")

    async def send_email(
        self,
        *,
        mail_settings: MailSettings,
        subject: str,
        body_lines: list[str],
    ) -> None:
        if not mail_settings.mail_enabled:
            raise RuntimeError("SMTP 配置未完成")
        if mail_settings.smtp_ssl and mail_settings.smtp_starttls:
            raise RuntimeError("SSL 和 STARTTLS 不能同时启用；465 通常用 SSL，587 通常用 STARTTLS")

        message = EmailMessage()
        message["From"] = mail_settings.mail_from
        message["To"] = ", ".join(mail_settings.mail_to)
        message["Subject"] = subject
        message.set_content("\n".join(body_lines))
        await asyncio.to_thread(self._deliver_email, mail_settings, message)

    def _deliver_email(self, mail_settings: MailSettings, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        try:
            if mail_settings.smtp_ssl:
                server = smtplib.SMTP_SSL(
                    mail_settings.smtp_host,
                    mail_settings.smtp_port,
                    timeout=15,
                    context=context,
                )
            else:
                server = smtplib.SMTP(
                    mail_settings.smtp_host,
                    mail_settings.smtp_port,
                    timeout=15,
                )
            with server:
                server.ehlo()
                if mail_settings.smtp_starttls and not mail_settings.smtp_ssl:
                    server.starttls(context=context)
                    server.ehlo()
                if mail_settings.smtp_username:
                    server.login(mail_settings.smtp_username, mail_settings.smtp_password)
                server.send_message(message)
        except smtplib.SMTPServerDisconnected as exc:
            raise RuntimeError(
                "SMTP 连接被服务端关闭。请检查端口与加密方式是否匹配：465 通常用 SSL，587 通常用 STARTTLS。"
            ) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise RuntimeError("SMTP 认证失败，请检查用户名、密码或授权码。") from exc
        except ssl.SSLError as exc:
            raise RuntimeError("SMTP TLS/SSL 握手失败，请检查证书和 SSL/STARTTLS 选项。") from exc
        except socket.timeout as exc:
            raise RuntimeError("连接 SMTP 服务器超时，请检查主机、端口或 NAS 网络。") from exc
        except OSError as exc:
            raise RuntimeError(f"无法连接 SMTP 服务器: {exc}") from exc

    def _build_message_push_url(
        self,
        *,
        push_url: str,
        title: str,
        subtitle: str,
        message: str,
    ) -> str:
        parsed = urlsplit(push_url.strip())
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update(
            {
                "title": title,
                "subtitle": subtitle,
                "message": message,
            }
        )
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query),
                parsed.fragment,
            )
        )

    async def send_message_push(self, *, title: str, subtitle: str, message: str) -> None:
        push_settings = self.get_push_settings()
        if not push_settings.push_enabled:
            raise RuntimeError("消息推送助手未配置")

        request_url = self._build_message_push_url(
            push_url=push_settings.push_url,
            title=title,
            subtitle=subtitle,
            message=message,
        )
        timeout = httpx.Timeout(settings.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(request_url)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("消息推送助手返回了无法解析的响应") from exc

        if payload.get("code") != 0:
            error_message = payload.get("message") or "消息推送助手返回失败"
            detail = payload.get("data")
            if isinstance(detail, dict) and detail.get("message"):
                error_message = f"{error_message}: {detail['message']}"
            raise RuntimeError(error_message)

    async def send_change_email(self, *, new_ip: str, previous_ip: str | None, changed_at: str) -> None:
        mail_settings = self.get_mail_settings()
        body_lines = [
            "你的 NAS 监控到公网 IP 已更新。",
            "",
            f"新的公网 IP：{new_ip}",
            f"之前的公网 IP：{previous_ip or '首次记录'}",
            f"更新时间：{format_timestamp(changed_at) or changed_at}",
            "",
            "如果你有远程访问、DDNS 或端口映射配置，建议确认是否正常。",
        ]
        if settings.base_url:
            body_lines.extend(
                [
                    "",
                    "管理页面：",
                    f"{settings.base_url.rstrip('/')}/",
                ]
            )
        await self.send_email(
            mail_settings=mail_settings,
            subject=f"{mail_settings.subject_prefix} 家里网络公网 IP 更新了",
            body_lines=body_lines,
        )

    async def send_change_push(
        self,
        *,
        new_ip: str,
        previous_ip: str | None,
        changed_at: str,
    ) -> None:
        subtitle = f"当前公网 IP：{new_ip}"
        message_lines = [
            f"新的公网 IP：{new_ip}",
            f"之前的公网 IP：{previous_ip or '首次记录'}",
            f"更新时间：{format_timestamp(changed_at) or changed_at}",
            "如果你有远程访问、DDNS 或端口映射配置，建议确认是否正常。",
        ]
        if settings.base_url:
            message_lines.extend(["", f"管理页面：{settings.base_url.rstrip('/')}/"])
        await self.send_message_push(
            title="家里网络公网 IP 更新了",
            subtitle=subtitle,
            message="\n".join(message_lines),
        )

    async def send_test_email(self) -> None:
        mail_settings = self.get_mail_settings()
        body_lines = [
            "这是一封来自 Public IP Monitor 的测试邮件。",
            "",
            "如果你收到了这封邮件，说明当前 SMTP 配置可正常发送。",
            f"测试时间：{format_timestamp(datetime.now(timezone.utc).isoformat())}",
        ]
        if settings.base_url:
            body_lines.extend(
                [
                    "",
                    "管理页面：",
                    f"{settings.base_url.rstrip('/')}/",
                ]
            )
        await self.send_email(
            mail_settings=mail_settings,
            subject=f"{mail_settings.subject_prefix} SMTP 测试邮件",
            body_lines=body_lines,
        )

    async def send_test_push(self) -> None:
        message_lines = [
            "这是一条来自 Public IP Monitor 的测试推送。",
            f"测试时间：{format_timestamp(datetime.now(timezone.utc).isoformat())}",
            "如果你收到了这条消息，说明消息推送助手已配置成功。",
        ]
        if settings.base_url:
            message_lines.extend(["", f"管理页面：{settings.base_url.rstrip('/')}/"])
        await self.send_message_push(
            title="Public IP Monitor 测试推送",
            subtitle="消息推送助手工作正常",
            message="\n".join(message_lines),
        )

    async def check_once(self) -> None:
        async with self._lock:
            checked_at = datetime.now(timezone.utc).isoformat()
            set_state("last_checked_at", checked_at)
            try:
                current_ip, source = await self.fetch_public_ip()
            except Exception as exc:  # noqa: BLE001
                set_state("last_error", str(exc))
                return

            previous_ip = get_state("current_ip")
            set_state("last_error", "")
            set_state("last_source", source)

            if previous_ip == current_ip:
                return

            notification_status = "skipped"
            notification_error = None

            if previous_ip is not None:
                sent_channels: list[str] = []
                channel_errors: list[str] = []

                if self.get_mail_settings().mail_enabled:
                    try:
                        await self.send_change_email(
                            new_ip=current_ip,
                            previous_ip=previous_ip,
                            changed_at=checked_at,
                        )
                        sent_channels.append("邮件")
                    except Exception as exc:  # noqa: BLE001
                        channel_errors.append(f"邮件: {exc}")

                if self.get_push_settings().push_enabled:
                    try:
                        await self.send_change_push(
                            new_ip=current_ip,
                            previous_ip=previous_ip,
                            changed_at=checked_at,
                        )
                        sent_channels.append("推送助手")
                    except Exception as exc:  # noqa: BLE001
                        channel_errors.append(f"推送助手: {exc}")

                if channel_errors:
                    notification_status = "failed"
                    notification_error = "; ".join(channel_errors)
                elif sent_channels:
                    notification_status = "sent"
                else:
                    notification_status = "skipped"
                    notification_error = "未配置任何通知渠道"

            set_state("current_ip", current_ip)
            set_state("last_change_at", checked_at)
            insert_change(
                ip_address=current_ip,
                changed_at=checked_at,
                source=source,
                notification_status=notification_status,
                notification_error=notification_error,
            )

    def get_snapshot(self) -> MonitorSnapshot:
        changes = list_changes(limit=100)
        return MonitorSnapshot(
            current_ip=get_state("current_ip"),
            previous_ip=changes[1]["ip_address"] if len(changes) > 1 else None,
            last_checked_at=format_timestamp(get_state("last_checked_at")),
            last_change_at=format_timestamp(get_state("last_change_at")),
            last_error=(get_state("last_error") or None),
            mail_enabled=self.get_mail_settings().mail_enabled,
            total_changes=count_changes(),
        )

    def get_changes(self) -> list[dict[str, str | int | None]]:
        changes: list[dict[str, str | int | None]] = []
        for row in list_changes(limit=200):
            item = dict(row)
            item["changed_at"] = format_timestamp(item["changed_at"])
            changes.append(item)
        return changes

    def get_changes_page(self, *, page: int, page_size: int) -> tuple[list[dict[str, str | int | None]], Pagination]:
        total_items = count_changes()
        total_pages = max((total_items + page_size - 1) // page_size, 1)
        safe_page = min(max(page, 1), total_pages)
        changes: list[dict[str, str | int | None]] = []
        for row in list_changes_page(page=safe_page, page_size=page_size):
            item = dict(row)
            item["changed_at"] = format_timestamp(item["changed_at"])
            changes.append(item)
        return changes, Pagination(
            page=safe_page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )

    def export_changes_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "ip_address", "changed_at", "source", "notification_status", "notification_error"])
        for row in list_all_changes():
            writer.writerow(
                [
                    row["id"],
                    row["ip_address"],
                    format_timestamp(row["changed_at"]) or row["changed_at"],
                    row["source"],
                    row["notification_status"],
                    row["notification_error"] or "",
                ]
            )
        return buffer.getvalue()

    def get_status_payload(self) -> dict[str, object]:
        payload = asdict(self.get_snapshot())
        payload["changes"] = self.get_changes()
        payload["mail_settings"] = self.get_mail_settings().masked()
        payload["push_settings"] = self.get_push_settings().masked()
        return payload
