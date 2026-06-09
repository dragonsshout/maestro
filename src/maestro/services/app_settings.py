"""
Módulo centralizador para obter configurações de integração do banco de dados.
Substitui o uso direto de config/settings.py para Jenkins/GitHub, usando o banco como source of truth.
Caso o valor não exista no banco, faz fallback para o .env.
"""

from typing import Optional

from pydantic import BaseModel

from maestro.config.settings import settings as env_settings
from maestro.config.crypto import decrypt_value


class IntegrationSettings(BaseModel):
    """Modelo Pydantic com as configurações de integração resolvidas (banco + fallback .env)."""

    jenkins_url: Optional[str] = None
    jenkins_username: Optional[str] = None
    jenkins_token: Optional[str] = None
    github_base_url: Optional[str] = None
    github_organization: Optional[str] = None
    github_token: Optional[str] = None
    step_timeout_minutes: Optional[str] = None


async def get_integration_settings(session=None) -> IntegrationSettings:
    """
    Obtém todas as configurações de integração do banco.
    Faz fallback para variáveis de ambiente (.env) caso não haja valor no banco.

    :param session: AsyncSession do SQLAlchemy. Se None, cria uma nova.
    :returns: IntegrationSettings com os valores resolvidos.
    """
    from maestro.database.session import AsyncSessionLocal
    from maestro.repositories.settings import UISettingsRepository
    from maestro.services.settings import SENSITIVE_SETTINGS

    close_session = False
    if session is None:
        session = AsyncSessionLocal()
        close_session = True

    try:
        repo = UISettingsRepository(db=session)
        saved = await repo.get_all()

        def _get(key: str, env_fallback: Optional[str] = None) -> Optional[str]:
            raw = saved.get(key)
            if raw:
                if key in SENSITIVE_SETTINGS:
                    return decrypt_value(raw)
                return raw
            return env_fallback

        return IntegrationSettings(
            jenkins_url=_get("jenkins_base_url", env_settings.jenkins_url),
            jenkins_username=_get("jenkins_username", env_settings.jenkins_username),
            jenkins_token=_get("jenkins_token", env_settings.jenkins_token),
            github_base_url=_get("github_base_url", None),
            github_organization=_get("github_organization", env_settings.github_organization),
            github_token=_get("github_token", env_settings.github_token),
            step_timeout_minutes=_get("step_timeout_minutes", None),
        )
    finally:
        if close_session:
            await session.close()
