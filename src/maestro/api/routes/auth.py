from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from maestro.auth.dependencies import can_admin, get_current_user
from maestro.database.models import User
from maestro.repositories.auth import GroupRepository, UserRepository
from maestro.services.auth import AuthService

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["Auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    """Render the login page."""
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    auth_service: AuthService = Depends(),
):
    """Authenticate user and set session cookie."""
    user = await auth_service.authenticate(username, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Usuario ou senha invalidos."},
            status_code=401,
        )

    token = auth_service.create_session_token(user)
    response = RedirectResponse(url="/ui/", status_code=302)
    response.set_cookie(
        key="maestro_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """Clear the session cookie and redirect to login."""
    response = RedirectResponse(url="/ui/login", status_code=302)
    response.delete_cookie(key="maestro_session")
    return response


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    current_user: User = Depends(can_admin),
    group_repo: GroupRepository = Depends(),
):
    """User management page (admin only)."""
    groups = await group_repo.get_all_groups()
    return templates.TemplateResponse(
        request,
        "users.html",
        {"current_user": current_user, "groups": groups},
    )


@router.get("/users/partials/list", response_class=HTMLResponse)
async def users_partial_list(
    request: Request,
    current_user: User = Depends(can_admin),
    user_repo: UserRepository = Depends(),
    group_repo: GroupRepository = Depends(),
):
    """HTMX partial: list of users with their groups."""
    users = await user_repo.get_all_users()
    all_groups = await group_repo.get_all_groups()

    users_with_groups = []
    for u in users:
        user_groups = await user_repo.get_user_groups(u.id)
        users_with_groups.append({"user": u, "groups": user_groups})

    return templates.TemplateResponse(
        request,
        "partials/users_table.html",
        {"users_with_groups": users_with_groups, "all_groups": all_groups},
    )


@router.post("/users", response_class=HTMLResponse)
async def create_user(
    request: Request,
    current_user: User = Depends(can_admin),
    auth_service: AuthService = Depends(),
    user_repo: UserRepository = Depends(),
    group_repo: GroupRepository = Depends(),
):
    """Create a new user (admin only)."""
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "").strip()
    full_name = form.get("full_name", "").strip() or None
    group_ids = [int(g) for g in form.getlist("group_ids")]

    error = None
    if not username or not password:
        error = "Usuario e senha sao obrigatorios."
    else:
        existing = await user_repo.get_user_by_username(username)
        if existing:
            error = f"Usuario '{username}' ja existe."

    if error:
        users = await user_repo.get_all_users()
        all_groups = await group_repo.get_all_groups()
        users_with_groups = []
        for u in users:
            user_groups = await user_repo.get_user_groups(u.id)
            users_with_groups.append({"user": u, "groups": user_groups})
        return templates.TemplateResponse(
            request,
            "partials/users_table.html",
            {"users_with_groups": users_with_groups, "all_groups": all_groups, "error": error},
        )

    await auth_service.create_user(username, password, full_name, group_ids)

    # Return updated list
    users = await user_repo.get_all_users()
    all_groups = await group_repo.get_all_groups()
    users_with_groups = []
    for u in users:
        user_groups = await user_repo.get_user_groups(u.id)
        users_with_groups.append({"user": u, "groups": user_groups})

    return templates.TemplateResponse(
        request,
        "partials/users_table.html",
        {"users_with_groups": users_with_groups, "all_groups": all_groups, "success": "Usuario criado com sucesso."},
    )


@router.post("/users/{user_id}/groups", response_class=HTMLResponse)
async def update_user_groups(
    request: Request,
    user_id: int,
    current_user: User = Depends(can_admin),
    user_repo: UserRepository = Depends(),
    group_repo: GroupRepository = Depends(),
):
    """Update groups for a user (admin only)."""
    form = await request.form()
    group_ids = [int(g) for g in form.getlist("group_ids")]

    user = await user_repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    await user_repo.set_user_groups(user_id, group_ids)

    # Return updated list
    users = await user_repo.get_all_users()
    all_groups = await group_repo.get_all_groups()
    users_with_groups = []
    for u in users:
        user_groups = await user_repo.get_user_groups(u.id)
        users_with_groups.append({"user": u, "groups": user_groups})

    return templates.TemplateResponse(
        request,
        "partials/users_table.html",
        {"users_with_groups": users_with_groups, "all_groups": all_groups, "success": "Grupos atualizados."},
    )


@router.post("/users/{user_id}/toggle-active", response_class=HTMLResponse)
async def toggle_user_active(
    request: Request,
    user_id: int,
    current_user: User = Depends(can_admin),
    user_repo: UserRepository = Depends(),
    group_repo: GroupRepository = Depends(),
):
    """Toggle a user's active status (admin only)."""
    user = await user_repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    user.is_active = not user.is_active
    await user_repo.update_user(user)

    # Return updated list
    users = await user_repo.get_all_users()
    all_groups = await group_repo.get_all_groups()
    users_with_groups = []
    for u in users:
        user_groups = await user_repo.get_user_groups(u.id)
        users_with_groups.append({"user": u, "groups": user_groups})

    return templates.TemplateResponse(
        request,
        "partials/users_table.html",
        {"users_with_groups": users_with_groups, "all_groups": all_groups},
    )


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Page for logged-in user to change their own password."""
    return templates.TemplateResponse(
        request,
        "change_password.html",
        {"current_user": current_user},
    )


@router.post("/change-password", response_class=HTMLResponse)
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(),
):
    """Change the logged-in user's password."""
    error = None
    success = None

    if new_password != confirm_password:
        error = "As senhas novas nao conferem."
    elif len(new_password) < 4:
        error = "A nova senha deve ter pelo menos 4 caracteres."
    else:
        # Verify current password
        verified = await auth_service.authenticate(current_user.username, current_password)
        if verified is None:
            error = "Senha atual incorreta."
        else:
            await auth_service.update_password(current_user.id, new_password)
            success = "Senha alterada com sucesso."

    return templates.TemplateResponse(
        request,
        "change_password.html",
        {"current_user": current_user, "error": error, "success": success},
    )
