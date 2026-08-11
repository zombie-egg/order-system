# ADR 0006: SQLite for Development, PostgreSQL for Production

- Status: Accepted
- Date: 2026-08-11

## Decision

SQLite is available for fast local development and tests. The commercial production target is PostgreSQL running as a managed local Windows service, with PostgreSQL also used by future cloud components.

## Consequences

- CI must exercise PostgreSQL before business persistence is considered production-ready.
- SQLAlchemy and Alembic migrations must avoid SQLite-only behavior.
- Installation, backup, recovery, and PostgreSQL service upgrades become part of the Windows deployment work.
