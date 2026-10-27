from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.admin import setup_admin
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.cases.router import router as cases_router
from app.conclusions.router import router as conclusions_router
from app.core.access_tokens import build_access_tokens
from app.core.config import get_settings
from app.core.db import dispose_database, get_database
from app.core.errors import register_exception_handlers
from app.core.redis import close_redis
from app.core.templating import APP_DIR
from app.core.web import origin_check_middleware
from app.examinations.router import router as examinations_router
from app.reference.router import router as reference_router
from app.schedule.router import router as schedule_router
from app.users.router import router as users_router
from app.web.router import register_web_handlers
from app.web.router import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_redis()
    await dispose_database()


def create_app() -> FastAPI:
    settings = get_settings()
    if not settings.debug and settings.secret_key == "change-me":
        raise RuntimeError("SECRET_KEY must be set to a non-default value when DEBUG is off")
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    register_web_handlers(app)
    app.add_middleware(BaseHTTPMiddleware, dispatch=origin_check_middleware)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    for router in (
        auth_router,
        users_router,
        reference_router,
        schedule_router,
        cases_router,
        examinations_router,
        conclusions_router,
        audit_router,
        web_router,
    ):
        app.include_router(router)

    setup_admin(
        app,
        get_database().engine,
        settings.secret_key,
        build_access_tokens(settings),
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
