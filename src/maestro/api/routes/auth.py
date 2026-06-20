from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from maestro.auth.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, verify_password
from maestro.database.session import get_db
from maestro.repositories.user import UserRepository

templates = Jinja2Templates(directory="src/maestro/ui/templates")

router = APIRouter(prefix="/ui", tags=["Auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user_repo = UserRepository(db)
    user = await user_repo.get_by_username(username)

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", {"error": "Usuário ou senha inválidos"})

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "group": user.group}, expires_delta=access_token_expires
    )

    response = RedirectResponse(url="/ui", status_code=302)
    response.set_cookie(
        key="maestro_session",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )
    return response


@router.post("/logout")
@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/ui/login", status_code=302)
    response.delete_cookie("maestro_session")
    return response
