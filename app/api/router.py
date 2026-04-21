from fastapi import APIRouter

from app.api.routes import (
    aaa_lex,
    aanvragen,
    admin,
    auth,
    documenten,
    health,
    installateur,
    maatregelen,
    panden,
    stripe_routes,
    subscriptions,
    subsidiecheck,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(subsidiecheck.router)
api_router.include_router(aanvragen.router)
api_router.include_router(documenten.router)
api_router.include_router(panden.router)
api_router.include_router(maatregelen.panden_nested)
api_router.include_router(maatregelen.maatregelen_router)
api_router.include_router(admin.router)
api_router.include_router(aaa_lex.router)
api_router.include_router(installateur.router)
api_router.include_router(stripe_routes.router)
api_router.include_router(subscriptions.router)
