# Security Policy

## Current phase

The Phase 3 Edge API implements staff identity, store-scoped authorization, kiosk/KDS
device credentials, orders, payment state, refunds, receipts, audit records, and reporting.
The payment integration is still development-only: no real Adyen, Stripe, or SumUp
credentials, terminal activation, webhooks, or settlement feeds are included.

Do not place merchant credentials, certificates, personal data, cardholder data,
production databases, database backups, or diagnostic archives in this repository.

## Secret handling

- `.env` is local-only and ignored by Git.
- Bootstrap prints each Kiosk/KDS credential once; the database stores only its hash.
- Staff passwords are stored with Argon2id. Access tokens are short-lived and are
  invalidated when the account or tenant is disabled or `token_version` changes.
- Login failures are tracked in a durable HMAC-keyed throttle table without storing raw
  tenant codes or usernames. Repeated failures cause a timed database-backed lockout,
  while a per-process semaphore bounds concurrent Argon2 work to protect Edge memory.
- Production secrets must use Windows protected storage or a managed secret store and
  must be rotatable without rebuilding frontend assets.
- Kiosk and KDS frontends must never contain PSP secret keys or staff credentials.
- Phase 4 browser clients accept bootstrap device credentials through an explicit runtime
  provisioning screen and keep them in `sessionStorage` only. This is suitable for local
  integration and supervised pilot work, but commercial Windows kiosks must inject device
  credentials from Windows protected storage through the future Windows agent; browser storage
  is not the final unattended-device secret store.
- Phase 5 browser entry points deny framing, suppress referrers, apply a restrictive CSP, reject URL
  credentials/query/fragment components, and require HTTPS whenever an API address is not loopback.
  These controls reduce exposure but do not turn JavaScript-readable device keys into a production
  secret boundary.
- Staff access tokens are kept in `sessionStorage`, cleared on HTTP 401 or sign-out, and never
  persisted with passwords. Do not use `localStorage` for staff tokens or device keys.
- PAN, CVV/CVC, PIN, magnetic-stripe tracks, and full raw payment payloads must never
  enter API requests, application logs, audit/outbox payloads, or databases.
- Uvicorn access logs are disabled by the supplied launchers because untrusted URL paths
  can contain sensitive values. Application error logs retain correlation ID, route,
  method, and exception type without serializing request bodies or exception messages.
- The mock payment adapter must remain disabled in staging and production.

## Operational boundary

- Keep the Edge API bound to loopback or a restricted store network; do not expose it
  directly to the public internet.
- Use PostgreSQL for staging and production. SQLite is for local single-machine
  development and testing only.
- Apply Alembic migrations before starting a new backend version and keep recoverable,
  encrypted backups for production data.
- The initial migration creates the Phase 3 schema from an empty database. A populated
  Phase 2 deployment must use a reviewed forward migration and backup/restore rehearsal;
  never apply a destructive downgrade or rebuild as an upgrade shortcut.
- Real payment-provider work requires provider certification, scoped credentials,
  webhook authentication, reconciliation, and an incident-response runbook.

## Reporting

Report suspected vulnerabilities or credential exposure privately to the project owner.
Do not include live secrets, cardholder data, or production database extracts in a report.
A coordinated disclosure and incident-response process must be established before a
commercial deployment.
