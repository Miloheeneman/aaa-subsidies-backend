import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    installateur = "installateur"
    klant = "klant"


class OrganisationType(str, enum.Enum):
    installateur = "installateur"
    klant = "klant"
    admin = "admin"


class RegelingCode(str, enum.Enum):
    ISDE = "ISDE"
    EIA = "EIA"
    MIA = "MIA"
    VAMIL = "VAMIL"
    DUMAVA = "DUMAVA"


class TypeAanvrager(str, enum.Enum):
    particulier = "particulier"
    zakelijk = "zakelijk"
    vve = "vve"
    maatschappelijk = "maatschappelijk"
    ondernemer = "ondernemer"


class AanvraagStatus(str, enum.Enum):
    intake = "intake"
    documenten = "documenten"
    review = "review"
    ingediend = "ingediend"
    goedgekeurd = "goedgekeurd"
    afgewezen = "afgewezen"


class Maatregel(str, enum.Enum):
    warmtepomp = "warmtepomp"
    isolatie = "isolatie"
    energiesysteem = "energiesysteem"
    meerdere = "meerdere"


class DeadlineType(str, enum.Enum):
    EIA_3maanden = "EIA_3maanden"
    DUMAVA_2jaar = "DUMAVA_2jaar"
    DUMAVA_3jaar = "DUMAVA_3jaar"


class DocumentType(str, enum.Enum):
    offerte = "offerte"
    factuur = "factuur"
    betalingsbewijs = "betalingsbewijs"
    foto_installatie = "foto_installatie"
    werkbon = "werkbon"
    energielabel = "energielabel"
    kvk_uittreksel = "kvk_uittreksel"
    technische_specs = "technische_specs"
    energielijst_bewijs = "energielijst_bewijs"
    milieulijst_bewijs = "milieulijst_bewijs"
    maatwerkadvies = "maatwerkadvies"
    begroting = "begroting"
    foto_voor = "foto_voor"
    foto_na = "foto_na"


class LeadStatus(str, enum.Enum):
    nieuw = "nieuw"
    contact_opgenomen = "contact_opgenomen"
    gewonnen = "gewonnen"
    verloren = "verloren"


class SubscriptionPlan(str, enum.Enum):
    """Klant-facing abonnementsplannen (zie /onboarding/plan)."""

    gratis = "gratis"
    starter = "starter"
    pro = "pro"
    enterprise = "enterprise"


# Plans that go through Stripe Checkout. ``gratis`` is set automatically
# at registration and ``enterprise`` is a mailto-CTA handled in the UI.
PAID_PLANS = frozenset({SubscriptionPlan.starter.value, SubscriptionPlan.pro.value})


# ---------------------------------------------------------------------------
# Panden module (stap 9) — enums
#
# We opzettelijk nieuwe, gescheiden enums gebruiken i.p.v. de bestaande
# ``Maatregel`` / ``DeadlineType`` / ``DocumentType`` die de legacy
# subsidie-aanvraag flow aandrijven. Zo kan de oude aanvraag-module
# ongestoord blijven draaien terwijl deze module zijn eigen lifecycle
# heeft.
# ---------------------------------------------------------------------------


class PandType(str, enum.Enum):
    woning = "woning"
    appartement = "appartement"
    kantoor = "kantoor"
    bedrijfspand = "bedrijfspand"
    zorginstelling = "zorginstelling"
    school = "school"
    sportaccommodatie = "sportaccommodatie"
    overig = "overig"


class EigenaarType(str, enum.Enum):
    eigenaar_bewoner = "eigenaar_bewoner"
    particulier_verhuurder = "particulier_verhuurder"
    zakelijk_verhuurder = "zakelijk_verhuurder"
    vve = "vve"
    overig = "overig"


class Energielabel(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class MaatregelType(str, enum.Enum):
    warmtepomp_lucht_water = "warmtepomp_lucht_water"
    warmtepomp_water_water = "warmtepomp_water_water"
    warmtepomp_hybride = "warmtepomp_hybride"
    dakisolatie = "dakisolatie"
    gevelisolatie = "gevelisolatie"
    vloerisolatie = "vloerisolatie"
    hr_glas = "hr_glas"
    zonneboiler = "zonneboiler"
    eia_investering = "eia_investering"
    mia_vamil_investering = "mia_vamil_investering"
    dumava_maatregel = "dumava_maatregel"


class MaatregelStatus(str, enum.Enum):
    orientatie = "orientatie"
    gepland = "gepland"
    uitgevoerd = "uitgevoerd"
    aangevraagd = "aangevraagd"
    goedgekeurd = "goedgekeurd"
    afgewezen = "afgewezen"


class MaatregelDeadlineType(str, enum.Enum):
    na_installatie = "na_installatie"
    voor_offerte = "voor_offerte"


class DeadlineStatus(str, enum.Enum):
    ok = "ok"
    waarschuwing = "waarschuwing"
    kritiek = "kritiek"
    verlopen = "verlopen"


class MaatregelDocumentType(str, enum.Enum):
    factuur = "factuur"
    betaalbewijs = "betaalbewijs"
    meldcode_bewijs = "meldcode_bewijs"
    foto_werkzaamheden = "foto_werkzaamheden"
    inbedrijfstelling = "inbedrijfstelling"
    offerte = "offerte"
    kvk_uittreksel = "kvk_uittreksel"
    machtiging = "machtiging"
    overig = "overig"


# Per-plan pand limieten (zie plan-enforcement middleware).
PLAN_PAND_LIMITS: dict[str, int | None] = {
    SubscriptionPlan.gratis.value: 3,
    SubscriptionPlan.starter.value: 30,
    SubscriptionPlan.pro.value: 100,
    # enterprise = onbeperkt (None)
    SubscriptionPlan.enterprise.value: None,
}
