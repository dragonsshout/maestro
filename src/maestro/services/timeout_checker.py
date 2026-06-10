"""
Background service that periodically checks for steps that exceeded their timeout.

Steps in 'in_progress' status whose updated_at is older than the configured timeout
are marked as 'timeout'.

Timeout resolution order:
1. Step-level timeout_minutes (from YAML)
2. Global step_timeout_minutes (from UI settings)
3. No timeout (if neither is configured, step runs indefinitely)
"""

import asyncio
from datetime import datetime, timedelta, timezone

import yaml
from sqlalchemy.future import select

from maestro.config.logger import get_logger
from maestro.database.models import OrchestratorDescriptor, ReleaseExecution, ReleaseStepExecution
from maestro.database.session import AsyncSessionLocal
from maestro.repositories.settings import UISettingsRepository
from maestro.schemas.enums import ExecutionStatus
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.services.settings import SETTING_STEP_TIMEOUT_MINUTES

logger = get_logger(__name__)

DEFAULT_CHECK_INTERVAL_SECONDS = 30


async def start_timeout_checker():
    """Entry point: runs the timeout check loop indefinitely."""
    logger.info("Timeout checker started.")
    while True:
        try:
            await _check_timeouts()
        except Exception as e:
            logger.error(f"Timeout checker error: {e}")
        await asyncio.sleep(DEFAULT_CHECK_INTERVAL_SECONDS)


async def _check_timeouts():
    """Single pass: find timed-out steps and mark them."""

    logger.info("Checking for timed out release steps...")
    async with AsyncSessionLocal() as session:
        # Get global timeout setting
        settings_repo = UISettingsRepository(db=session)
        global_timeout_str = await settings_repo.get(SETTING_STEP_TIMEOUT_MINUTES)
        global_timeout = int(global_timeout_str) if global_timeout_str else None

        # Find all steps currently in_progress
        result = await session.execute(
            select(ReleaseStepExecution).where(ReleaseStepExecution.status == ExecutionStatus.IN_PROGRESS)
        )
        in_progress_steps = list(result.scalars().all())

        if not in_progress_steps:
            return

        now = datetime.now(timezone.utc)

        # Group steps by execution to load their YAML configs
        execution_ids = set(s.release_execution_id for s in in_progress_steps)
        exec_result = await session.execute(select(ReleaseExecution).where(ReleaseExecution.id.in_(execution_ids)))
        executions = {e.id: e for e in exec_result.scalars().all()}

        # Load descriptors for timeout_minutes per step
        descriptor_ids = set(e.orchestrator_descriptor_id for e in executions.values())
        desc_result = await session.execute(
            select(OrchestratorDescriptor).where(OrchestratorDescriptor.id.in_(descriptor_ids))
        )
        descriptors = {d.id: d for d in desc_result.scalars().all()}

        # Build step-level timeout map: (stage_id, step_id) -> timeout_minutes
        step_timeout_map: dict[tuple[int, str, str], int | None] = {}
        for exec_id, execution in executions.items():
            descriptor = descriptors.get(execution.orchestrator_descriptor_id)
            if not descriptor:
                continue
            config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
            for stage in config.spec.stages:
                for step in stage.steps:
                    step_timeout_map[(exec_id, stage.id, step.id)] = step.timeout_minutes

        # Check each step
        timed_out = []
        for step in in_progress_steps:
            # Resolve timeout: step-level > global > None (no timeout)
            key = (step.release_execution_id, step.stage_id, step.step_id)
            step_timeout = step_timeout_map.get(key)
            effective_timeout = step_timeout if step_timeout is not None else global_timeout

            if effective_timeout is None:
                continue  # No timeout configured for this step

            deadline = step.updated_at.replace(tzinfo=timezone.utc) + timedelta(minutes=effective_timeout)
            if now > deadline:
                step.status = ExecutionStatus.TIMEOUT
                step.message = f"Timeout após {effective_timeout} minutos sem resposta."
                session.add(step)
                timed_out.append(step)
                logger.warning(
                    f"Step {step.step_id} (stage={step.stage_id}, execution={step.release_execution_id}) "
                    f"marked as TIMEOUT after {effective_timeout}min."
                )

        if timed_out:
            await session.commit()
