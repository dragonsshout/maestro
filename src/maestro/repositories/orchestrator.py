from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from maestro.database.models import OrchestratorDescriptor
from maestro.database.session import get_db


class OrchestratorDescriptorRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def add(self, descriptor: OrchestratorDescriptor) -> OrchestratorDescriptor:
        self.db.add(descriptor)
        await self.db.commit()
        await self.db.refresh(descriptor)
        return descriptor

    async def get_by_id(self, descriptor_id: int) -> OrchestratorDescriptor | None:
        result = await self.db.execute(select(OrchestratorDescriptor).where(OrchestratorDescriptor.id == descriptor_id))
        return result.scalars().first()

    async def get_by_name(self, name: str) -> OrchestratorDescriptor | None:
        result = await self.db.execute(select(OrchestratorDescriptor).where(OrchestratorDescriptor.name == name))
        return result.scalars().first()

    async def get_all(self, skip: int = 0, limit: int = 15, search: str | None = None) -> list[OrchestratorDescriptor]:
        query = select(OrchestratorDescriptor)
        if search:
            query = query.where(OrchestratorDescriptor.name.ilike(f"%{search}%"))
        query = query.order_by(OrchestratorDescriptor.id).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_count(self, search: str | None = None) -> int:
        from sqlalchemy import func

        query = select(func.count(OrchestratorDescriptor.id))
        if search:
            query = query.where(OrchestratorDescriptor.name.ilike(f"%{search}%"))
        result = await self.db.execute(query)
        return result.scalar()
