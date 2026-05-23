from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from maestro.database.session import get_db
from maestro.database.models import ReleaseStepExecution
from typing import List

class ReleaseStepExecutionRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def add(self, execution: ReleaseStepExecution) -> ReleaseStepExecution:
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def get_by_process_id(self, release_process_id: str) -> List[ReleaseStepExecution]:
        result = await self.db.execute(
            select(ReleaseStepExecution).where(ReleaseStepExecution.release_process_id == release_process_id)
        )
        return list(result.scalars().all())

    async def get_specific_step(self, release_process_id: str, stage_id: str, step_id: str) -> ReleaseStepExecution | None:
        result = await self.db.execute(
            select(ReleaseStepExecution).where(
                ReleaseStepExecution.release_process_id == release_process_id,
                ReleaseStepExecution.stage_id == stage_id,
                ReleaseStepExecution.step_id == step_id
            )
        )
        return result.scalars().first()
