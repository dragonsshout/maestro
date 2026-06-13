from typing import List

from maestro.config.logger import get_logger
from maestro.integration.github import GithubIntegration
from maestro.integration.jenkins import JenkinsIntegration
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.services.app_settings import get_integration_settings
from maestro.services.job_path_resolver import resolve_job_path

logger = get_logger(__name__)


class ReleaseValidationService:
    """
    Serviço responsável por validar a existência de repositórios no GitHub
    e jobs no Jenkins antes de salvar um descritor de release.

    NÃO valida branches — apenas path do Jenkins e se o repositório existe no GitHub.
    """

    async def _init_integrations(self, session=None):
        """Inicializa integrações com credenciais do banco (fallback .env já resolvido)."""
        cfg = await get_integration_settings(session)
        self.github = GithubIntegration(
            organization=cfg.github_organization,
            token=cfg.github_token,
            base_url=cfg.github_base_url,
            trust_env=cfg.http_trust_env,
        )
        self.jenkins = JenkinsIntegration(
            base_url=cfg.jenkins_url,
            username=cfg.jenkins_username,
            token=cfg.jenkins_token,
            trust_env=cfg.http_trust_env,
        )

    async def validate(self, config: ReleaseConfigSchema, session=None) -> None:
        """
        Valida repositórios (GitHub) e jobs (Jenkins) definidos no YAML de release.
        NÃO valida se a branch existe.
        Coleta todos os erros encontrados e lança um ValueError com a lista completa.

        :param config: Schema validado do YAML de release.
        :raises ValueError: Se houver repositórios inexistentes ou jobs inválidos.
        """
        await self._init_integrations(session)
        errors: List[str] = []

        # Coleta repositórios únicos para evitar chamadas duplicadas
        checked_repos: dict[str, bool] = {}

        for stage in config.spec.stages:
            for step in stage.steps:
                # Validação do repositório no GitHub (verifica se o repo existe)
                if step.repository not in checked_repos:
                    repo_exists = await self._check_repository(step.repository)
                    checked_repos[step.repository] = repo_exists

                if not checked_repos[step.repository]:
                    errors.append(
                        f"Repositório '{step.repository}' não encontrado no GitHub "
                        f"(stage: '{stage.id}', step: '{step.id}')"
                    )

                # Validação do job no Jenkins
                job_type = step.job.type if step.job else "jenkins"
                if job_type == "jenkins":
                    job_path = resolve_job_path(step, config.spec)
                    job_exists = await self._check_jenkins_job(job_path)
                    if not job_exists:
                        errors.append(
                            f"Job '{job_path}' não encontrado no Jenkins (stage: '{stage.id}', step: '{step.id}')"
                        )

        if errors:
            error_message = "Erro de validação na configuração de release:\n" + "\n".join(
                f"  - {error}" for error in errors
            )
            raise ValueError(error_message)

    async def _check_repository(self, repository: str) -> bool:
        """Verifica se o repositório existe no GitHub (usa a API de repos)."""
        try:
            return await self.github.repository_exists(repository)
        except Exception as e:
            logger.warning(f"Erro ao verificar repositório '{repository}': {e}")
            return False

    async def _check_jenkins_job(self, job_path: str) -> bool:
        """Verifica se o job existe no Jenkins."""
        try:
            return await self.jenkins.job_exists(job_path)
        except Exception as e:
            logger.warning(f"Erro ao verificar job '{job_path}' no Jenkins: {e}")
            return False
