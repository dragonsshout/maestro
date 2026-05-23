from unicodedata import name
from fastapi import Depends
from maestro.database.models import OrchestratorDescriptor, ReleaseExecution, ReleaseStepExecution
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.repositories.execution import ExecutionRepository
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.config.settings import settings
from maestro.integration.github import GithubIntegration
from pydantic import ValidationError
import yaml
import uuid
from sqlalchemy.exc import IntegrityError

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

    async def execute_release(self, name: str) -> int:
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

        for stage in config.spec.stages:
            for step in stage.steps:
                step_execution = ReleaseStepExecution(
                    release_execution_id=release_execution.id,
                    stage_id=stage.id,
                    step_id=step.id,
                    status="pending"
                )
                await self.execution_repo.add_step_execution(step_execution)
        
        return release_execution.id
