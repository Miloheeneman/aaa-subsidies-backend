from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class KlantNotificatieOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    title: str
    body: Optional[str] = None
    project_id: UUID
    maatregel_id: Optional[UUID] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class KlantNotificatieListResponse(BaseModel):
    items: list[KlantNotificatieOut]
    unread_count: int
