from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .db import init_db
from .services import PublicIPMonitor

monitor = PublicIPMonitor()
templates = Jinja2Templates(directory="app/templates")
PAGE_SIZE = 10


async def _polling_loop() -> None:
    while True:
        await asyncio.sleep(settings.check_interval_seconds)
        await monitor.check_once()


def build_redirect(message: str, level: str = "success") -> RedirectResponse:
    return RedirectResponse(
        url=f"/?message={quote(message)}&level={quote(level)}",
        status_code=303,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    monitor.ensure_default_mail_settings()
    if settings.startup_check_enabled:
        await monitor.check_once()
    task = asyncio.create_task(_polling_loop(), name="public-ip-monitor")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    page_param = request.query_params.get("page", "1")
    try:
        page = max(int(page_param), 1)
    except ValueError:
        page = 1
    changes, pagination = monitor.get_changes_page(page=page, page_size=PAGE_SIZE)
    start_page = max(1, pagination.page - 2)
    end_page = min(pagination.total_pages, start_page + 4)
    start_page = max(1, end_page - 4)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "settings": settings,
            "snapshot": monitor.get_snapshot(),
            "changes": changes,
            "pagination": pagination,
            "page_numbers": list(range(start_page, end_page + 1)),
            "mail_settings": monitor.get_mail_settings().masked(),
            "flash_message": request.query_params.get("message"),
            "flash_level": request.query_params.get("level", "success"),
        },
    )


@app.post("/settings/mail")
async def save_mail_settings(request: Request) -> RedirectResponse:
    form = await request.form()
    try:
        monitor.update_mail_settings({key: str(value) for key, value in form.items()})
    except ValueError:
        return build_redirect("SMTP 端口必须是有效数字", "error")
    return build_redirect("邮件配置已保存")


@app.post("/settings/mail/test")
async def test_mail_settings(request: Request) -> RedirectResponse:
    form = await request.form()
    try:
        monitor.update_mail_settings({key: str(value) for key, value in form.items()})
        await monitor.send_test_email()
    except ValueError:
        return build_redirect("SMTP 端口必须是有效数字", "error")
    except Exception as exc:  # noqa: BLE001
        return build_redirect(f"测试邮件发送失败: {exc}", "error")
    return build_redirect("测试邮件已发送，请检查收件箱")


@app.get("/api/status", response_class=JSONResponse)
async def status() -> JSONResponse:
    return JSONResponse(monitor.get_status_payload())


@app.get("/export/ip-changes.csv", response_class=PlainTextResponse)
async def export_ip_changes() -> PlainTextResponse:
    csv_content = monitor.export_changes_csv()
    headers = {
        "Content-Disposition": 'attachment; filename="public-ip-changes.csv"'
    }
    return PlainTextResponse(csv_content, headers=headers, media_type="text/csv; charset=utf-8")


@app.get("/healthz", response_class=JSONResponse)
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})
