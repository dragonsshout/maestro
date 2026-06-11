from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends
from jose import JWTError, jwt
from passlib.context import CryptContext

from maestro.config.settings import settings
from maestro.database.models import User
from maestro.repositories.auth import GroupRepository, UserRepository

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository = Depends(),
        group_repo: GroupRepository = Depends(),
    ):
        self.user_repo = user_repo
        self.group_repo = group_repo

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authenticate a user by username and password. Returns User or None."""
        user = await self.user_repo.get_user_by_username(username)
        if user is None:
            return None
        if not user.is_active:
            return None
        if not pwd_context.verify(password, user.password_hash):
            return None
        return user

    async def create_user(
        self,
        username: str,
        password: str,
        full_name: Optional[str] = None,
        group_ids: Optional[list[int]] = None,
    ) -> User:
        """Create a new user with hashed password and optional group assignments."""
        password_hash = pwd_context.hash(password)
        user = await self.user_repo.create_user(username, password_hash, full_name)
        if group_ids:
            await self.user_repo.set_user_groups(user.id, group_ids)
        return user

    async def update_password(self, user_id: int, new_password: str) -> Optional[User]:
        """Update a user's password."""
        user = await self.user_repo.get_user_by_id(user_id)
        if user is None:
            return None
        user.password_hash = pwd_context.hash(new_password)
        return await self.user_repo.update_user(user)

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get a user by ID."""
        return await self.user_repo.get_user_by_id(user_id)

    async def get_user_groups(self, user_id: int) -> list:
        """Get all groups for a user."""
        return await self.user_repo.get_user_groups(user_id)

    def create_session_token(self, user: User) -> str:
        """Create a JWT session token for a user."""
        expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
        payload = {
            "sub": str(user.id),
            "username": user.username,
            "exp": expire,
        }
        return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)

    @staticmethod
    def decode_session_token(token: str) -> Optional[dict]:
        """Decode a JWT session token. Returns payload dict or None if invalid."""
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None
