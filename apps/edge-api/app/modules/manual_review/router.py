from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from app.api.dependencies import Principal, SessionDependency, require_permission
from app.core.enums import PermissionCode
from app.modules.manual_review.schemas import (
    AssignReviewRequest,
    ManualReviewResponse,
    ResolveReviewRequest,
)
from app.modules.manual_review.service import assign_review, list_reviews, resolve_review

router = APIRouter(prefix="/admin/reviews", tags=["admin-reviews"])

ReviewReadPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.REVIEW_READ.value))
]
ReviewResolvePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.REVIEW_RESOLVE.value))
]


@router.get("", response_model=list[ManualReviewResponse], operation_id="list_manual_reviews")
async def get_reviews(
    session: SessionDependency,
    principal: ReviewReadPrincipal,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ManualReviewResponse]:
    return await list_reviews(session, principal, limit=limit)


@router.post(
    "/{case_id}/assign",
    response_model=ManualReviewResponse,
    operation_id="assign_manual_review",
)
async def post_assign(
    case_id: UUID,
    request: AssignReviewRequest,
    session: SessionDependency,
    principal: ReviewResolvePrincipal,
) -> ManualReviewResponse:
    return await assign_review(
        session,
        principal,
        case_id=case_id,
        assignee_user_id=request.assignee_user_id,
        expected_version=request.expected_version,
    )


@router.post(
    "/{case_id}/resolve",
    response_model=ManualReviewResponse,
    operation_id="resolve_manual_review",
)
async def post_resolve(
    case_id: UUID,
    request: ResolveReviewRequest,
    session: SessionDependency,
    principal: ReviewResolvePrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ManualReviewResponse:
    return await resolve_review(
        session,
        principal,
        case_id=case_id,
        request=request,
        idempotency_key=idempotency_key,
    )
