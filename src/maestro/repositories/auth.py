from typing import Optional

from fastapi import Depends
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from maestro.database.models import Group, User, UserGroupAssociation
from maestro.database.session import get_db


class UserRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def get_user_by_username(self, username: str) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalars().first()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

    async def create_user(self, username: str, password_hash: str, full_name: Optional[str] = None) -> User:
        user = User(username=username, password_hash=password_hash, full_name=full_name)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user(self, user: User) -> User:
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def get_all_users(self) -> list[User]:
        result = await self.db.execute(select(User).order_by(User.username))
        return list(result.scalars().all())

    async def get_user_groups(self, user_id: int) -> list[Group]:
        result = await self.db.execute(
            select(Group)
            .join(UserGroupAssociation, UserGroupAssociation.group_id == Group.id)
            .where(UserGroupAssociation.user_id == user_id)
        )
        return list(result.scalars().all())

    async def set_user_groups(self, user_id: int, group_ids: list[int]) -> None:
        await self.db.execute(
            delete(UserGroupAssociation).where(UserGroupAssociation.user_id == user_id)
        )
        for group_id in group_ids:
            assoc = UserGroupAssociation(user_id=user_id, group_id=group_id)
            self.db.add(assoc)
        await self.db.commit()


class GroupRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def get_all_groups(self) -> list[Group]:
        result = await self.db.execute(select(Group).order_by(Group.name))
        return list(result.scalars().all())

    async def get_group_by_name(self, name: str) -> Optional[Group]:
        result = await self.db.execute(select(Group).where(Group.name == name))
        return result.scalars().first()

    async def get_group_by_id(self, group_id: int) -> Optional[Group]:
        result = await self.db.execute(select(Group).where(Group.id == group_id))
        return result.scalars().first()
