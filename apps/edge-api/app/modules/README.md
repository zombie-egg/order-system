# Backend module boundaries

These directories reserve domain boundaries only. Phase 2 contains no business services, models, repositories, or API routes.

- `identity`: staff and administrator identities and permissions.
- `organization`: tenant, legal entity, store, kiosk, and kitchen station.
- `catalog`: product and category configuration.
- `pricing_tax`: authoritative pricing and Netherlands tax policy.
- `ordering`: immutable order snapshots.
- `payments`: PSP-neutral payment lifecycle and Adyen adapter boundary.
- `kitchen_fulfillment`: paid-order tickets and staff workflow.
- `manual_review`: human resolution of unfulfillable paid orders.
- `receipts`: customer receipts and printer fallback.
- `audit`: append-only administrative and operational audit.
- `reporting`: operational read models and exports.
