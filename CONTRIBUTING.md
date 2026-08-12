# Contributing

- Use UTF-8 source files.
- Run `.\scripts\check.ps1` before handing off changes.
- Keep Kiosk, Kitchen Display, and Admin as separate permission boundaries.
- Phase 5 frontend workflows and device UI are complete. Commercial-readiness changes must not weaken Backend transaction, payment, authorization, CSP, HTTPS, or secret-handling boundaries.
- Preserve integer-minor-unit money, immutable quote/order/receipt snapshots, idempotency, explicit `UNKNOWN` payment state, and transaction boundaries.
- Every tenant-level operation and every store-level operation must use distinct, explicit permissions and scope checks.
- Do not add automatic drink-machine control, Serial, MQTT, Modbus, or hardware simulation.
- Treat payment terminals and optional receipt printers as isolated peripherals; never reinterpret them as authorization to add drink-production control.
- New architecture decisions require an ADR in `docs/adr`.
- Never commit secrets, logs, databases, payment payloads, or customer data.
