from fastapi import Depends
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from maestro.database.models import JobPathRegistry
from maestro.database.session import get_db


class JobPathRegistryRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def get_by_repository_and_environment(self, repository: str, environment: str) -> JobPathRegistry | None:
        result = await self.db.execute(
            select(JobPathRegistry).where(
                JobPathRegistry.repository == repository,
                JobPathRegistry.environment == environment,
            )
        )
        return result.scalars().first()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 15,
        search: str | None = None,
    ) -> list[JobPathRegistry]:
        query = select(JobPathRegistry)
        if search:
            query = query.where(JobPathRegistry.repository.ilike(f"%{search}%"))
        query = query.order_by(JobPathRegistry.repository, JobPathRegistry.environment).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_count(self, search: str | None = None) -> int:
        query = select(func.count(JobPathRegistry.id))
        if search:
            query = query.where(JobPathRegistry.repository.ilike(f"%{search}%"))
        result = await self.db.execute(query)
        return result.scalar()

    async def upsert(self, entry: JobPathRegistry) -> JobPathRegistry:
        """
        Insere ou atualiza um registro baseado na chave única (repository + environment).
        """
        existing = await self.get_by_repository_and_environment(entry.repository, entry.environment)
        if existing:
            existing.domain = entry.domain
            existing.type = entry.type
            existing.path = entry.path
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            self.db.add(entry)
            await self.db.commit()
            await self.db.refresh(entry)
            return entry

    async def upsert_many(self, entries: list[JobPathRegistry]) -> int:
        """
        Faz upsert de múltiplos registros. Retorna a quantidade processada.
        """
        count = 0
        for entry in entries:
            await self.upsert(entry)
            count += 1
        return count

    async def delete(self, entry_id: int) -> bool:
        result = await self.db.execute(select(JobPathRegistry).where(JobPathRegistry.id == entry_id))
        entry = result.scalars().first()
        if not entry:
            return False
        await self.db.delete(entry)
        await self.db.commit()
        return True
