"""
Utilitário para resolver o job path do Jenkins.

Regra de prioridade:
1. Se o step define `job.path` explicitamente, usa o valor informado.
2. Senão, busca na tabela job_path_registry pelo (repository + environment).
3. Se não encontrar na tabela, fallback para o padrão job/<ENV>/job/<repo>/job/<repo>.

ENVIRONMENT vem de `spec.environment` (default: "PRD").
"""

from dataclasses import dataclass

from maestro.repositories.job_path_registry import JobPathRegistryRepository
from maestro.schemas.orchestrator import ReleaseSpecSchema, StepSchema


@dataclass
class ResolvedJobPath:
    """Resultado da resolução de um job path com metadados sobre a origem."""

    path: str
    source: str  # "explicit" | "registry" | "auto"



def resolve_job_path(step: StepSchema, spec: ReleaseSpecSchema) -> str:
    """
    Resolve o job path efetivo para um step (versão síncrona/legado).

    Mantida para compatibilidade. Retorna o path explícito ou um fallback baseado
    no padrão antigo caso não haja acesso ao banco. Para resolução completa com
    registry, usar resolve_job_path_async.

    :param step: Definição do step no YAML.
    :param spec: Spec da release (contém environment).
    :return: O path do job no Jenkins.
    """
    # Se o job foi informado com path explícito, usa o valor
    if step.job and step.job.path:
        return step.job.path

    # Fallback legado (será substituído por resolve_job_path_async nos fluxos que usam DB)
    environment = spec.environment or "PRD"
    repository = step.repository

    return f"job/{environment}/job/{repository}/job/{repository}"


async def resolve_job_path_async(
    step: StepSchema, spec: ReleaseSpecSchema, registry_repo: JobPathRegistryRepository
) -> str:
    """
    Resolve o job path efetivo para um step com consulta ao registry via repository.

    Prioridade:
    1. job.path explícito no YAML → usa diretamente.
    2. Busca na tabela job_path_registry por (repository + environment).
    3. Fallback: gera path padrão job/<ENV>/job/<repo>/job/<repo>.

    :param step: Definição do step no YAML.
    :param spec: Spec da release (contém environment).
    :param registry_repo: Instância do JobPathRegistryRepository para consulta ao banco.
    :return: O path do job no Jenkins.
    """
    # 1. Path explícito no YAML sempre prevalece
    if step.job and step.job.path:
        return step.job.path

    environment = spec.environment or "PRD"
    repository = step.repository

    # 2. Busca no registry via repository
    registry_entry = await registry_repo.get_by_repository_and_environment(repository, environment)

    if registry_entry:
        return registry_entry.path

    # 3. Fallback: gera path padrão
    return f"job/{environment}/job/{repository}/job/{repository}"


async def resolve_job_path_by_repository(
    repository: str,
    environment: str,
    registry_repo: JobPathRegistryRepository,
) -> ResolvedJobPath:
    """
    Resolve o job path apenas com repositório e ambiente, sem precisar do StepSchema.

    Útil quando não existe ainda um step YAML definido (ex: Release Builder, validações
    inline de UI) e só se quer saber qual path será efetivamente usado.

    Prioridade:
    1. Busca na tabela job_path_registry por (repository + environment).
    2. Fallback: gera path padrão job/<ENV>/job/<repo>/job/<repo>.

    :param repository: Nome do repositório.
    :param environment: Ambiente (ex: 'PRD', 'DEV').
    :param registry_repo: Instância do JobPathRegistryRepository.
    :return: ResolvedJobPath com o path resolvido e a origem ('registry' | 'auto').
    """
    env = environment.upper()

    registry_entry = await registry_repo.get_by_repository_and_environment(repository, env)
    if registry_entry:
        return ResolvedJobPath(path=registry_entry.path, source="registry")

    return ResolvedJobPath(
        path=f"job/{env}/job/{repository}/job/{repository}",
        source="auto",
    )
