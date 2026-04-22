"""Plan enforcement for the projecten module (STAP 9).

Reads the per-user subscription_plan (see migratie 0005) and translates
it to a hard limit on ``Project`` rows. Admins bypass all limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, User
from app.models.enums import PROJECT_LIMIT_PER_PLAN, UserRole


@dataclass(frozen=True)
class ProjectQuota:
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
    if plan not in PROJECT_LIMIT_PER_PLAN:
        # Unknown plan string → fall back to the most restrictive tier
        # so a data-glitch never accidentally grants unlimited access.
        return "gratis"
    return plan


def count_projecten_for_user(db: Session, user: User) -> int:
    """Count non-deleted projecten owned by the user's organisation.

    Klanten create projecten under their org; projecten created by org
    colleagues count against the shared quota. This matches the
    "Starter 2 users / 30 projecten" wording on the pricing page.
    """
    if user.organisation_id is None:
        return 0
    stmt = (
        select(func.count(Project.id))
        .where(Project.organisation_id == user.organisation_id)
        .where(Project.is_deleted.is_(False))
    )
    return int(db.execute(stmt).scalar_one())


def get_quota(db: Session, user: User) -> ProjectQuota:
    if user.role == UserRole.admin:
        return ProjectQuota(plan="admin", limit=None, used=0)
    plan = _effective_plan(user)
    limit = PROJECT_LIMIT_PER_PLAN[plan]
    used = count_projecten_for_user(db, user)
    return ProjectQuota(plan=plan, limit=limit, used=used)
