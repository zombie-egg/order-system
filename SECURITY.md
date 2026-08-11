# Security Policy

## Current phase

This repository currently contains scaffolding only. Do not place real Adyen keys, merchant accounts, certificates, customer data, card data, production databases, or diagnostic archives in the repository.

## Secret handling

- `.env` is local-only and ignored by Git.
- Production secrets will use Windows protected storage or a managed secret store.
- The Kiosk application must never contain PSP secret keys.
- PAN, CVV, PIN, track data, and full raw payment payloads must never enter application logs or databases.

## Reporting

Security issues should be reported privately to the project owner. A public disclosure process will be defined before commercial deployment.
