# Phase 5 Scope: Commercial Device UI

## Goal

Turn the Phase 4 workflows into clear, touch-safe operational interfaces for a Netherlands-first
unattended ordering terminal, manual kitchen display, and staff administration console. This phase
does not add automatic drink preparation or change Backend transaction and authorization rules.

## Customer Kiosk

- Dutch four-step ordering journey with persistent progress, large touch targets, product hierarchy,
  responsive cart, accessible option dialogs, and explicit payment safety language.
- Live kiosk heartbeat and store-status checks prevent browsing or payment while the store is paused
  or the local Edge service is unavailable.
- Checkout state, order identifiers, payment attempts, and stable idempotency keys are kept in the
  current browser session so a refresh can restore an unfinished payment without creating a second
  order. No card data is stored.
- Named Backend fulfillment/payment errors, receipt recovery, connection status, reduced-motion,
  forced-colors, and 1366x768/1920x1080 device layouts are covered.

## Kitchen Display

- High-contrast three-column board for new, preparing, and ready tickets, with priority/remake badges,
  age warnings, allergen emphasis, and large manual transition actions.
- Offline read-only mode, manual retry, focus-safe destructive failure dialog, keyboard support, and
  screen-reader announcement control.
- Heartbeat runs every four seconds because the current Backend policy permits a five-second offline
  threshold. A future contract should return a server-recommended heartbeat interval.

## Admin Console

- Branded operations shell, responsive navigation, structured cards, sticky data tables, accessible
  forms, status badges, reports, modal review flow, and consistent loading/error/empty states.
- Refund actions now match the Backend state machine: execute only `PENDING`; reconcile only
  `UNKNOWN`; `SUCCEEDED` and `FAILED` are terminal.
- Manual-review resolution reuses a stable idempotency key until a definite response or explicit
  cancellation. API requests use a 30-second timeout, `no-store`, omitted credentials, and no referrer.
- Minimum-permission report users can select their assigned store IDs without requiring
  `organization:read`; staff creation clearly remains unavailable without store names.

## Browser security boundary

- All three HTML entry points declare a restrictive development-compatible CSP, deny framing,
  disable referrers, and limit connections to loopback or HTTPS.
- API URL validation rejects embedded credentials, query strings, fragments, and non-loopback HTTP.
- Device keys and staff tokens remain JavaScript-readable `sessionStorage` values for development
  and supervised pilots only. Commercial unattended equipment still requires the Windows agent or a
  protected loopback BFF so long-lived device credentials never enter the page runtime.

## Verification

- Root Prettier, ESLint, strict TypeScript, Vitest, and all production Vite builds pass.
- Current automated total: Kiosk 18 tests, KDS 9 tests, Admin 2 tests, shared packages 3 tests
  (32 frontend tests in total).
- Local browser visual automation was attempted through the in-app browser, but the platform's
  automatic security review denied localhost access. No alternate browser or policy bypass was used;
  responsive CSS, DOM behavior, tests, and production builds form the completed automated evidence.

## Remaining release blockers

- Replace browser-held device credentials with Windows protected storage and a fixed loopback agent.
- Install the declared Backend `PyJWT` and `argon2-cffi` dependencies in the project virtual
  environment, then run the full Python suite and live four-service startup check.
- Integrate and certify a real PSP terminal/provider, webhooks, settlement reconciliation, printing,
  deployment signing, monitoring, backup/restore, and incident response before commercial rollout.
