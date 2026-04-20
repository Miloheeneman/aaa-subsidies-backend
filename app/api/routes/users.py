"""User-scoped endpoints.

``GET /api/v1/users/me`` returns the authenticated user's profile plus
subscription_plan / subscription_status so the frontend can render the
plan badge in the dashboard and gate UI elements by plan without a
second round-trip to ``/auth/me``.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.models import Organisation
from app.schemas.auth import MeResponse, OrganisationOut, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=MeResponse)
def get_me(user: CurrentUser, db: DbSession) -> MeResponse:
    organisation: Organisation | None = None
    if user.organisation_id is not None:
        organisation = db.get(Organisation, user.organisation_id)
    return MeResponse(
        user=UserOut.model_validate(user),
        organisation=(
            OrganisationOut.model_validate(organisation)
            if organisation is not None
            else None
        ),
    )
