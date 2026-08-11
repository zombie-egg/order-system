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

The execution-policy change applies only to the current PowerShell process and reverts when that window closes. Do not use a permanent `Unrestricted` policy for this project.

## Future production work

The Edge API, Worker, and Windows Agent will become Windows Services. The public terminal will use Microsoft Edge Kiosk mode or a minimal WebView2 host. Production packaging, service accounts, firewall rules, disk encryption, and signed updates are outside Phase 2.
