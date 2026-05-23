from unicodedata import name
from fastapi import Depends, BackgroundTasks
from maestro.database.models import OrchestratorDescriptor, ReleaseExecution, ReleaseStepExecution
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.repositories.execution import ExecutionRepository
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.config.settings import settings
from maestro.integration.github import GithubIntegration
from maestro.integration.jenkins import JenkinsIntegration
from pydantic import ValidationError
import yaml
import uuid
from sqlalchemy.exc import IntegrityError
from maestro.config.logger import get_logger

logger = get_logger(__name__)

class OrchestratorService:
    def __init__(
        self, 
        repository: OrchestratorDescriptorRepository = Depends(),
        execution_repo: ExecutionRepository = Depends()
    ):
        self.repository = repository
        self.execution_repo = execution_repo

    async def save_descriptor(self, yaml_content: str) -> OrchestratorDescriptor:
        # Validação do formato YAML
        try:
            parsed_yaml = yaml.safe_load(yaml_content)

            # Validação do Schema Pydantic
            release_config = ReleaseConfigSchema(**parsed_yaml)

        except (yaml.YAMLError, ValidationError) as e:
            raise ValueError(f"Erro de validação na estrutura do YAML:\n{e}")

        descriptor = OrchestratorDescriptor(
            name=release_config.metadata.name,
            yaml=yaml_content
        )

        try:
            return await self.repository.add(descriptor)
        except IntegrityError:
            raise ValueError(f"Já existe uma configuração de release com o nome '{release_config.metadata.name}'.")

    async def execute_release(self, name: str, background_tasks: BackgroundTasks) -> int:
        descriptor = await self.repository.get_by_name(name)
        if not descriptor:
            raise ValueError(f"Descritor com nome '{name}' não encontrado.")

        if await self.execution_repo.exists_by_name(name):
            raise ValueError(f"Já existe uma execução registrada para a release '{name}'.")

        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))

        release_execution = ReleaseExecution(
            name=name,
            status="pending",
            orchestrator_descriptor_id=descriptor.id
        )
        release_execution = await self.execution_repo.add_release_execution(release_execution)

        github = GithubIntegration(organization=settings.github_organization, token=settings.github_token)
        try:
            for stage in config.spec.stages:
                for step in stage.steps:
                    pr = await github.get_pull_request_by_branch(step.repository, step.release)
                    if not pr:
                        raise ValueError(f"Pull Request não encontrado para a branch '{step.release}' no repositório '{step.repository}'.")
                    
                    pr_detail = await github.get_pull_request_details(step.repository, pr.number)
                    if pr_detail.mergeable_state != "clean":
                        raise ValueError(f"O Pull Request para a branch '{step.release}' no repositório '{step.repository}' não está no estado 'clean' (estado atual: '{pr_detail.mergeable_state}').")

        except Exception as e:
            release_execution.status = "failure"
            release_execution.message = str(e)

            # atualiza dados da falha
            await self.execution_repo.update_release_execution(release_execution)

            raise e

        # cria os steps para cada stage
        for stage in config.spec.stages:
            for step in stage.steps:
                step_execution = ReleaseStepExecution(
                    release_execution_id=release_execution.id,
                    stage_id=stage.id,
                    step_id=step.id,
                    status="pending"
                )
                await self.execution_repo.add_step_execution(step_execution)

        background_tasks.add_task(self.process_workflow, release_execution.id)
        return release_execution.id

    async def process_workflow(self, execution_id: int):
        execution = await self.execution_repo.get_execution_by_id(execution_id)
        if not execution:
            logger.warning(f"Execução {execution_id} não encontrada.")
            return

        if execution.status in ["success", "failure"]:
            return

        descriptor = await self.repository.get_by_id(execution.orchestrator_descriptor_id)
        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
        steps_exec = await self.execution_repo.get_steps_by_execution_id(execution_id)
        
        # Mapear as execuções de step
        step_exec_map = {(se.stage_id, se.step_id): se for se in steps_exec}

        execution_in_progress = False
        execution_failed = False

        for stage in config.spec.stages:
            stage_status = "success"
            for step in stage.steps:
                se = step_exec_map.get((stage.id, step.id))
                if not se: continue

                if se.status == "failure":
                    stage_status = "failure"
                    execution_failed = True
                    break
                elif se.status == "in_progress":
                    stage_status = "in_progress"
                    execution_in_progress = True
                elif se.status == "pending":
                    # Mark as in progress and trigger job
                    se.status = "in_progress"
                    await self.execution_repo.update_step_execution(se)
                    
                    if step.job.type == "jenkins":
                        logger.info(f"Acionando job do tipo {step.job.type} no caminho {step.job.path} para o step {step.id}")
                        jenkins = JenkinsIntegration(
                            base_url=settings.jenkins_url,
                            username=settings.jenkins_username,
                            token=settings.jenkins_token
                        )
                        # O jenkins deve chamar o webhook passando estes parâmetros de volta
                        params = {
                            "release_process_id": str(execution_id),
                            "stage_id": stage.id,
                            "step_id": step.id
                        }
                        try:
                            # Dispara o job sem esperar (fire and forget). A continuação será via webhook.
                            await jenkins.build_job(step.job.path, parameters=params, fire_and_forget=True)
                        except Exception as e:
                            logger.error(f"Erro ao acionar o Jenkins para {step.job.path}: {e}")
                            se.status = "failure"
                            se.message = str(e)
                            await self.execution_repo.update_step_execution(se)
                            stage_status = "failure"
                            execution_failed = True
                            continue
                            
                    else:
                        logger.warning(f"Job type não suportado ainda: {step.job.type}")
                        # Simulando que terminou rápido
                        se.status = "success"
                        await self.execution_repo.update_step_execution(se)
                        continue

                    # Como depende de webhook (ou job falhou acima), atualizamos o status geral
                    if se.status == "in_progress":
                        stage_status = "in_progress"
                        execution_in_progress = True

            if stage_status == "failure":
                execution.status = "failure"
                await self.execution_repo.update_release_execution(execution)
                return
            elif stage_status == "in_progress":
                # Waiting for steps to complete, cannot proceed to next stage
                return

        if not execution_in_progress and not execution_failed:
            execution.status = "success"
            await self.execution_repo.update_release_execution(execution)
