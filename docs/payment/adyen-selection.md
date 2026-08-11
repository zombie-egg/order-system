# Payment Provider Selection: Adyen S1U2

## Decision

Use **Adyen + S1U2 unattended terminal + Terminal API local communication** as the target production payment integration for the Netherlands pilot.

Stripe Terminal Server-driven remains a fallback subject to written confirmation that the selected reader and installation are permitted for a permanently unattended kiosk. SumUp is not part of the first production route.

## Why Adyen

- S1U2 is designed for unattended use.
- Terminal API is platform-neutral and can be called from a Windows-local payment adapter.
- Adyen is well positioned for Netherlands acquiring and later multi-location operations.
- Cardholder data can remain within the certified terminal and PSP boundary.

## Planned topology

```text
Kiosk Web -> Edge API -> Local Payment Adapter -> Adyen S1U2 -> Adyen
```

The Kiosk never stores PSP secrets. The application stores internal payment state, Adyen `POIID`, PSP reference, and only necessary masked metadata.

## Preconditions before implementation

- Merchant onboarding and UBO/KYB approval.
- Written confirmation of S1U2 availability in the Netherlands in 2026.
- Confirmation of unattended placement, mounting, network, and insurance requirements.
- Test and live merchant accounts.
- Terminal delivery and lab access.
- Agreement on refund permissions, settlement files, and support escalation.

## Official documentation

- [Adyen terminal catalogue](https://docs.adyen.com/point-of-sale/choose-a-terminal/)
- [Adyen S1U2](https://docs.adyen.com/point-of-sale/terminals/s1u2/)
- [Adyen Terminal API](https://docs.adyen.com/point-of-sale/design-your-integration/terminal-api/)
- [Adyen onboarding](https://docs.adyen.com/get-started-with-adyen/)

The documentation links must be rechecked when Phase 3 payment work begins because hardware availability and commercial terms can change.
