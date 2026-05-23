from unicodedata import name
from fastapi import Depends
from maestro.database.models import OrchestratorDescriptor, ReleaseStepExecution
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.repositories.execution import ReleaseStepExecutionRepository
from maestro.schemas.orchestrator import ReleaseConfigSchema
from pydantic import ValidationError
import yaml
import uuid
from sqlalchemy.exc import IntegrityError

class OrchestratorService:
    def __init__(
        self, 
        repository: OrchestratorDescriptorRepository = Depends(),
        execution_repo: ReleaseStepExecutionRepository = Depends()
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

    async def execute_release(self, name: str) -> str:
        descriptor = await self.repository.get_by_name(name)
        if not descriptor:
            raise ValueError(f"Descritor com nome '{name}' não encontrado.")

        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
        release_process_id = str(uuid.uuid4())

        for stage in config.spec.stages:
            for step in stage.steps:
                execution = ReleaseStepExecution(
                    name=step.id,
                    release_process_id=release_process_id,
                    stage_id=stage.id,
                    step_id=step.id,
                    status="pending"
                )
                await self.execution_repo.add(execution)
        
        return release_process_id
