# Development Runbook

## Script is not recognized

Commands such as `.\scripts\bootstrap.ps1` are relative to the current directory. Run `Get-Location` and `Test-Path .\scripts\bootstrap.ps1`; the second command must return `True`. If it returns `False`, open PowerShell in the repository root before retrying.

If PowerShell asks whether to change the execution policy, avoid the interactive prompt by using:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

This setting lasts only for the current PowerShell window.

## Port conflict

Default ports are 5173, 5174, 5175, and 8000. Stop the old development process before restarting. Do not silently move a public terminal to another port in production configuration.

## Virtual environment missing

Run `.\scripts\bootstrap.ps1`. If activation is blocked, call `.\.venv\Scripts\python.exe` directly.

## Dependency installation fails

Check network access to npm and PyPI, then rerun bootstrap. Do not remove lockfiles to hide a resolver problem.

## PostgreSQL unavailable

Phase 2 readiness checks ping the configured database connection. The default is an embedded SQLite file with empty metadata and no business tables, so no separately managed database service is required. PostgreSQL remains optional until later persistence work.
