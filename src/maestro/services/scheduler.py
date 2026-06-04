"""
Servico de agendamento de releases.

Permite agendar a execucao de uma release para uma data/hora futura.
O background task (start_scheduler_checker) verifica periodicamente se
ha agendamentos pendentes prontos para execucao.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, BackgroundTasks

from maestro.config.logger import get_logger
from maestro.database.models import ScheduledRelease
from maestro.repositories.schedule import ScheduleRepository
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.repositories.execution import ExecutionRepository
from maestro.schemas.enums import ScheduledReleaseStatus

logger = get_logger(__name__)

CHECK_INTERVAL_SECONDS = 30


class SchedulerService:
    def __init__(
        self,
        schedule_repo: ScheduleRepository = Depends(),
        orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
        execution_repo: ExecutionRepository = Depends(),
    ):
        self.schedule_repo = schedule_repo
        self.orchestrator_repo = orchestrator_repo
        self.execution_repo = execution_repo

    async def schedule_release(
        self, name: str, scheduled_at: datetime, created_by: Optional[str] = None
    ) -> ScheduledRelease:
        """Agenda a execucao de uma release para a data/hora informada."""
        # Valida que a data e no futuro
        now = datetime.now(timezone.utc)
        scheduled_at_utc = scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc)
        if scheduled_at_utc <= now:
            raise ValueError("A data de agendamento deve ser no futuro.")

        # Verifica se ja existe agendamento pendente para esta release
        has_pending = await self.schedule_repo.has_pending_schedule_for_release(name)
        if has_pending:
            raise ValueError(
                f"Ja existe um agendamento pendente para a release '{name}'. "
                "Cancele o agendamento existente antes de criar um novo."
            )

        # Verifica se o descritor existe
        descriptor = await self.orchestrator_repo.get_by_name(name)
        if not descriptor:
            raise ValueError(f"Descritor com nome '{name}' nao encontrado.")

        schedule = ScheduledRelease(
            orchestrator_descriptor_id=descriptor.id,
            name=name,
            scheduled_at=scheduled_at_utc,
            status=ScheduledReleaseStatus.PENDING.value,
            created_by=created_by,
        )
        return await self.schedule_repo.create_schedule(schedule)

    async def cancel_schedule(self, schedule_id: int) -> ScheduledRelease:
        """Cancela um agendamento pendente."""
        return await self.schedule_repo.cancel_schedule(schedule_id)

    async def get_all_schedules(self, skip: int = 0, limit: int = 50) -> List[ScheduledRelease]:
        """Retorna todos os agendamentos."""
        return await self.schedule_repo.get_all_schedules(skip=skip, limit=limit)

    async def get_schedules_for_release(self, name: str) -> List[ScheduledRelease]:
        """Retorna agendamentos de uma release especifica."""
        return await self.schedule_repo.get_schedules_for_release(name)


async def start_scheduler_checker():
    """Entry point: runs the schedule dispatch loop indefinitely."""
    logger.info("Scheduler checker started.")
    while True:
        try:
            await _process_due_schedules()
        except Exception as e:
            logger.error(f"Scheduler checker error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _process_due_schedules():
    """Single pass: find due schedules and trigger their executions."""
    from maestro.database.session import AsyncSessionLocal
    from maestro.repositories.schedule import ScheduleRepository
    from maestro.repositories.execution import ExecutionRepository
    from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
    from maestro.services.orchestrator import OrchestratorService
    from maestro.services.jenkins import JenkinsService

    async with AsyncSessionLocal() as session:
        schedule_repo = ScheduleRepository(db=session)
        exec_repo = ExecutionRepository(db=session)
        orch_repo = OrchestratorDescriptorRepository(db=session)

        pending = await schedule_repo.get_pending_due_schedules()
        if not pending:
            return

        for schedule in pending:
            try:
                # Verifica se ha execucao ativa para esta release
                active = await exec_repo.get_active_execution_by_name(schedule.name)
                if active:
                    await schedule_repo.mark_failed(
                        schedule.id,
                        f"Execucao ativa #{active.id} encontrada para a release '{schedule.name}'. "
                        "Agendamento nao pode ser executado."
                    )
                    continue

                # Monta o OrchestratorService manualmente (como process_workflow faz)
                jenkins_service = JenkinsService()
                svc = OrchestratorService.__new__(OrchestratorService)
                svc.repository = orch_repo
                svc.execution_repo = exec_repo
                svc.jenkins_service = jenkins_service

                bg = BackgroundTasks()
                execution_id = await svc.execute_release(schedule.name, bg)

                await schedule_repo.mark_executed(schedule.id, execution_id)

                # Executa as background tasks que foram enfileiradas
                for task in bg.tasks:
                    asyncio.create_task(task.func(*task.args, **task.kwargs))

            except Exception as e:
                logger.error(f"Falha ao executar agendamento da release '{schedule.name}': {e}")
                await schedule_repo.mark_failed(schedule.id, str(e))
