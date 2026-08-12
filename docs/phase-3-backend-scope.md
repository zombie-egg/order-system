# Phase 3 Scope: Backend

## Goal

Deliver the transactional store-edge backend for a Netherlands Windows self-service ordering terminal. The backend is authoritative for identity, catalog, pricing, orders, payment state, manual kitchen fulfillment, exception review, receipts, audit, and operational reporting.

This document records the completed Backend boundary. The customer-facing, kitchen, and
administration workflows were subsequently implemented in Phase 4; see
`docs/phase-4-frontend-scope.md`.

## Included

- Versioned SQLAlchemy domain models and an initial Alembic migration.
- Tenant, legal entity, store, kiosk, kitchen station, and payment-terminal bindings.
- Staff authentication with Argon2id password hashing, signed short-lived access tokens, RBAC, account disablement, and token invalidation.
- Durable HMAC-keyed login throttling, timed lockouts, and bounded concurrent Argon2 verification without persisting attempted tenant codes, usernames, or passwords.
- Multilingual categories, products, option groups, option values, price books, availability, and versioned tax rules.
- Server-authoritative quotes using integer euro cents, deterministic rounding, expiry, immutable snapshots, and configurable VAT rates.
- Idempotent order creation from an unexpired quote with immutable item, option, price, tax, preparation, and allergen snapshots.
- PSP-neutral payment attempts and transactions, including `UNKNOWN`; a development-only mock provider; no cardholder-data fields.
- Atomic paid-order release into a kitchen ticket, receipt, audit record, and transactional outbox event.
- Kitchen station heartbeat, queue reads, optimistic-concurrency state transitions, and explicit unfulfillable reasons.
- Manual review assignment and authorized resolution, including refund, remake, substitution, manual fulfillment, or no financial action.
- Refund records, refund receipts, payment reconciliation views, append-only audit, and basic operational reporting.
- Development bootstrap commands and deterministic test fixtures.
- Fail-closed runtime configuration: only async SQLite/psycopg URLs are accepted, while staging and production require PostgreSQL, a non-development JWT secret, and the mock payment adapter disabled.
- Unit, API integration, migration, idempotency, state-machine, authorization, and transaction-boundary tests.

## Explicitly excluded

- Real Adyen, Stripe, or SumUp credentials, network calls, terminal activation, webhooks, or settlement ingestion. Only the provider contract and a development-only mock are implemented.
- Automatic drink-machine control, PLC, Serial, MQTT, Modbus, machine HTTP protocols, or drink-production simulators.
- Inventory management, customer profiles, loyalty, membership, marketing automation, and recommendations. These were not part of the approved first backend boundary.
- Cloud multi-store synchronization, OTA, Windows service installation, printer drivers, and production kiosk lockdown.
- Frontend business screens or UI styling.
- Hard-coded Netherlands VAT percentages. Tax categories, rates, validity windows, and price-inclusion policy are data.

## Core invariants

1. Money is stored and calculated as integer minor units; floating-point money is forbidden.
2. Displayed prices, VAT, discounts, payment amount, order amount, receipt amount, and refund amount must reconcile exactly.
3. A quote cannot be changed after issue and cannot be consumed after expiry.
4. Reusing an idempotency key with a different request is a conflict; retrying the same request returns the original resource.
5. A payment timeout or ambiguous response becomes `UNKNOWN`, never an assumed failure.
6. A kitchen ticket is released only after confirmed payment.
7. Confirming payment, confirming the order, creating the kitchen ticket, receipt, audit record, and outbox event is one database transaction.
8. An unfulfillable paid order creates a manual-review case and never triggers an automatic refund.
9. Refund success is recorded only after the payment provider confirms it.
10. Public kiosk APIs never expose staff credentials, internal audit data, PSP secrets, or cardholder data.

## Acceptance criteria

- An empty database upgrades to the latest Alembic revision and downgrades to base in an isolated migration test.
- SQLite development tests pass, and CI applies the complete migration to PostgreSQL 17, probes the migrated schema through the async runtime, and downgrades it to base.
- API documentation exposes explicit stable operation IDs for all routes.
- Authentication, permission denial, disabled accounts, and expired or invalid tokens are tested.
- Quote, order, payment, kitchen, review, refund, and receipt happy paths are covered through HTTP integration tests.
- Duplicate order/payment/refund requests and conflicting idempotency-key reuse are tested.
- Invalid state transitions and stale optimistic-concurrency versions are rejected.
- Payment `UNKNOWN` does not create a kitchen ticket and can be reconciled without duplicate payment.
- No source field or log payload accepts PAN, CVV, PIN, or magnetic-stripe data.
- Ruff, Mypy, Pytest, frontend regression checks, production frontend builds, PostgreSQL migration checks, and PowerShell 5.1 startup/cleanup checks pass.
