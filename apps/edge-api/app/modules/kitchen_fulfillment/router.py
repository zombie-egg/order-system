from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    FulfillmentEndpointDependency,
    Principal,
    SessionDependency,
    require_permission,
)
from app.core.enums import PermissionCode
from app.modules.kitchen_fulfillment.schemas import (
    FulfillmentHeartbeatResponse,
    FulfillmentTicketResponse,
    TransitionTicketRequest,
)
from app.modules.kitchen_fulfillment.service import (
    heartbeat_endpoint,
    list_station_queue,
    transition_ticket,
)

router = APIRouter(prefix="/fulfillment", tags=["fulfillment"])

KitchenPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.KITCHEN_OPERATE.value))
]


@router.post(
    "/heartbeat",
    response_model=FulfillmentHeartbeatResponse,
    operation_id="heartbeat_fulfillment_endpoint",
)
async def post_heartbeat(
    session: SessionDependency,
    endpoint_principal: FulfillmentEndpointDependency,
) -> FulfillmentHeartbeatResponse:
    endpoint_id, station_id, heartbeat_at, version = await heartbeat_endpoint(
        session,
        endpoint_principal,
    )
    return FulfillmentHeartbeatResponse(
        endpoint_id=endpoint_id,
        station_id=station_id,
        heartbeat_at=heartbeat_at,
        version=version,
    )


@router.get(
    "/tickets",
    response_model=list[FulfillmentTicketResponse],
    operation_id="list_fulfillment_queue",
)
async def get_tickets(
    session: SessionDependency,
    endpoint_principal: FulfillmentEndpointDependency,
    principal: KitchenPrincipal,
) -> list[FulfillmentTicketResponse]:
    return await list_station_queue(session, endpoint_principal, principal)


@router.post(
    "/tickets/{ticket_id}/transition",
    response_model=FulfillmentTicketResponse,
    operation_id="transition_fulfillment_ticket",
)
async def post_transition(
    ticket_id: UUID,
    request: TransitionTicketRequest,
    session: SessionDependency,
    endpoint_principal: FulfillmentEndpointDependency,
    principal: KitchenPrincipal,
) -> FulfillmentTicketResponse:
    return await transition_ticket(
        session,
        endpoint_principal,
        principal,
        ticket_id=ticket_id,
        to_status=request.to_status,
        expected_version=request.expected_version,
        failure_reason_code=request.failure_reason_code,
        failure_detail=request.failure_detail,
    )
