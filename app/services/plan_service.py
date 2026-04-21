"""Plan enforcement for the panden module (STAP 9).

Reads the per-user subscription_plan (see migratie 0005) and translates
it to a hard limit on ``Pand`` rows. Admins bypass all limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Pand, User
from app.models.enums import PAND_LIMIT_PER_PLAN, UserRole


@dataclass(frozen=True)
class PandQuota:
    plan: str
    limit: Optional[int]  # None means unlimited
    used: int

    @property
    def remaining(self) -> Optional[int]:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        if self.limit is None:
            return False
        return self.used >= self.limit


def _effective_plan(user: User) -> str:
    plan = (user.subscription_plan or "gratis").lower()
    if plan not in PAND_LIMIT_PER_PLAN:
        # Unknown plan string → fall back to the most restrictive tier
        # so a data-glitch never accidentally grants unlimited access.
        return "gratis"
    return plan


def count_panden_for_user(db: Session, user: User) -> int:
    """Count non-deleted panden owned by the user's organisation.

    Klanten create panden under their org; panden created by org
    colleagues count against the shared quota. This matches the
    "Starter 2 users / 30 panden" wording on the pricing page.
    """
    if user.organisation_id is None:
        return 0
    stmt = (
        select(func.count(Pand.id))
        .where(Pand.organisation_id == user.organisation_id)
        .where(Pand.is_deleted.is_(False))
    )
    return int(db.execute(stmt).scalar_one())


def get_quota(db: Session, user: User) -> PandQuota:
    if user.role == UserRole.admin:
        return PandQuota(plan="admin", limit=None, used=0)
    plan = _effective_plan(user)
    limit = PAND_LIMIT_PER_PLAN[plan]
    used = count_panden_for_user(db, user)
    return PandQuota(plan=plan, limit=limit, used=used)
