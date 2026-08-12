# Development Runbook

需要直接体验 Kiosk、KDS、Admin 与 Backend 的读者应先使用 [Windows 一键演示指南](./demo.md)。本页保留工程开发和故障排查细节。

## Script is not recognized

Commands such as `.\scripts\bootstrap.ps1` are relative to the current directory. Run `Get-Location` and `Test-Path .\scripts\bootstrap.ps1`; the second command must return `True`. If it returns `False`, open PowerShell in the repository root before retrying.

If PowerShell asks whether to change the execution policy, avoid the interactive prompt by using:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

This setting lasts only for the current PowerShell window.

For a complete operable demo, prefer double-clicking `Start-Demo.cmd`. It uses a process-only
execution-policy bypass, a dedicated `var\demo\demo.db`, Backend `seed-demo` data, and then starts
the API plus Kiosk, KDS, and Admin. See [Windows 一键演示](./demo.md).

## Port conflict

Default ports are 5173, 5174, 5175, and 8000. Stop the old development process before restarting. Do not silently move a public terminal to another port in production configuration.

For an isolated development startup check, pass four unique ports explicitly. Script parameters override values in `.env`, and the matching loopback CORS origins are generated automatically:

```powershell
.\scripts\dev.ps1 -StartupCheck -ApiPort 18000 -KioskPort 15173 `
  -KitchenDisplayPort 15174 -AdminPort 15175
```

On a startup failure, inspect `var\logs\*-<run-id>.stderr.log`. The script stops every process it started; `-StartupCheck` also verifies that all four ports were released.

## Virtual environment missing

Run `.\scripts\bootstrap.ps1`. If activation is blocked, call `.\.venv\Scripts\python.exe` directly.

## Dependency installation fails

Check network access to npm and PyPI, then rerun bootstrap. Do not remove lockfiles to hide a resolver problem.

## PostgreSQL unavailable

Phase 3 defaults to an embedded SQLite database with the full business schema, so no separately managed database service is required for local development. `bootstrap.ps1` and `dev.ps1` run `alembic upgrade head` before use. PostgreSQL is optional for development but remains the production target.

Only `sqlite+aiosqlite` and `postgresql+psycopg` URLs are accepted. Staging and production reject SQLite and the mock payment adapter. Keep a PostgreSQL `connect_timeout` in unattended runtime configuration so an unavailable service fails fast.

If migration fails, run this from the repository root and inspect the first error; do not delete the database as a generic fix:

```powershell
.\.venv\Scripts\python.exe -m alembic -c .\apps\edge-api\alembic.ini current
.\.venv\Scripts\python.exe -m alembic -c .\apps\edge-api\alembic.ini upgrade head
```

The checked-in Phase 3 revision is an empty-database initial schema. Before upgrading any populated Phase 2 or pilot database, create a dedicated forward data migration, take a recoverable backup, and rehearse restore. `alembic downgrade base` is destructive and is only used against isolated test databases.

## First-store bootstrap

Run `python -m app.cli bootstrap-store` only after migrations. Omit `--owner-password` so PowerShell history cannot capture it. The command emits one-time Kiosk/KDS credentials; store them as secrets and never paste them into issue trackers or commit them.
