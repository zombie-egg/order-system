# ADR 0003: Modular Monolith at the Edge

- Status: Accepted
- Date: 2026-08-11

## Decision

Use one FastAPI deployment with explicit domain modules for the initial edge platform.

## Consequences

- Order, payment, Kitchen Ticket, and audit transactions stay easier to reason about.
- Module boundaries and adapters are enforced without early distributed-system overhead.
- Telemetry, reporting, and cloud synchronization can be extracted later if scale justifies it.
