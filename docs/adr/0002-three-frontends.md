# ADR 0002: Separate Kiosk, Kitchen Display, and Admin Applications

- Status: Accepted
- Date: 2026-08-11

## Decision

The public Kiosk, staff Kitchen Display, and privileged Admin Dashboard are separate frontend applications.

## Consequences

- Public bundles do not contain administrative routes or permissions.
- KDS can be optimized for rapid staff operation without exposing the full admin surface.
- Shared packages may contain presentation primitives and generated API types, but not final pricing or payment rules.
