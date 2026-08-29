from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.web.auth import clear_auth_cookie, set_auth_cookie, verify_session_token

router = APIRouter(tags=["Auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    bot = request.app.state.bot
    templates = request.app.state.templates
    session_cookie = request.cookies.get("eradicateur_session")
    if verify_session_token(session_cookie, bot.config.dashboard_token):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"bot": bot, "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    token: str = Form(...),
):
    bot = request.app.state.bot
    templates = request.app.state.templates
    expected_token = bot.config.dashboard_token

    if not expected_token or token.strip() != expected_token.strip():
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "bot": bot,
                "error": "Invalid Password / Token. Please try again.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    set_auth_cookie(response, expected_token)
    return response


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    clear_auth_cookie(response)
    return response

