"""
Utilitário para resolver o job path do Jenkins.

Regra de prioridade:
1. Se o step define `job.path` explicitamente, usa o valor informado.
2. Senão, busca na tabela job_path_registry pelo (repository + environment).
3. Se não encontrar na tabela, retorna None (não gera mais path automático).

ENVIRONMENT vem de `spec.environment` (default: "PRD").
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from maestro.database.models import JobPathRegistry
from maestro.schemas.orchestrator import ReleaseSpecSchema, StepSchema


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
    step: StepSchema, spec: ReleaseSpecSchema, session: AsyncSession
) -> str:
    """
    Resolve o job path efetivo para um step com consulta ao registry.

    Prioridade:
    1. job.path explícito no YAML → usa diretamente.
    2. Busca na tabela job_path_registry por (repository + environment).
    3. Fallback: gera path padrão job/<ENV>/job/<repo>/job/<repo>.

    :param step: Definição do step no YAML.
    :param spec: Spec da release (contém environment).
    :param session: AsyncSession do SQLAlchemy para consulta ao banco.
    :return: O path do job no Jenkins.
    """
    # 1. Path explícito no YAML sempre prevalece
    if step.job and step.job.path:
        return step.job.path

    environment = spec.environment or "PRD"
    repository = step.repository

    # 2. Busca na tabela job_path_registry
    result = await session.execute(
        select(JobPathRegistry).where(
            JobPathRegistry.repository == repository,
            JobPathRegistry.environment == environment,
        )
    )
    registry_entry = result.scalars().first()

    if registry_entry:
        return registry_entry.path

    # 3. Fallback: gera path padrão
    return f"job/{environment}/job/{repository}/job/{repository}"
