from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from maestro.database.session import get_db
from maestro.database.models import ReleaseExecution, ReleaseStepExecution
from typing import List

class ExecutionRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def add_release_execution(self, execution: ReleaseExecution) -> ReleaseExecution:
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def update_release_execution(self, execution: ReleaseExecution) -> ReleaseExecution:
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def get_execution_by_id(self, execution_id: int) -> ReleaseExecution | None:
        result = await self.db.execute(
            select(ReleaseExecution).where(ReleaseExecution.id == execution_id)
        )
        return result.scalars().first()

    async def add_step_execution(self, execution: ReleaseStepExecution) -> ReleaseStepExecution:
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def update_step_execution(self, execution: ReleaseStepExecution) -> ReleaseStepExecution:
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def get_steps_by_execution_id(self, release_execution_id: int) -> List[ReleaseStepExecution]:
        result = await self.db.execute(
            select(ReleaseStepExecution).where(ReleaseStepExecution.release_execution_id == release_execution_id)
        )
        return list(result.scalars().all())

    async def get_specific_step(self, release_execution_id: int, stage_id: str, step_id: str) -> ReleaseStepExecution | None:
        result = await self.db.execute(
            select(ReleaseStepExecution).where(
                ReleaseStepExecution.release_execution_id == release_execution_id,
                ReleaseStepExecution.stage_id == stage_id,
                ReleaseStepExecution.step_id == step_id
            )
        )
        return result.scalars().first()

    async def exists_by_name(self, name: str) -> bool:
        result = await self.db.execute(
            select(ReleaseExecution).where(ReleaseExecution.name == name).limit(1)
        )
        return result.scalars().first() is not None

    async def get_latest_execution_by_name(self, name: str) -> ReleaseExecution | None:
        result = await self.db.execute(
            select(ReleaseExecution)
            .where(ReleaseExecution.name == name)
            .order_by(ReleaseExecution.id.desc())
            .limit(1)
        )
        return result.scalars().first()
