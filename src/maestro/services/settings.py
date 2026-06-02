from fastapi import Depends
from maestro.repositories.settings import UISettingsRepository

# Chaves conhecidas de configuração
SETTING_JENKINS_BASE_URL = "jenkins_base_url"
SETTING_GITHUB_BASE_URL = "github_base_url"
SETTING_GITHUB_ORGANIZATION = "github_organization"
SETTING_STEP_TIMEOUT_MINUTES = "step_timeout_minutes"

KNOWN_SETTINGS = {
    SETTING_JENKINS_BASE_URL: {
        "label": "URL base do Jenkins",
        "placeholder": "https://jenkins.exemplo.com",
        "help": "Usado para montar links diretos para os builds nos detalhes de execução.",
    },
    SETTING_GITHUB_BASE_URL: {
        "label": "URL base do GitHub",
        "placeholder": "https://github.com",
        "help": "URL base da instância GitHub (ou GitHub Enterprise).",
    },
    SETTING_GITHUB_ORGANIZATION: {
        "label": "Organização do GitHub",
        "placeholder": "minha-org",
        "help": "Nome da organização usada para montar links de repositório.",
    },
    SETTING_STEP_TIMEOUT_MINUTES: {
        "label": "Timeout global de steps (minutos)",
        "placeholder": "60",
        "help": "Tempo máximo (em minutos) que um step pode ficar em execução antes de ser marcado como timeout. Pode ser sobrescrito por step no YAML.",
    },
}


class UISettingsService:
    def __init__(self, repo: UISettingsRepository = Depends()):
        self.repo = repo

    async def get_all(self) -> dict[str, str | None]:
        """Retorna todas as configurações salvas, preenchendo None para as não salvas."""
        saved = await self.repo.get_all()
        return {key: saved.get(key) for key in KNOWN_SETTINGS}

    async def get(self, key: str) -> str | None:
        return await self.repo.get(key)

    async def save(self, settings: dict[str, str | None]) -> None:
        # Filtra apenas chaves conhecidas para evitar lixo no banco
        filtered = {k: v for k, v in settings.items() if k in KNOWN_SETTINGS}
        await self.repo.upsert_many(filtered)
