from fastapi import Depends

from maestro.config.crypto import decrypt_value, encrypt_value
from maestro.repositories.settings import UISettingsRepository

# Chaves conhecidas de configuração
SETTING_JENKINS_BASE_URL = "jenkins_base_url"
SETTING_JENKINS_USERNAME = "jenkins_username"
SETTING_JENKINS_TOKEN = "jenkins_token"
SETTING_GITHUB_BASE_URL = "github_base_url"
SETTING_GITHUB_ORGANIZATION = "github_organization"
SETTING_GITHUB_TOKEN = "github_token"
SETTING_STEP_TIMEOUT_MINUTES = "step_timeout_minutes"
SETTING_HTTP_TRUST_ENV = "http_trust_env"
SETTING_BUILD_POLL_INTERVAL_SECONDS = "build_poll_interval_seconds"

# Chaves que contêm dados sensíveis (serão criptografadas no banco e mascaradas na UI)
SENSITIVE_SETTINGS = {SETTING_JENKINS_TOKEN, SETTING_GITHUB_TOKEN}

KNOWN_SETTINGS = {
    SETTING_JENKINS_BASE_URL: {
        "label": "URL base do Jenkins",
        "placeholder": "https://jenkins.exemplo.com",
        "help": "URL base da instância Jenkins usada para disparar jobs e montar links.",
        "sensitive": False,
    },
    SETTING_JENKINS_USERNAME: {
        "label": "Usuário do Jenkins",
        "placeholder": "seu_usuario",
        "help": "Usuário para autenticação na API do Jenkins.",
        "sensitive": False,
    },
    SETTING_JENKINS_TOKEN: {
        "label": "Token do Jenkins",
        "placeholder": "token_jenkins",
        "help": "Token de API para autenticação no Jenkins. Armazenado com criptografia.",
        "sensitive": True,
    },
    SETTING_GITHUB_BASE_URL: {
        "label": "URL base do GitHub",
        "placeholder": "https://github.com",
        "help": "URL base da instância GitHub (ou GitHub Enterprise).",
        "sensitive": False,
    },
    SETTING_GITHUB_ORGANIZATION: {
        "label": "Organização do GitHub",
        "placeholder": "minha-org",
        "help": "Nome da organização usada para montar links de repositório e chamadas à API.",
        "sensitive": False,
    },
    SETTING_GITHUB_TOKEN: {
        "label": "Token do GitHub",
        "placeholder": "ghp_xxx",
        "help": "Token de acesso pessoal (PAT) do GitHub. Armazenado com criptografia.",
        "sensitive": True,
    },
    SETTING_STEP_TIMEOUT_MINUTES: {
        "label": "Timeout global de steps (minutos)",
        "placeholder": "60",
        "help": (
            "Tempo máximo (em minutos) que um step pode ficar em execução antes de ser "
            "marcado como timeout. Pode ser sobrescrito por step no YAML."
        ),
        "sensitive": False,
    },
    SETTING_HTTP_TRUST_ENV: {
        "label": "HTTP Trust Env (proxy/certs do sistema)",
        "placeholder": "true",
        "help": (
            "Quando habilitado (true), o httpx respeita variáveis de ambiente como "
            "HTTP_PROXY, HTTPS_PROXY, NO_PROXY e SSL_CERT_FILE. Valores aceitos: true ou false."
        ),
        "sensitive": False,
        "type": "toggle",
    },
    SETTING_BUILD_POLL_INTERVAL_SECONDS: {
        "label": "Intervalo de polling dos builds (segundos)",
        "placeholder": "10",
        "help": (
            "Frequência (em segundos) com que o Maestro consulta o Jenkins para verificar "
            "o status dos builds em andamento. Padrão: 10 segundos."
        ),
        "sensitive": False,
    },
}


class UISettingsService:
    def __init__(self, repo: UISettingsRepository = Depends()):
        self.repo = repo

    async def get_all(self) -> dict[str, str | None]:
        """Retorna todas as configurações salvas, descriptografando dados sensíveis."""
        saved = await self.repo.get_all()
        result = {}
        for key in KNOWN_SETTINGS:
            raw_value = saved.get(key)
            if raw_value and key in SENSITIVE_SETTINGS:
                result[key] = decrypt_value(raw_value)
            else:
                result[key] = raw_value
        return result

    async def get_all_masked(self) -> dict[str, str | None]:
        """Retorna configurações com dados sensíveis mascarados para exibição na UI."""
        saved = await self.repo.get_all()
        result = {}
        for key in KNOWN_SETTINGS:
            raw_value = saved.get(key)
            if raw_value and key in SENSITIVE_SETTINGS:
                decrypted = decrypt_value(raw_value)
                if decrypted and len(decrypted) > 4:
                    result[key] = "*" * (len(decrypted) - 4) + decrypted[-4:]
                elif decrypted:
                    result[key] = "****"
                else:
                    result[key] = None
            else:
                result[key] = raw_value
        return result

    async def get(self, key: str) -> str | None:
        """Retorna um valor descriptografado se necessário."""
        raw_value = await self.repo.get(key)
        if raw_value and key in SENSITIVE_SETTINGS:
            return decrypt_value(raw_value)
        return raw_value

    async def save(self, settings: dict[str, str | None]) -> None:
        """Salva configurações, criptografando dados sensíveis."""
        filtered = {}
        for k, v in settings.items():
            if k not in KNOWN_SETTINGS:
                continue
            if v and k in SENSITIVE_SETTINGS:
                # Se o valor veio mascarado (só asteriscos + 4 chars), não sobrescrever
                if v and v.startswith("*"):
                    continue
                filtered[k] = encrypt_value(v)
            else:
                filtered[k] = v
        await self.repo.upsert_many(filtered)
