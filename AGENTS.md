# Repository Guidelines

## Project Structure & Module Organization
`app/` contains the application code. `app/main.py` defines the FastAPI app, routes, and startup polling loop. `app/services.py` holds the public-IP check, SMTP delivery, CSV export, and pagination logic. `app/db.py` manages SQLite schema and queries, and `app/config.py` loads environment-driven settings. UI assets live in `app/templates/` and `app/static/`. Container files are at the repository root: `Dockerfile`, `docker-compose.yml`, and `docker-compose.nas.yml`.

## Build, Test, and Development Commands
Install dependencies locally with `pip install -r requirements.txt`.
Run the app in development with `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`.
Start the containerized stack with `docker compose up -d --build`.
Stop it with `docker compose down`.
There is no dedicated test runner configured yet, so basic verification is manual: open `/`, `/api/status`, and `/healthz`, then confirm SQLite writes under `./data/`.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, type hints on public functions, `snake_case` for functions and variables, and `PascalCase` for dataclasses like `MailSettings` and `PublicIPMonitor`. Keep modules small and responsibility-based; add new persistence code in `app/db.py`, not inline in route handlers. Match the current import style and prefer straightforward standard-library solutions before adding dependencies.

## Testing Guidelines
No automated tests are present yet. For changes to monitoring or mail flow, verify one successful IP check, one unchanged check, and one failure path. For UI changes, confirm the dashboard renders, pagination works, and CSV export downloads correctly. If you add tests, place them under `tests/` and use `test_*.py` names so the suite is easy to adopt later with `pytest`.

## Commit & Pull Request Guidelines
Git history is currently minimal (`Initial commit`), so use short imperative commit messages, for example `Add SMTP validation for SSL mode`. Keep each commit focused on one change. Pull requests should include a concise description, any environment or migration impact, and screenshots for template or CSS updates. Link related issues when applicable.

## Configuration & Data Notes
Runtime behavior is controlled through environment variables such as `DATABASE_PATH`, `CHECK_INTERVAL_SECONDS`, and SMTP settings. Do not commit real credentials. Treat `./data/public_ip_monitor.db` as local runtime state, not source.
