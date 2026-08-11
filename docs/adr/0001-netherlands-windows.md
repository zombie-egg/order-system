# ADR 0001: Netherlands and Windows First

- Status: Accepted
- Date: 2026-08-11

## Decision

The first market is the Netherlands and the commercial edge platform is Windows-first. Defaults are `NL`, `EUR`, `nl-NL`, and `Europe/Amsterdam`.

## Consequences

- Windows-native setup and CI are mandatory.
- Commercial operation cannot depend on Docker Desktop.
- VAT rates are versioned configuration and are not hard-coded in the scaffold.
- Netherlands receipt, accounting retention, and refund requirements require accountant and official-source validation before pilot.
