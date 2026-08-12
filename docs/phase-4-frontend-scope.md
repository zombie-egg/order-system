# Phase 4 Scope: Frontend Workflows

## Goal

Connect the Netherlands store-edge Backend to three operational React clients without adding
automatic drink-machine control: customer Kiosk, staff Kitchen Display, and Admin Console.

Phase 4 delivers complete functional workflows and safe runtime boundaries. Final brand language,
motion, visual hierarchy, and dedicated device-resolution polish were completed in Phase 5; see
`docs/phase-5-ui-scope.md`.

## Customer Kiosk

- Runtime kiosk provisioning; the device key is never compiled into the Vite bundle.
- Multilingual catalog and category browsing, required option validation, accessible cart controls,
  allergen information, and server-authoritative quote review.
- Integer-minor-unit totals, VAT and discount display, idempotent order creation, payment execution,
  `UNKNOWN`/`AUTHORIZING` reconciliation, failed-payment retry, and response-loss recovery.
- Order polling, pickup number, redacted sale/refund receipts, and explicit customer-safe errors.

## Kitchen Display

- Runtime KDS endpoint provisioning plus a short-lived staff bearer token; both Backend security
  dependencies remain required for queue access and transitions.
- Endpoint heartbeat, initial queue load, periodic refresh, manual refresh, offline recovery, and
  HTTP 401 session clearing.
- Optimistic-concurrency state transitions and a mandatory reason/detail workflow before marking a
  paid ticket `UNFULFILLABLE` and opening human review.
- Touch-oriented queue columns with preparation and allergen snapshots.

## Admin Console

- Tenant staff login, `auth/me` session restoration, permission-aware navigation, and 401 recovery.
- Operational dashboard, store policy, staff accounts, catalog/pricing setup, orders, refunds,
  manual review, reports, and audit workflows using the existing Phase 3 endpoints.
- Loading, empty, permission denial, conflict, network, and mutation feedback states.
- Money remains integer minor units at every API boundary; forms convert human-entered EUR values
  before sending them.

## Shared packages

- `@smart-drink/contracts` provides reusable Backend-shaped TypeScript contracts and minor-unit
  currency formatting.
- `@smart-drink/api-client` provides a dependency-free fetch client, RFC 7807 error handling,
  header-based device credentials, staff bearer support, and idempotency helpers.
- Existing applications may migrate to the shared client incrementally; their Phase 4 app-specific
  clients are independently contract-tested and contain no third-party runtime dependency.

## Security and deployment boundary

- `VITE_*` configuration contains only the API address. It must never contain passwords, tokens,
  device keys, merchant credentials, or PSP secrets.
- Browser `sessionStorage` is used to prevent persistent secrets in local development and supervised
  pilots. Commercial unattended Windows equipment must obtain device credentials from protected OS
  storage through the future Windows agent.
- The Edge API stays on loopback or a restricted store network. HTTPS and a locked-down Windows
  kiosk account are required when traffic leaves the local machine.
- Payment collection remains PSP-terminal work. These frontends never accept PAN, CVV/CVC, PIN,
  track data, or raw payment-provider payloads.

## Verification

- Root frontend formatting, lint, strict TypeScript, Vitest, and all three Vite production builds.
- Kiosk tests cover API headers, catalog/cart/options, quote/payment/reconciliation/retry/recovery,
  and receipt display.
- KDS tests cover authentication headers, queue connection, unfulfillable review data, URL
  validation, and 401 recovery.
- Admin tests cover login, session secrecy, and permission-scoped navigation; Phase 5 additionally
  aligned refund/review state actions and commercial UI boundaries, while deeper module interaction
  coverage remains appropriate before production release.

Live browser-to-Backend acceptance still requires the Python virtual environment to contain the
declared `PyJWT` and `argon2-cffi` dependencies. Until then, frontend tests use controlled fetch
responses and do not claim a live end-to-end payment or security run.
