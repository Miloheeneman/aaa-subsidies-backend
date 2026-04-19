from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import Organisation, User
from app.models.enums import OrganisationType, UserRole
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MessageResponse,
    OrganisationOut,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
)
from app.services.email import send_password_reset_email, send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _role_for_org_type(org_type: OrganisationType) -> UserRole:
    if org_type is OrganisationType.installateur:
        return UserRole.installateur
    return UserRole.klant


@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest, db: DbSession) -> MessageResponse:
    email_normalized = payload.email.lower().strip()

    existing = db.execute(
        select(User).where(User.email == email_normalized)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Er bestaat al een account met dit e-mailadres",
        )

    org_type = OrganisationType(payload.organisation_type)
    role = _role_for_org_type(org_type)

    organisation = Organisation(
        name=payload.organisation_name.strip(),
        type=org_type,
    )
    db.add(organisation)
    db.flush()

    user = User(
        email=email_normalized,
        password_hash=hash_password(payload.password),
        role=role,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        phone=payload.phone.strip() if payload.phone else None,
        organisation_id=organisation.id,
        verified=False,
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Er bestaat al een account met dit e-mailadres",
        )
    db.refresh(user)

    token = create_email_verification_token(user.id)
    send_verification_email(
        to=user.email, first_name=user.first_name, token=token
    )

    return MessageResponse(message="Verificatie email verstuurd")


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession) -> LoginResponse:
    email_normalized = payload.email.lower().strip()
    user = db.execute(
        select(User).where(User.email == email_normalized)
    ).scalar_one_or_none()

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Onjuist e-mailadres of wachtwoord",
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise invalid

    if not user.verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bevestig eerst uw e-mailadres voordat u inlogt",
        )

    token = create_access_token(user.id, role=user.role.value)

    organisation: Organisation | None = None
    if user.organisation_id is not None:
        organisation = db.get(Organisation, user.organisation_id)

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        user=UserOut.model_validate(user),
        organisation=(
            OrganisationOut.model_validate(organisation)
            if organisation is not None
            else None
        ),
    )


@router.post("/verify-email/{token}", response_model=MessageResponse)
def verify_email(token: str, db: DbSession) -> MessageResponse:
    try:
        payload = decode_token(token, expected_purpose="verify_email")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    try:
        user_id = UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ongeldig verificatietoken",
        ) from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gebruiker niet gevonden",
        )

    if not user.verified:
        user.verified = True
        db.commit()

    return MessageResponse(message="Email geverifieerd")


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest, db: DbSession
) -> MessageResponse:
    email_normalized = payload.email.lower().strip()
    user = db.execute(
        select(User).where(User.email == email_normalized)
    ).scalar_one_or_none()

    if user is not None:
        token = create_password_reset_token(user.id)
        send_password_reset_email(
            to=user.email, first_name=user.first_name, token=token
        )

    # Always return the same message to avoid user enumeration.
    return MessageResponse(
        message=(
            "Als er een account bij dit e-mailadres hoort, "
            "is er een herstelmail verstuurd"
        )
    )


@router.post("/reset-password/{token}", response_model=MessageResponse)
def reset_password(
    token: str, payload: ResetPasswordRequest, db: DbSession
) -> MessageResponse:
    try:
        decoded = decode_token(token, expected_purpose="reset_password")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    try:
        user_id = UUID(decoded["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ongeldig hersteltoken",
        ) from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gebruiker niet gevonden",
        )

    user.password_hash = hash_password(payload.new_password)
    db.commit()

    return MessageResponse(message="Wachtwoord bijgewerkt")


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, db: DbSession) -> MeResponse:
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
