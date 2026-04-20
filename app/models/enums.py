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
