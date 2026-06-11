from typing import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from maestro.database.models import User
from maestro.database.session import get_db
from maestro.repositories.auth import UserRepository
from maestro.services.auth import AuthService


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract user from JWT session cookie.

    If not authenticated:
    - UI requests (Accept: text/html) are redirected to /ui/login
    - API requests receive a 401 response
    """
    token = request.cookies.get("maestro_session")

    user = None
    if token:
        payload = AuthService.decode_session_token(token)
        if payload and "sub" in payload:
            user_id = int(payload["sub"])
            user_repo = UserRepository(db=db)
            user = await user_repo.get_user_by_id(user_id)
            if user and not user.is_active:
                user = None

    if user is None:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/ui/login", status_code=302)
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user


def require_group(group_name: str) -> Callable:
    """Return a dependency that verifies the current user belongs to a specific group."""

    async def _check_group(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user = await get_current_user(request, db)
        # If we got a RedirectResponse back, return it as-is
        if isinstance(user, RedirectResponse):
            return user

        user_repo = UserRepository(db=db)
        groups = await user_repo.get_user_groups(user.id)
        group_names = [g.name for g in groups]

        if group_name not in group_names:
            raise HTTPException(status_code=403, detail=f"Requires group: {group_name}")

        return user

    return _check_group


def _require_any_group(allowed_groups: list[str]) -> Callable:
    """Return a dependency that verifies the current user belongs to at least one of the allowed groups."""

    async def _check_groups(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user = await get_current_user(request, db)
        if isinstance(user, RedirectResponse):
            return user

        user_repo = UserRepository(db=db)
        groups = await user_repo.get_user_groups(user.id)
        group_names = [g.name for g in groups]

        if not any(g in allowed_groups for g in group_names):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {', '.join(allowed_groups)}",
            )

        return user

    return _check_groups


# Permission level helpers
can_view = get_current_user  # Any authenticated user can view
can_approve = _require_any_group(["Approver", "Operators", "Administrators"])
can_operate = _require_any_group(["Operators", "Administrators"])
can_admin = _require_any_group(["Administrators"])
