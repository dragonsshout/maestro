"""
Utilitário para resolver o job path do Jenkins.

Regra de prioridade:
1. Se o step define `job.path` explicitamente, usa o valor informado.
2. Senão, busca na tabela job_path_registry pelo (repository + environment).
3. Se não encontrar na tabela, fallback para o padrão gerado automaticamente.

ENVIRONMENT vem de `spec.environment` (default: "PRD").

O fallback gera um path compatível com a estrutura de folders do Jenkins:
- Cada segmento do path (environment, partes do repositório) é separado por "/job/".
- Repositório simples: "api-teste" → job/PRD/job/api-teste/job/api-teste
- Repositório com org: "plataforma-digital/api-frotista-planos"
  → job/PRD/job/plataforma-digital/job/api-frotista-planos/job/api-frotista-planos
"""

from maestro.config.logger import get_logger
from maestro.repositories.job_path_registry import JobPathRegistryRepository
from maestro.schemas.orchestrator import ReleaseSpecSchema, StepSchema

logger = get_logger(__name__)


def _build_fallback_path(environment: str, repository: str) -> str:
    """
    Gera o path fallback para o Jenkins baseado no environment e repository.

    Cada segmento (environment, partes do repositório separadas por '/')
    é transformado em '/job/<segmento>'. O último segmento do repositório
    é repetido como nome do job final.

    Exemplos:
    - environment="PRD", repository="api-teste"
      → "job/PRD/job/api-teste/job/api-teste"
    - environment="PRD", repository="plataforma-digital/api-frotista-planos"
      → "job/PRD/job/plataforma-digital/job/api-frotista-planos/job/api-frotista-planos"
    """
    # Segmentos do repositório (ex: ["plataforma-digital", "api-frotista-planos"])
    repo_parts = [p for p in repository.split("/") if p]

    # Nome do job final é o último segmento do repositório
    job_name = repo_parts[-1] if repo_parts else repository

    # Monta: job/<ENV>/job/<part1>/job/<part2>/.../job/<job_name>
    segments = [environment] + repo_parts + [job_name]
    return "/".join(f"job/{seg}" for seg in segments)


def resolve_job_path(step: StepSchema, spec: ReleaseSpecSchema) -> str:
    """
    Resolve o job path efetivo para um step (versão síncrona/legado).

    Mantida para compatibilidade. Retorna o path explícito ou um fallback baseado
    no padrão gerado. Para resolução completa com registry, usar resolve_job_path_async.

    :param step: Definição do step no YAML.
    :param spec: Spec da release (contém environment).
    :return: O path do job no Jenkins.
    """
    # Se o job foi informado com path explícito, usa o valor
    if step.job and step.job.path:
        return step.job.path

    # Fallback legado (será substituído por resolve_job_path_async nos fluxos que usam DB)
    environment = spec.environment or "PRD"
    return _build_fallback_path(environment, step.repository)


async def resolve_job_path_async(
    step: StepSchema, spec: ReleaseSpecSchema, registry_repo: JobPathRegistryRepository
) -> str:
    """
    Resolve o job path efetivo para um step com consulta ao registry via repository.

    Prioridade:
    1. job.path explícito no YAML → usa diretamente.
    2. Busca na tabela job_path_registry por (repository + environment).
    3. Fallback: gera path padrão com _build_fallback_path.

    :param step: Definição do step no YAML.
    :param spec: Spec da release (contém environment).
    :param registry_repo: Instância do JobPathRegistryRepository para consulta ao banco.
    :return: O path do job no Jenkins.
    """
    # 1. Path explícito no YAML sempre prevalece
    if step.job and step.job.path:
        logger.debug(f"[job_path_resolver] Usando path explícito do YAML: {step.job.path}")
        return step.job.path

    environment = spec.environment or "PRD"
    repository = step.repository

    # 2. Busca no registry via repository
    registry_entry = await registry_repo.get_by_repository_and_environment(repository, environment)

    if registry_entry:
        logger.debug(
            f"[job_path_resolver] Path encontrado no registry para "
            f"'{repository}' / '{environment}': {registry_entry.path}"
        )
        return registry_entry.path

    # 3. Fallback: gera path padrão
    fallback = _build_fallback_path(environment, repository)
    logger.warning(
        f"[job_path_resolver] Nenhum path explícito ou registro encontrado para "
        f"'{repository}' / '{environment}'. Usando fallback: {fallback}"
    )
    return fallback
