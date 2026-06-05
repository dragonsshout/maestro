from datetime import datetime, timezone
from typing import List

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from maestro.database.session import get_db
from maestro.database.models import ScheduledRelease
from maestro.schemas.enums import ScheduledReleaseStatus


class ScheduleRepository:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def create_schedule(self, schedule: ScheduledRelease) -> ScheduledRelease:
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def get_pending_due_schedules(self) -> List[ScheduledRelease]:
        """Retorna agendamentos pendentes cuja data ja passou (prontos para execucao)."""
        result = await self.db.execute(
            select(ScheduledRelease).where(
                ScheduledRelease.status == ScheduledReleaseStatus.PENDING.value,
                ScheduledRelease.scheduled_at <= func.now(),
            ).order_by(ScheduledRelease.scheduled_at.asc())
        )
        return list(result.scalars().all())

    async def cancel_schedule(self, schedule_id: int) -> ScheduledRelease:
        """Cancela um agendamento pendente. Levanta ValueError se nao encontrado ou nao pendente."""
        result = await self.db.execute(
            select(ScheduledRelease).where(ScheduledRelease.id == schedule_id)
        )
        schedule = result.scalars().first()
        if not schedule:
            raise ValueError(f"Agendamento #{schedule_id} nao encontrado.")
        if schedule.status != ScheduledReleaseStatus.PENDING.value:
            raise ValueError(
                f"Agendamento #{schedule_id} nao pode ser cancelado (status: {schedule.status})."
            )
        schedule.status = ScheduledReleaseStatus.CANCELLED.value
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def mark_executed(self, schedule_id: int, execution_id: int) -> None:
        """Marca um agendamento como executado com o ID da execucao criada."""
        result = await self.db.execute(
            select(ScheduledRelease).where(ScheduledRelease.id == schedule_id)
        )
        schedule = result.scalars().first()
        if schedule:
            schedule.status = ScheduledReleaseStatus.EXECUTED.value
            schedule.release_execution_id = execution_id
            self.db.add(schedule)
            await self.db.commit()

    async def mark_failed(self, schedule_id: int, error_message: str) -> None:
        """Marca um agendamento como falho com mensagem de erro."""
        result = await self.db.execute(
            select(ScheduledRelease).where(ScheduledRelease.id == schedule_id)
        )
        schedule = result.scalars().first()
        if schedule:
            schedule.status = ScheduledReleaseStatus.FAILED.value
            schedule.error_message = error_message
            self.db.add(schedule)
            await self.db.commit()

    async def get_schedules_for_release(self, name: str) -> List[ScheduledRelease]:
        """Retorna todos os agendamentos de uma release especifica."""
        result = await self.db.execute(
            select(ScheduledRelease)
            .where(ScheduledRelease.name == name)
            .order_by(ScheduledRelease.scheduled_at.desc())
        )
        return list(result.scalars().all())

    async def get_all_schedules(self, skip: int = 0, limit: int = 50, search: str = None) -> List[ScheduledRelease]:
        """Retorna todos os agendamentos ordenados por data de criacao, com suporte a busca."""
        query = select(ScheduledRelease)
        if search:
            query = query.where(ScheduledRelease.name.ilike(f"%{search}%"))
        
        result = await self.db.execute(
            query.order_by(ScheduledRelease.scheduled_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_schedules_count(self, search: str = None) -> int:
        """Retorna a contagem total de agendamentos."""
        query = select(func.count(ScheduledRelease.id))
        if search:
            query = query.where(ScheduledRelease.name.ilike(f"%{search}%"))
        result = await self.db.execute(query)
        return result.scalar()

    async def has_pending_schedule_for_release(self, name: str) -> bool:
        """Verifica se existe um agendamento pendente para a release informada."""
        result = await self.db.execute(
            select(func.count(ScheduledRelease.id)).where(
                ScheduledRelease.name == name,
                ScheduledRelease.status == ScheduledReleaseStatus.PENDING.value,
            )
        )
        count = result.scalar()
        return count > 0
