from typing import List
from maestro.integration.github import GithubIntegration
from maestro.integration.jenkins import JenkinsIntegration
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.config.settings import settings
from maestro.config.logger import get_logger

logger = get_logger(__name__)


class ReleaseValidationService:
    """
    Serviço responsável por validar a existência de branches no GitHub
    e jobs no Jenkins antes de salvar um descritor de release.
    """

    def __init__(self):
        self.github = GithubIntegration(
            organization=settings.github_organization,
            token=settings.github_token
        )
        self.jenkins = JenkinsIntegration(
            base_url=settings.jenkins_url,
            username=settings.jenkins_username,
            token=settings.jenkins_token
        )

    async def validate(self, config: ReleaseConfigSchema) -> None:
        """
        Valida todas as branches e jobs definidos no YAML de release.
        Coleta todos os erros encontrados e lança um ValueError com a lista completa.

        :param config: Schema validado do YAML de release.
        :raises ValueError: Se houver branches inexistentes ou jobs inválidos.
        """
        errors: List[str] = []

        for stage in config.spec.stages:
            for step in stage.steps:
                # Validação da branch no GitHub
                branch_exists = await self._check_branch(step.repository, step.release)
                if not branch_exists:
                    errors.append(
                        f"Branch '{step.release}' não encontrada no repositório '{step.repository}' "
                        f"(stage: '{stage.id}', step: '{step.id}')"
                    )

                # Validação do job no Jenkins
                if step.job.type == "jenkins":
                    job_exists = await self._check_jenkins_job(step.job.path)
                    if not job_exists:
                        errors.append(
                            f"Job '{step.job.path}' não encontrado no Jenkins "
                            f"(stage: '{stage.id}', step: '{step.id}')"
                        )

        if errors:
            error_message = "Erro de validação na configuração de release:\n" + "\n".join(
                f"  - {error}" for error in errors
            )
            raise ValueError(error_message)

    async def _check_branch(self, repository: str, branch: str) -> bool:
        """Verifica se a branch existe no repositório GitHub."""
        try:
            return await self.github.branch_exists(repository, branch)
        except Exception as e:
            logger.warning(f"Erro ao verificar branch '{branch}' no repositório '{repository}': {e}")
            return False

    async def _check_jenkins_job(self, job_path: str) -> bool:
        """Verifica se o job existe no Jenkins."""
        try:
            return await self.jenkins.job_exists(job_path)
        except Exception as e:
            logger.warning(f"Erro ao verificar job '{job_path}' no Jenkins: {e}")
            return False
