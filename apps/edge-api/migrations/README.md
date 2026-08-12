# Database migrations

`7207959333e0_phase_3_backend_schema.py` is the Phase 3 initial business migration. It creates the complete 57-table schema and is intentionally independent from runtime `app.*` imports so an empty deployment can migrate reliably.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m alembic -c .\apps\edge-api\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c .\apps\edge-api\alembic.ini current
```

Downgrades are tested on isolated temporary databases. Do not downgrade a production store database without a reviewed backup and rollback plan.
