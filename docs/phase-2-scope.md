# Phase 2 Scope: Project Creation

## Goal

Create a reproducible Windows-first monorepo that starts, builds, tests, and clearly preserves the approved domain boundaries without implementing business features.

## Included

- Git repository and workspace conventions.
- Separate Kiosk, Kitchen Display, and Admin React/Vite/TypeScript/Tailwind shells.
- FastAPI technical scaffold with `/health/live`, `/health/ready`, `/version`, and OpenAPI.
- Empty SQLAlchemy/Alembic migration root with no business tables.
- Empty backend module boundaries for the approved domains.
- PowerShell bootstrap, development, and check scripts.
- Optional developer PostgreSQL container.
- Windows CI, formatting, linting, type checking, tests, and frontend builds.
- Architecture and ADR documentation.
- Reserved directories for the Edge Worker, Windows Agent, and payment simulator, with documentation only and no runtime implementation.

The repository `package-lock.json` is the reproducible npm dependency source; CI uses `npm ci`.

## Explicitly excluded

- Catalog, cart, pricing, VAT calculations, orders, payment flows, refunds, webhooks, reconciliation, authentication, RBAC, kitchen workflow, manual review, reporting, or real database models.
- Adyen, Stripe, SumUp, or complete mock payment implementations.
- Automatic drink-machine integration, drink-production hardware protocols, device gateway, machine simulator, or hardware-in-the-loop tests. Payment terminals and optional receipt printers remain separate future peripherals.
- Windows installer, service registration, Kiosk lock-down, firewall changes, or OTA.

## Acceptance criteria

- From the repository root, a clean Windows environment can run `.\scripts\bootstrap.ps1`.
- From the repository root, `.\scripts\dev.ps1` starts the API and all three web shells.
- The API health endpoints return HTTP 200.
- OpenAPI contains only the three technical routes.
- Frontend lint, typecheck, tests, and builds pass.
- Python format check, lint, Mypy, and tests pass.
- No secret, `.env`, database, log, virtual environment, or `node_modules` is tracked.
- Documentation consistently states Netherlands, Windows, Adyen-first, manual fulfillment, manual review, and no drink-machine control.
