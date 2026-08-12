from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    """Base contract for API input DTOs.

    Silently ignored fields are unsafe at a payment boundary: a misspelled field can
    otherwise look accepted, and unexpected card-data fields can pass validation.
    """

    model_config = ConfigDict(extra="forbid")


class ProblemDetails(BaseModel):
    """Stable, correlation-aware error response shared by every API failure path."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    correlation_id: str
    details: dict[str, Any]
