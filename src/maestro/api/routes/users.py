from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from maestro.auth.dependencies import get_current_user
from maestro.database.models import User
from maestro.database.session import get_db
from maestro.services.user import UserService

templates = Jinja2Templates(directory="src/maestro/ui/templates")

router = APIRouter(prefix="/ui/users", tags=["Users"])


@router.get("", response_class=HTMLResponse)
async def users_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas Administradores podem gerenciar usuários.")

    user_service = UserService(db)
    users = await user_service.get_all_users()

    return templates.TemplateResponse(
        request,
        "users.html",
        {"current_user": current_user, "users": users},
    )


@router.get("/modals/create", response_class=HTMLResponse)
async def modal_create_user(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return templates.TemplateResponse(request, "partials/user_modals.html", {"action": "create", "current_user": current_user})


@router.post("/create", response_class=HTMLResponse)
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    group: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    user_service = UserService(db)
    try:
        await user_service.create_user(username, password, group)
    except ValueError as e:
        return HTMLResponse(f"<div class='alert alert-error'>{str(e)}</div>", status_code=400)

    # Force a refresh of the users table by redirecting or triggering HTMX event
    response = HTMLResponse("<script>window.location.reload();</script>")
    return response


@router.get("/modals/edit-group/{user_id}", response_class=HTMLResponse)
async def modal_edit_group(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    user_service = UserService(db)
    user = await user_service.user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    return templates.TemplateResponse(request, "partials/user_modals.html", {"action": "edit_group", "user": user, "current_user": current_user})


@router.post("/{user_id}/group", response_class=HTMLResponse)
async def edit_user_group(
    request: Request,
    user_id: int,
    group: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    user_service = UserService(db)
    try:
        await user_service.update_user_group(user_id, group)
    except ValueError as e:
        return HTMLResponse(f"<div class='alert alert-error'>{str(e)}</div>", status_code=400)

    return HTMLResponse("<script>window.location.reload();</script>")


@router.get("/modals/reset-password/{user_id}", response_class=HTMLResponse)
async def modal_reset_password(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    user_service = UserService(db)
    user = await user_service.user_repo.get_by_id(user_id)
    return templates.TemplateResponse(request, "partials/user_modals.html", {"action": "reset_password", "user": user, "current_user": current_user})


@router.post("/{user_id}/reset-password", response_class=HTMLResponse)
async def reset_password(
    request: Request,
    user_id: int,
    password: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.group != "Administrators":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    user_service = UserService(db)
    await user_service.change_password(user_id, password)
    return HTMLResponse("<div class='alert alert-success'>Senha alterada com sucesso!</div>")


@router.get("/modals/change-password", response_class=HTMLResponse)
async def modal_change_own_password(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "partials/user_modals.html", {"action": "change_password", "current_user": current_user})


@router.post("/change-password", response_class=HTMLResponse)
async def change_own_password(
    request: Request,
    password: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_service = UserService(db)
    await user_service.change_password(current_user.id, password)
    return HTMLResponse("<div class='alert alert-success'>Sua senha foi alterada com sucesso! Faça login novamente.</div><script>setTimeout(() => window.location.href='/ui/logout', 2000);</script>")
