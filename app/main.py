import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    cors_kwargs = {
        "allow_origins": settings.BACKEND_CORS_ORIGINS,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    if settings.BACKEND_CORS_ORIGIN_REGEX:
        cors_kwargs["allow_origin_regex"] = settings.BACKEND_CORS_ORIGIN_REGEX
    logger.info(
        "CORS configured: origins=%s regex=%s",
        settings.BACKEND_CORS_ORIGINS,
        settings.BACKEND_CORS_ORIGIN_REGEX or "(none)",
    )
    app.add_middleware(CORSMiddleware, **cors_kwargs)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/")
    def root():
        return {
            "service": settings.APP_NAME,
            "status": "running",
            "docs": "/docs",
        }

    return app


app = create_app()
