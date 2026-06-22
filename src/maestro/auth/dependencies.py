from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from maestro.auth.security import decode_access_token
from maestro.database.models import User
from maestro.database.session import get_db
from maestro.repositories.user import UserRepository

# This header is sent by htmx when performing an ajax request
HTMX_REQUEST_HEADER = "HX-Request"


class RequiresAuthException(Exception):
    pass


async def get_current_user_optional(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    token = request.cookies.get("maestro_session")
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    username: str = payload.get("sub")
    if username is None:
        return None

    user_repo = UserRepository(db)
    user = await user_repo.get_by_username(username)
    return user


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await get_current_user_optional(request, db)
    if not user:
        raise RequiresAuthException()

    request.state.current_user = user
    return user
