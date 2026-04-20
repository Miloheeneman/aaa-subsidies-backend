from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Requests ----------

class RegisterRequest(BaseModel):
    # The platform is a klant portal — there is no public "ik ben een
    # installateur" branch anymore. Every registration creates a klant
    # account; admins are promoted manually via SQL. organisation_name
    # is optional because a lot of users are particulieren, not bedrijven.
    # organisation_type is still accepted (and optional) so older API
    # clients and our internal test harnesses don't break, but it is
    # ignored unless the value is "klant".
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(min_length=1, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=32)
    organisation_name: Optional[str] = Field(default=None, max_length=255)
    organisation_type: Optional[Literal["klant", "installateur"]] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


# ---------- Responses ----------

class MessageResponse(BaseModel):
    message: str


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: str
    kvk_number: Optional[str] = None
    address: Optional[str] = None
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    verified: bool
    organisation_id: Optional[UUID] = None
    subscription_plan: str = "gratis"
    subscription_status: str = "active"
    created_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    organisation: Optional[OrganisationOut] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_minutes: int
    user: UserOut
    organisation: Optional[OrganisationOut] = None
