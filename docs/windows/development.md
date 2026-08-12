# Windows Development

## Supported baseline

- Windows 10 or Windows 11
- PowerShell 5.1 or newer
- Node.js 24 / npm 11
- Python 3.12 (recommended; Python 3.13 is also supported for development)
- Docker Desktop optional

## Path and encoding rules

- Source is UTF-8.
- PowerShell scripts use Windows line endings.
- Do not depend on WSL, Bash, Make, symbolic links, or case-sensitive filenames.
- Use `pathlib` in Python and platform APIs in TypeScript rather than concatenating path strings.
- Runtime data must be stored on a local disk, not SMB, OneDrive, or another synchronized folder.

## Native development

Open PowerShell in the repository root (the directory containing `README.md` and `scripts`). Confirm the location with `Test-Path .\scripts\bootstrap.ps1`; it must return `True`.

Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\bootstrap.ps1
.\scripts\dev.ps1
```

The API and web applications run natively. Docker is only needed when a developer chooses the PostgreSQL profile.

The bootstrap and development scripts apply the current Alembic migration before starting the API. Runtime SQLite files use foreign keys, a 30-second busy timeout, WAL mode, and `synchronous=NORMAL`; keep them on a local NTFS disk.

`dev.ps1` reads `API_PORT`, `KIOSK_PORT`, `KITCHEN_DISPLAY_PORT`, and `ADMIN_PORT` from the process environment or root `.env`. Explicit script parameters take precedence, for example:

```powershell
.\scripts\dev.ps1 -StartupCheck -ApiPort 18000 -KioskPort 15173 `
  -KitchenDisplayPort 15174 -AdminPort 15175
```

The script rejects duplicate or occupied ports, adds the effective frontend loopback origins to the API CORS configuration, applies migrations, and restores its temporary process-environment overrides during cleanup.

The execution-policy change applies only to the current PowerShell process and reverts when that window closes. Do not use a permanent `Unrestricted` policy for this project.

## Current production boundary

The Phase 3 Backend is a development-ready transaction service, not yet a Windows production installation. Edge API/Worker/Windows Agent service registration, service accounts, firewall rules, BitLocker policy, signed updates, backup/restore drills, credential rotation, real PSP certification, and kiosk lockdown remain later deployment work. The public terminal will use Microsoft Edge Kiosk mode or a minimal WebView2 host.
