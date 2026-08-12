# Backend module boundaries

Phase 3 implements these domain boundaries as SQLAlchemy models, services, schemas, and versioned API routes. Domain services depend on core principals and persistence contracts, not FastAPI request objects.

- `identity`: staff and administrator identities and permissions.
- `organization`: tenant, legal entity, store, kiosk, and kitchen station.
- `catalog`: product and category configuration.
- `pricing_tax`: authoritative pricing and Netherlands tax policy.
- `ordering`: immutable order snapshots.
- `payments`: PSP-neutral payment/refund lifecycle, strict unknown-state handling, and provider adapter boundary; only a development Mock adapter exists.
- `kitchen_fulfillment`: paid-order tickets and staff workflow.
- `manual_review`: human resolution of unfulfillable paid orders.
- `receipts`: immutable transaction/refund receipt snapshots and integrity checks; a transaction receipt is not automatically a formal tax invoice.
- `audit`: append-only administrative and operational audit.
- `reporting`: store-scoped operational, sales, fulfillment, refund, and reconciliation read models.

Automatic drink-machine control remains permanently outside these modules.
