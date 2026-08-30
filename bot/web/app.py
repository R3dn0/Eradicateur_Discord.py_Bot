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

    # Auto-inject CSRF token and bot in template contexts
    orig_template_response = templates.TemplateResponse

    def template_response_with_csrf(
        request: Request,
        name: str,
        context: dict | None = None,
        status_code: int = 200,
        **kwargs,
    ):
        ctx = context.copy() if context else {}
        if "csrf_token" not in ctx:
            ctx["csrf_token"] = getattr(request.state, "csrf_token", "")
        if "bot" not in ctx:
            ctx["bot"] = bot
        if "current_user" not in ctx:
            ctx["current_user"] = getattr(request.state, "user", None)
        return orig_template_response(
            request=request,
            name=name,
            context=ctx,
            status_code=status_code,
            **kwargs,
        )

    templates.TemplateResponse = template_response_with_csrf  # type: ignore[assignment]

    app.state.bot = bot
    app.state.templates = templates

    # Security Headers Middleware
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' data: https:; "
            "worker-src 'self' blob:; "
            "connect-src 'self';"
        )
        return response

    # Custom exception handler for redirects and errors
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


