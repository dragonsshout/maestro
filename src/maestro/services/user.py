from sqlalchemy.ext.asyncio import AsyncSession

from maestro.auth.security import get_password_hash
from maestro.database.models import User
from maestro.repositories.user import UserRepository


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def get_all_users(self) -> list[User]:
        return await self.user_repo.get_all()

    async def get_user_by_username(self, username: str) -> User | None:
        return await self.user_repo.get_by_username(username)

    async def create_user(self, username: str, password_plain: str, group: str) -> User:
        if await self.user_repo.get_by_username(username):
            raise ValueError(f"Usuário '{username}' já existe.")

        hashed = get_password_hash(password_plain)
        user = User(username=username, password_hash=hashed, group=group)
        return await self.user_repo.add(user)

    async def update_user_group(self, user_id: int, group: str) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("Usuário não encontrado.")
        user.group = group
        return await self.user_repo.update(user)

    async def change_password(self, user_id: int, new_password_plain: str) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("Usuário não encontrado.")
        user.password_hash = get_password_hash(new_password_plain)
        return await self.user_repo.update(user)
