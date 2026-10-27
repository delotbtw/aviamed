from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.admin import setup_admin
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.cases.router import router as cases_router
from app.conclusions.router import router as conclusions_router
from app.core.config import get_settings
from app.core.templating import APP_DIR, templates
from app.examinations.router import router as examinations_router
from app.reference.router import router as reference_router
from app.schedule.router import router as schedule_router
from app.users.router import router as users_router


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name)
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
    ):
        app.include_router(router)

    setup_admin(app)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    return app


app = create_app()
