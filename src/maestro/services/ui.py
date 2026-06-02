import asyncio
import json
from pathlib import Path
from fastapi import Depends
from jinja2 import Environment, FileSystemLoader
from maestro.repositories.execution import ExecutionRepository
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.schemas.enums import ExecutionStatus
from maestro.database.models import ReleaseExecution, ReleaseStepExecution
from maestro.config.logger import get_logger
import yaml
from typing import AsyncGenerator

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "ui" / "templates"

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

TERMINAL_STATUSES = {
    ExecutionStatus.SUCCESS,
    ExecutionStatus.FAILURE,
    ExecutionStatus.ERROR,
    ExecutionStatus.ABORTED,
}


class UIService:
    def __init__(
        self,
        execution_repo: ExecutionRepository = Depends(),
        orchestrator_repo: OrchestratorDescriptorRepository = Depends(),
    ):
        self.execution_repo = execution_repo
        self.orchestrator_repo = orchestrator_repo

    async def get_all_executions(self) -> list[ReleaseExecution]:
        return await self.execution_repo.get_all_executions()

    async def get_execution_with_stages(self, execution_id: int) -> tuple[ReleaseExecution, list, list] | None:
        """Retorna a execução, a lista de stages e o histórico de ações para renderização."""
        execution = await self.execution_repo.get_execution_by_id(execution_id)
        if not execution:
            return None

        stages = await self._build_stages_view(execution)
        action_logs = await self.execution_repo.get_action_logs_by_execution_id(execution_id)
        return execution, stages, action_logs

    async def execution_sse_stream(self, execution_id: int) -> AsyncGenerator[dict, None]:
        """
        Gerador assíncrono para SSE: emite eventos com HTML renderizado
        sempre que o estado dos steps mudar. Encerra quando a execução termina.
        """
        last_snapshot = None

        while True:
            try:
                from maestro.database.session import AsyncSessionLocal
                from maestro.repositories.settings import UISettingsRepository
                from maestro.services.settings import SETTING_JENKINS_BASE_URL, SETTING_GITHUB_BASE_URL, SETTING_GITHUB_ORGANIZATION

                async with AsyncSessionLocal() as session:
                    exec_repo = ExecutionRepository(db=session)
                    orch_repo = OrchestratorDescriptorRepository(db=session)
                    settings_repo = UISettingsRepository(db=session)
                    scoped_service = UIService(exec_repo, orch_repo)

                    result = await scoped_service.get_execution_with_stages(execution_id)
                    if not result:
                        break

                    execution, stages, action_logs = result
                    jenkins_base_url = (await settings_repo.get(SETTING_JENKINS_BASE_URL) or "").rstrip("/")
                    github_base_url = (await settings_repo.get(SETTING_GITHUB_BASE_URL) or "").rstrip("/")
                    github_organization = await settings_repo.get(SETTING_GITHUB_ORGANIZATION) or ""

                snapshot = _build_snapshot(stages, execution.status, len(action_logs))

                if snapshot != last_snapshot:
                    last_snapshot = snapshot
                    
                    stages_html = _render_partial(
                        "partials/stages.html",
                        stages=stages,
                        jenkins_base_url=jenkins_base_url,
                        github_base_url=github_base_url,
                        github_organization=github_organization,
                    )
                    
                    oob_html = _render_partial(
                        "partials/execution_oob.html",
                        execution=execution,
                        waiting_approval=(execution.status == ExecutionStatus.WAITING_APPROVAL)
                    )

                    log_html = _render_partial(
                        "partials/action_log.html",
                        action_logs=action_logs,
                    )
                    
                    html = stages_html + "\n" + oob_html + "\n" + log_html
                    yield {"event": "stage-update", "data": html}

                    if execution.status in TERMINAL_STATUSES:
                        break

            except asyncio.CancelledError:
                # Cliente desconectou — encerra limpo
                logger.info(f"SSE client disconnected for execution {execution_id}")
                break
            except Exception as e:
                logger.error(f"SSE error for execution {execution_id}: {e}")
                break

            await asyncio.sleep(2)

    async def _build_stages_view(self, execution: ReleaseExecution) -> list:
        descriptor = await self.orchestrator_repo.get_by_id(execution.orchestrator_descriptor_id)
        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
        steps = await self.execution_repo.get_steps_by_execution_id(execution.id)
        return _assemble_stages(config, steps)


# --- Funções puras auxiliares (sem estado, sem dependências) ---

def _assemble_stages(config: ReleaseConfigSchema, steps: list[ReleaseStepExecution]) -> list:
    """Combina a definição do YAML com os dados de execução do banco."""
    step_map = {(se.stage_id, se.step_id): se for se in steps}
    # índice da definição do YAML para enriquecer com metadados
    step_def_map = {
        (stage.id, step.id): step
        for stage in config.spec.stages
        for step in stage.steps
    }

    result = []
    for stage in config.spec.stages:
        enriched_steps = []
        for step_def in stage.steps:
            key = (stage.id, step_def.id)
            if key not in step_map:
                continue
            execution_step = step_map[key]
            enriched_steps.append({
                "execution": execution_step,
                "repository": step_def.repository,
                "release": step_def.release,
                "job_type": step_def.job.type,
                "job_path": step_def.job.path,
            })
        result.append({"id": stage.id, "steps": enriched_steps})
    return result


def _build_snapshot(stages: list, execution_status: str, log_count: int = 0) -> str:
    """Gera uma string compacta do estado atual para detectar mudanças."""
    return json.dumps(
        {
            "status": str(execution_status),
            "log_count": log_count,
            "stages": [
            {
                "stage": s["id"],
                "steps": [
                    {"id": st["execution"].step_id, "status": st["execution"].status}
                    for st in s["steps"]
                ],
            }
            for s in stages
        ]},
        default=str,
    )


def _render_partial(template_name: str, **context) -> str:
    """Renderiza um template Jinja2 e retorna o HTML como string."""
    return _jinja_env.get_template(template_name).render(**context)
