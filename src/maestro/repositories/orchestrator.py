from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from maestro.database.session import get_db
from maestro.database.models import OrchestratorDescriptor

class OrchestratorDescriptorRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def add(self, descriptor: OrchestratorDescriptor) -> OrchestratorDescriptor:
        self.db.add(descriptor)
        await self.db.commit()
        await self.db.refresh(descriptor)
        return descriptor

    async def get_by_id(self, descriptor_id: int) -> OrchestratorDescriptor | None:
        result = await self.db.execute(
            select(OrchestratorDescriptor).where(OrchestratorDescriptor.id == descriptor_id)
        )
        return result.scalars().first()

    async def get_by_name(self, name: str) -> OrchestratorDescriptor | None:
        result = await self.db.execute(
            select(OrchestratorDescriptor).where(OrchestratorDescriptor.name == name)
        )
        return result.scalars().first()

    async def get_all(self) -> list[OrchestratorDescriptor]:
        result = await self.db.execute(
            select(OrchestratorDescriptor).order_by(OrchestratorDescriptor.id)
        )
        return list(result.scalars().all())
