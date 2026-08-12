from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.enums import (
    MockPaymentScenario,
    PaymentProvider,
    PaymentStatus,
    RefundStatus,
)
from app.core.errors import DomainError


@dataclass(frozen=True, slots=True)
class AuthorizeCommand:
    attempt_id: UUID
    provider_service_id: str
    merchant_reference: str
    terminal_reference: str
    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    provider: PaymentProvider
    provider_event_id: str
    status: PaymentStatus
    psp_reference: str | None = None
    card_brand: str | None = None
    masked_account: str | None = None
    failure_code: str | None = None
    failure_detail_redacted: str | None = None


@dataclass(frozen=True, slots=True)
class RefundCommand:
    refund_id: UUID
    provider_service_id: str
    original_psp_reference: str
    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class RefundResult:
    provider: PaymentProvider
    provider_event_id: str
    status: RefundStatus
    psp_reference: str | None = None
    failure_code: str | None = None


class PaymentAdapter(Protocol):
    provider: PaymentProvider
    available: bool

    async def authorize(self, command: AuthorizeCommand) -> AuthorizationResult: ...

    async def query_authorization(self, command: AuthorizeCommand) -> AuthorizationResult: ...

    async def refund(self, command: RefundCommand) -> RefundResult: ...

    async def query_refund(self, command: RefundCommand) -> RefundResult: ...


class MockPaymentAdapter:
    provider = PaymentProvider.MOCK
    available = True

    def __init__(self, scenario: MockPaymentScenario = MockPaymentScenario.APPROVED) -> None:
        self.scenario = scenario

    async def authorize(self, command: AuthorizeCommand) -> AuthorizationResult:
        return self._authorization_result(command)

    async def query_authorization(self, command: AuthorizeCommand) -> AuthorizationResult:
        return self._authorization_result(command)

    async def refund(self, command: RefundCommand) -> RefundResult:
        return self._refund_result(command)

    async def query_refund(self, command: RefundCommand) -> RefundResult:
        return self._refund_result(command)

    def _authorization_result(self, command: AuthorizeCommand) -> AuthorizationResult:
        suffix = command.provider_service_id[-16:]
        if self.scenario == MockPaymentScenario.APPROVED:
            return AuthorizationResult(
                provider=self.provider,
                provider_event_id=f"mock-authorisation-{suffix}",
                status=PaymentStatus.PAID,
                psp_reference=f"MOCK-PSP-{suffix}",
                card_brand="TEST",
                masked_account="************1111",
            )
        if self.scenario == MockPaymentScenario.DECLINED:
            return AuthorizationResult(
                provider=self.provider,
                provider_event_id=f"mock-declined-{suffix}",
                status=PaymentStatus.FAILED,
                failure_code="DECLINED",
                failure_detail_redacted="The development payment scenario declined the payment",
            )
        return AuthorizationResult(
            provider=self.provider,
            provider_event_id=f"mock-unknown-{suffix}",
            status=PaymentStatus.UNKNOWN,
            failure_code="RESULT_UNKNOWN",
            failure_detail_redacted="The development payment result is ambiguous",
        )

    def _refund_result(self, command: RefundCommand) -> RefundResult:
        suffix = command.provider_service_id[-16:]
        if self.scenario == MockPaymentScenario.APPROVED:
            return RefundResult(
                provider=self.provider,
                provider_event_id=f"mock-refund-{suffix}",
                status=RefundStatus.SUCCEEDED,
                psp_reference=f"MOCK-REFUND-{suffix}",
            )
        if self.scenario == MockPaymentScenario.DECLINED:
            return RefundResult(
                provider=self.provider,
                provider_event_id=f"mock-refund-failed-{suffix}",
                status=RefundStatus.FAILED,
                failure_code="REFUND_DECLINED",
            )
        return RefundResult(
            provider=self.provider,
            provider_event_id=f"mock-refund-unknown-{suffix}",
            status=RefundStatus.UNKNOWN,
            failure_code="RESULT_UNKNOWN",
        )


class DisabledPaymentAdapter:
    """Fail closed when no commercial payment adapter has been configured."""

    provider = PaymentProvider.MOCK
    available = False

    async def authorize(self, command: AuthorizeCommand) -> AuthorizationResult:
        del command
        raise self._unavailable()

    async def query_authorization(self, command: AuthorizeCommand) -> AuthorizationResult:
        del command
        raise self._unavailable()

    async def refund(self, command: RefundCommand) -> RefundResult:
        del command
        raise self._unavailable()

    async def query_refund(self, command: RefundCommand) -> RefundResult:
        del command
        raise self._unavailable()

    @staticmethod
    def _unavailable() -> DomainError:
        return DomainError(
            "payment_adapter_unavailable",
            "No approved payment adapter is configured",
            status_code=503,
        )
