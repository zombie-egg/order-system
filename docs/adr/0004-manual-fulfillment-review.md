# ADR 0004: Manual Fulfillment and Human Review

- Status: Accepted
- Date: 2026-08-11

## Decision

Paid orders are fulfilled by staff through a Kitchen Display workflow. The platform does not control drink-making equipment.

An unfulfillable paid order opens a Manual Review Case. The system does not automatically refund it.

## Consequences

- No device gateway, machine protocol, hardware simulator, or machine command ledger is created.
- Every staff state change records actor and time.
- Refund, partial refund, remake, substitution, and no-financial-action are explicit audited resolutions.
