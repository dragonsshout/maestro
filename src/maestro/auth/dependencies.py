from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from maestro.database.models import User
from maestro.database.session import get_db
from maestro.repositories.auth import UserRepository
from maestro.services.auth import AuthService

# Permission groups mapping (single source of truth)
GROUPS_CAN_OPERATE = ["Operators", "Administrators"]
GROUPS_CAN_APPROVE = ["Approver", "Operators", "Administrators"]
GROUPS_CAN_ADMIN = ["Administrators"]


class NotAuthenticatedException(Exception):
    """Raised when a user is not authenticated.

    The exception handler in main.py catches this and redirects HTML requests to /ui/login
    or returns a 401 for API requests.
    """

    pass


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract user from JWT session cookie.

    Raises NotAuthenticatedException if not authenticated.
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
        raise NotAuthenticatedException()

    return user


async def _get_user_group_names(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Fetch user group names, caching on request.state to avoid duplicate DB queries."""
    if hasattr(request.state, "user_group_names"):
        return request.state.user_group_names

    user_repo = UserRepository(db=db)
    groups = await user_repo.get_user_groups(current_user.id)
    group_names = [g.name for g in groups]
    request.state.user_group_names = group_names
    return group_names


def _require_any_group(allowed_groups: list[str]) -> Callable:
    """Return a dependency that verifies the current user belongs to at least one of the allowed groups."""

    async def _check_groups(
        current_user: User = Depends(get_current_user),
        group_names: list[str] = Depends(_get_user_group_names),
    ) -> User:
        if not any(g in allowed_groups for g in group_names):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {', '.join(allowed_groups)}",
            )

        return current_user

    return _check_groups


def require_group(group_name: str) -> Callable:
    """Return a dependency that verifies the current user belongs to a specific group."""

    async def _check_group(
        current_user: User = Depends(get_current_user),
        group_names: list[str] = Depends(_get_user_group_names),
    ) -> User:
        if group_name not in group_names:
            raise HTTPException(status_code=403, detail=f"Requires group: {group_name}")

        return current_user

    return _check_group


# Permission level helpers (use the shared constants)
can_view = get_current_user  # Any authenticated user can view
can_approve = _require_any_group(GROUPS_CAN_APPROVE)
can_operate = _require_any_group(GROUPS_CAN_OPERATE)
can_admin = _require_any_group(GROUPS_CAN_ADMIN)


def build_user_permissions(group_names: list[str]) -> dict:
    """Build a permissions dict from user group names."""
    return {
        "can_operate": any(g in GROUPS_CAN_OPERATE for g in group_names),
        "can_approve": any(g in GROUPS_CAN_APPROVE for g in group_names),
        "can_admin": any(g in GROUPS_CAN_ADMIN for g in group_names),
    }


async def get_user_permissions(
    group_names: list[str] = Depends(_get_user_group_names),
) -> dict:
    """FastAPI dependency that returns a permissions dict for the current user.

    Uses the cached group names from request.state to avoid duplicate DB queries.
    """
    return build_user_permissions(group_names)
