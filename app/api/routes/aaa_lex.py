from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, require_admin
from app.models import (
    AAALexProject,
    Organisation,
    RegelingConfig,
    SubsidieAanvraag,
    User,
)
from app.models.enums import AanvraagStatus, UserRole
from app.schemas.aaa_lex import (
    AAALexProjectCreate,
    AAALexProjectCreateResponse,
    AAALexProjectOut,
    MatchedSubsidie,
)
from app.services.email import send_aaa_lex_match_email
from app.services.subsidy_matching import match_subsidies

router = APIRouter(prefix="/aaa-lex", tags=["aaa-lex"])


def _fee_bedrag(
    geschatte_subsidie: Decimal | None, fee_percentage: Decimal | None
) -> Decimal | None:
    if geschatte_subsidie is None or fee_percentage is None:
        return None
    return (geschatte_subsidie * fee_percentage / Decimal("100")).quantize(
        Decimal("0.01")
    )


def _primary_contact_for_organisation(
    db, organisation_id: UUID
) -> User | None:
    return db.execute(
        select(User)
        .where(User.organisation_id == organisation_id)
        .order_by(User.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()


@router.post(
    "/project",
    response_model=AAALexProjectCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_project(
    payload: AAALexProjectCreate,
    db: DbSession,
) -> AAALexProjectCreateResponse:
    # Validate organisation_id if provided.
    organisation: Organisation | None = None
    if payload.organisation_id is not None:
        organisation = db.get(Organisation, payload.organisation_id)
        if organisation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organisatie niet gevonden",
            )

    project = AAALexProject(
        external_reference=payload.external_reference,
        organisation_id=payload.organisation_id,
        pandadres=payload.pandadres,
        postcode=payload.postcode,
        plaats=payload.plaats,
        bouwjaar=payload.bouwjaar,
        huidig_energielabel=payload.huidig_energielabel,
        nieuw_energielabel=payload.nieuw_energielabel,
        type_pand=payload.type_pand,
        oppervlakte_m2=payload.oppervlakte_m2,
        dakoppervlakte_m2=payload.dakoppervlakte_m2,
        geveloppervlakte_m2=payload.geveloppervlakte_m2,
        aanbevolen_maatregelen=(
            [m.model_dump(mode="json") for m in payload.aanbevolen_maatregelen]
            if payload.aanbevolen_maatregelen
            else None
        ),
        geschatte_investering=payload.geschatte_investering,
        geschatte_co2_besparing=payload.geschatte_co2_besparing,
        ingevoerd_door=payload.ingevoerd_door,
        notities=payload.notities,
    )
    db.add(project)
    db.flush()

    # Subsidy matching.
    maatregelen_dicts = (
        [m.model_dump(mode="python") for m in payload.aanbevolen_maatregelen]
        if payload.aanbevolen_maatregelen
        else None
    )
    aanvrager_type, matched = match_subsidies(
        type_pand=payload.type_pand,
        aanbevolen_maatregelen=maatregelen_dicts,
        geschatte_investering=payload.geschatte_investering,
    )

    # Look up live fee_percentage per regeling + filter by actief.
    configs = db.execute(
        select(RegelingConfig).where(RegelingConfig.actief.is_(True))
    ).scalars().all()
    configs_by_code = {c.code.value: c for c in configs}

    matched_active = [m for m in matched if m.code.value in configs_by_code]

    # Determine aanvrager User + organisation to attach applications to.
    aanvrager_user: User | None = None
    if organisation is not None:
        aanvrager_user = _primary_contact_for_organisation(db, organisation.id)

    created_aanvragen: list[tuple[str, SubsidieAanvraag]] = []
    matched_out: list[MatchedSubsidie] = []

    total_geschatte: Decimal = Decimal("0")

    for m in matched_active:
        cfg = configs_by_code[m.code.value]
        fee_bedrag = _fee_bedrag(m.geschatte_subsidie, cfg.fee_percentage)

        aanvraag_id: UUID | None = None
        if organisation is not None and aanvrager_user is not None:
            aanvraag = SubsidieAanvraag(
                organisation_id=organisation.id,
                aanvrager_id=aanvrager_user.id,
                regeling=m.code,
                type_aanvrager=aanvrager_type,
                status=AanvraagStatus.intake,
                maatregel=m.maatregel,
                investering_bedrag=payload.geschatte_investering,
                geschatte_subsidie=m.geschatte_subsidie,
                aaa_lex_fee_percentage=cfg.fee_percentage,
                aaa_lex_fee_bedrag=fee_bedrag,
                deadline_type=m.deadline_type,
                notes=(
                    f"Automatisch aangemaakt vanuit AAA-Lex meting "
                    f"(project {project.id}). {m.toelichting}"
                ),
            )
            db.add(aanvraag)
            db.flush()
            aanvraag_id = aanvraag.id
            created_aanvragen.append((m.code.value, aanvraag))

        if m.geschatte_subsidie is not None:
            total_geschatte += m.geschatte_subsidie

        matched_out.append(
            MatchedSubsidie(
                regeling=m.code.value,
                naam=m.naam,
                fee_percentage=cfg.fee_percentage,
                geschatte_subsidie=m.geschatte_subsidie,
                aaa_lex_fee_bedrag=fee_bedrag,
                deadline_type=m.deadline_type.value if m.deadline_type else None,
                toelichting=m.toelichting,
                aanvraag_id=aanvraag_id,
            )
        )

    # Link the first created aanvraag back onto the project for easy access.
    if created_aanvragen:
        project.aanvraag_id = created_aanvragen[0][1].id

    db.commit()
    db.refresh(project)

    # Notify client if we know who they are.
    client_notified = False
    if (
        organisation is not None
        and aanvrager_user is not None
        and matched_out
    ):
        totaal_str = (
            f"€ {total_geschatte.quantize(Decimal('0.01'))}"
            if total_geschatte > 0
            else None
        )
        send_aaa_lex_match_email(
            to=aanvrager_user.email,
            first_name=aanvrager_user.first_name,
            pandadres=project.pandadres,
            regeling_labels=[m.naam for m in matched_out],
            geschatte_totaal=totaal_str,
        )
        client_notified = True

    return AAALexProjectCreateResponse(
        project=AAALexProjectOut.model_validate(project),
        matched_subsidies=matched_out,
        total_geschatte_subsidie=(
            total_geschatte if total_geschatte > 0 else None
        ),
        client_notified=client_notified,
    )


@router.get(
    "/project/{project_id}",
    dependencies=[Depends(require_admin)],
)
def get_project(project_id: UUID, db: DbSession) -> dict:
    project = db.get(AAALexProject, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AAA-Lex project niet gevonden",
        )

    aanvragen: list[SubsidieAanvraag] = []
    if project.organisation_id is not None:
        aanvragen = (
            db.execute(
                select(SubsidieAanvraag)
                .where(
                    SubsidieAanvraag.organisation_id == project.organisation_id
                )
                .order_by(SubsidieAanvraag.created_at.asc())
            )
            .scalars()
            .all()
        )

    return {
        "project": AAALexProjectOut.model_validate(project).model_dump(mode="json"),
        "linked_aanvragen": [
            {
                "id": str(a.id),
                "regeling": a.regeling.value,
                "status": a.status.value,
                "geschatte_subsidie": (
                    str(a.geschatte_subsidie)
                    if a.geschatte_subsidie is not None
                    else None
                ),
                "toegekende_subsidie": (
                    str(a.toegekende_subsidie)
                    if a.toegekende_subsidie is not None
                    else None
                ),
                "aaa_lex_fee_percentage": (
                    str(a.aaa_lex_fee_percentage)
                    if a.aaa_lex_fee_percentage is not None
                    else None
                ),
                "deadline_type": (
                    a.deadline_type.value if a.deadline_type is not None else None
                ),
                "created_at": a.created_at.isoformat(),
            }
            for a in aanvragen
        ],
    }
