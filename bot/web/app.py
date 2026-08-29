from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bot.web.routes.activity_pool import router as activity_pool_router
from bot.web.routes.auth import router as auth_router
from bot.web.routes.balances import router as balances_router
from bot.web.routes.config import router as config_router
from bot.web.routes.dashboard import router as dashboard_router
from bot.web.routes.logs import router as logs_router
from bot.web.routes.payouts import router as payouts_router


def create_app(bot) -> FastAPI:
    app = FastAPI(
        title="Eradicateur Bot - Admin Dashboard",
        description="Interactive SQLite database management and Discord bot configuration",
        version="1.0.0",
        docs_url=None,  # Disabled for security by default
        redoc_url=None,
    )

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    # Helper filter for number formatting (e.g. 1 000 000)
    def format_number(val: float | None) -> str:
        if val is None:
            return "0"
        return f"{val:,}".replace(",", " ")

    def format_percent(val: float | None) -> str:
        if val is None:
            return "0 %"
        return f"{val * 100:.1f} %"

    templates.env.filters["format_number"] = format_number
    templates.env.filters["format_percent"] = format_percent

    app.state.bot = bot
    app.state.templates = templates

    # Custom exception handler for 307 redirect
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == status.HTTP_307_TEMPORARY_REDIRECT:
            location = exc.headers.get("Location", "/login") if exc.headers else "/login"
            return RedirectResponse(url=location, status_code=status.HTTP_302_FOUND)
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            if request.headers.get("HX-Request"):
                return HTMLResponse(
                    '<script>window.location.href="/login";</script>',
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"HX-Redirect": "/login"},
                )
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return templates.TemplateResponse(
            request=request,
            name="login.html" if exc.status_code == 401 else "dashboard.html",
            context={"bot": bot, "error": str(exc.detail)},
            status_code=exc.status_code,
        )

    # Include routers
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(balances_router)
    app.include_router(payouts_router)
    app.include_router(config_router)
    app.include_router(activity_pool_router)
    app.include_router(logs_router)

    return app

