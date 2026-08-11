# ADR 0005: Adyen S1U2 as the First Production Terminal

- Status: Accepted with commercial preconditions
- Date: 2026-08-11

## Decision

Target Adyen S1U2 with Terminal API local communication for the Netherlands commercial pilot.

## Consequences

- The core payment domain remains provider-neutral, but only one real provider is implemented first.
- The terminal is bound to a store and kiosk using its Adyen terminal reference/POIID.
- Stripe Terminal may be added later as a fallback adapter after unattended-use confirmation.
- No PSP implementation is written in Phase 2.
