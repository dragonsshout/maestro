"""
Background service that polls Jenkins builds to automatically detect:
- Build completed (SUCCESS/FAILURE/ABORTED)
- Build waiting for input (waiting_approval)

This eliminates the need for callbacks from Jenkins for status updates.
"""
import asyncio

import yaml

from maestro.config.logger import get_logger
from maestro.database.models import ReleaseStepExecution
from maestro.integration.jenkins import JenkinsIntegration
from maestro.schemas.enums import ExecutionStatus
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.services.app_settings import get_integration_settings

logger = get_logger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 10


async def start_build_poller():
    """Entry point: runs the build polling loop indefinitely."""
    logger.info("Build poller started.")
    while True:
        try:
            interval = await _get_poll_interval()
            await _poll_builds()
        except Exception as e:
            logger.error(f"Build poller error: {e}")
            interval = DEFAULT_POLL_INTERVAL_SECONDS
        await asyncio.sleep(interval)


async def _get_poll_interval() -> int:
    """Lê o intervalo de polling das configurações do banco."""
    from maestro.database.session import AsyncSessionLocal
    from maestro.repositories.settings import UISettingsRepository
    from maestro.services.settings import SETTING_BUILD_POLL_INTERVAL_SECONDS

    async with AsyncSessionLocal() as session:
        repo = UISettingsRepository(db=session)
        value = await repo.get(SETTING_BUILD_POLL_INTERVAL_SECONDS)
        if value:
            try:
                return max(1, int(value))
            except ValueError:
                pass
    return DEFAULT_POLL_INTERVAL_SECONDS


async def _poll_builds():
    """Single pass: check all in_progress steps with correlation_id against Jenkins."""
    from maestro.database.session import AsyncSessionLocal
    from maestro.repositories.execution import ExecutionRepository

    async with AsyncSessionLocal() as session:
        repo = ExecutionRepository(db=session)

        # Busca steps in_progress com correlation_id via repository
        steps = await repo.get_in_progress_steps_with_correlation()
        if not steps:
            return

        # Carrega execuções e descriptors via repository
        execution_ids = set(s.release_execution_id for s in steps)
        executions = await repo.get_executions_by_ids(execution_ids)

        descriptor_ids = set(e.orchestrator_descriptor_id for e in executions.values())
        descriptors = await repo.get_descriptors_by_ids(descriptor_ids)

        # Monta mapa de job_path a partir dos YAMLs
        job_path_map: dict[tuple[int, str, str], str] = {}
        for exec_id, execution in executions.items():
            descriptor = descriptors.get(execution.orchestrator_descriptor_id)
            if not descriptor:
                continue
            config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
            for stage in config.spec.stages:
                for step_def in stage.steps:
                    job_path_map[(exec_id, stage.id, step_def.id)] = step_def.job.path

        # Obtém integração Jenkins
        cfg = await get_integration_settings(session)
        jenkins = JenkinsIntegration(
            base_url=cfg.jenkins_url,
            username=cfg.jenkins_username,
            token=cfg.jenkins_token,
            trust_env=cfg.http_trust_env,
        )

        # Verifica cada step
        any_changed = False
        for step in steps:
            key = (step.release_execution_id, step.stage_id, step.step_id)
            job_path = job_path_map.get(key)
            if not job_path:
                continue

            build_number = step.job_execution_correlation_id
            try:
                changed = await _check_step_build(jenkins, step, job_path, build_number, session)
                if changed:
                    any_changed = True
            except Exception as e:
                logger.warning(
                    f"Error polling build #{build_number} for step {step.step_id} "
                    f"(job={job_path}): {e}"
                )

        if any_changed:
            await session.commit()

            # Re-dispara workflow para execuções que tiveram mudança
            changed_execution_ids = set(
                s.release_execution_id for s in steps
                if s.status != ExecutionStatus.IN_PROGRESS
            )
            for exec_id in changed_execution_ids:
                try:
                    await _retrigger_workflow(exec_id)
                except Exception as e:
                    logger.error(f"Error re-triggering workflow for execution {exec_id}: {e}")


async def _retrigger_workflow(execution_id: int):
    """Re-dispara o process_workflow para uma execução."""
    from maestro.services.orchestrator import OrchestratorService
    from maestro.services.jenkins import JenkinsService

    svc = OrchestratorService.__new__(OrchestratorService)
    jenkins_svc = JenkinsService.__new__(JenkinsService)
    jenkins_svc._jenkins_integration = None
    jenkins_svc.execution_repo = None
    svc.jenkins_service = jenkins_svc
    await svc.process_workflow(execution_id)


async def _check_step_build(
    jenkins: JenkinsIntegration,
    step: ReleaseStepExecution,
    job_path: str,
    build_number: int,
    session,
) -> bool:
    """
    Check a single build status. Returns True if the step status was updated.
    """
    # 1. Verifica pending inputs primeiro (maior prioridade)
    #    Jenkins pode reportar building=false enquanto parado em input
    try:
        pending_inputs = await jenkins.get_pending_inputs(job_path, build_number)
        if pending_inputs:
            step.status = ExecutionStatus.WAITING_APPROVAL
            step.job_input_id = pending_inputs[0].id
            step.message = "Aguardando aprovação no Jenkins."
            session.add(step)
            logger.info(
                f"Step {step.step_id} (build #{build_number}): "
                f"pending input detected → waiting_approval (input_id={pending_inputs[0].id})"
            )
            return True
    except Exception as e:
        logger.debug(f"Could not check pending inputs for build #{build_number}: {e}")

    # 2. Verifica se o build terminou
    build_info = await jenkins.get_build_info(job_path, build_number)

    if not build_info.building and build_info.result:
        # Build finalizado — mapeia resultado Jenkins para status interno
        result_map = {
            "SUCCESS": ExecutionStatus.SUCCESS,
            "FAILURE": ExecutionStatus.FAILURE,
            "ABORTED": ExecutionStatus.ABORTED,
            "UNSTABLE": ExecutionStatus.FAILURE,
        }
        new_status = result_map.get(build_info.result, ExecutionStatus.FAILURE)
        step.status = new_status
        step.message = f"Jenkins result: {build_info.result}"
        session.add(step)
        logger.info(
            f"Step {step.step_id} (build #{build_number}): "
            f"finished with result={build_info.result} → status={new_status.value}"
        )
        return True

    return False
