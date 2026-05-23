from fastapi import Depends
from maestro.database.models import OrchestratorDescriptor
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.schemas.orchestrator import ReleaseConfigSchema
from pydantic import ValidationError
import yaml

class OrchestratorService:
    def __init__(self, repository: OrchestratorDescriptorRepository = Depends()):
        self.repository = repository

    async def save_descriptor(self, yaml_content: str) -> OrchestratorDescriptor:
        try:
            # Validação do formato YAML
            parsed_yaml = yaml.safe_load(yaml_content)

            # Validação do Schema Pydantic
            ReleaseConfigSchema(**parsed_yaml)

        except (yaml.YAMLError, ValidationError) as e:
            raise ValueError(f"Erro de validação na estrutura do YAML:\n{e}")

        descriptor = OrchestratorDescriptor(yaml=yaml_content)
        return await self.repository.add(descriptor)
