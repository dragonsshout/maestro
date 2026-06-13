"""
Serviço responsável pelo gerenciamento do Job Path Registry,
incluindo o discovery de jobs a partir da API do Jenkins.

O discovery consulta: <JENKINS_BASE_URL>/api/json?tree=jobs[name,url,jobs[name,url,jobs[name,url]]]
e extrai os dados seguindo o padrão de URL:
  <JENKINS_BASE_URL>/job/<ENVIRONMENT>/job/<DOMAIN>/job/<REPOSITORY>/

O resultado é persistido via upsert (repository + environment como chave única).
"""

from urllib.parse import urlparse

import httpx
from fastapi import Depends

from maestro.config.logger import get_logger
from maestro.database.models import JobPathRegistry
from maestro.repositories.job_path_registry import JobPathRegistryRepository
from maestro.schemas.job_path_registry import JobPathRegistryDiscoveryResponse

logger = get_logger(__name__)


class JobPathRegistryService:
    def __init__(self, repository: JobPathRegistryRepository = Depends()):
        self.repository = repository

    async def get_all_paginated(
        self, page: int = 1, per_page: int = 15, search: str | None = None
    ) -> tuple[list[JobPathRegistry], int]:
        skip = (page - 1) * per_page
        entries = await self.repository.get_all(skip=skip, limit=per_page, search=search)
        total_count = await self.repository.get_count(search=search)
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        return entries, total_pages

    async def discover_from_jenkins(self) -> JobPathRegistryDiscoveryResponse:
        """
        Consulta a API do Jenkins para descobrir todos os jobs e popula
        a tabela job_path_registry via upsert.

        Padrão de URL esperado:
          <JENKINS_BASE_URL>/job/<ENVIRONMENT>/job/<DOMAIN>/job/<REPOSITORY>/
        """
        from maestro.services.app_settings import get_integration_settings

        cfg = await get_integration_settings(session=self.repository.db)
        if not cfg.jenkins_url:
            raise ValueError("URL base do Jenkins não configurada.")

        jenkins_base_url = cfg.jenkins_url.rstrip("/")
        auth = (cfg.jenkins_username, cfg.jenkins_token) if cfg.jenkins_username and cfg.jenkins_token else None

        # Consulta a árvore de jobs do Jenkins (3 níveis de profundidade)
        api_url = f"{jenkins_base_url}/api/json"
        params = {"tree": "jobs[name,url,jobs[name,url,jobs[name,url]]]"}

        async with httpx.AsyncClient(auth=auth, trust_env=cfg.http_trust_env) as client:
            response = await client.get(api_url, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()

        # Extrai os jobs do resultado
        entries = self._parse_jenkins_tree(data, jenkins_base_url)

        logger.info(f"Jenkins discovery: {len(entries)} jobs encontrados.")

        # Faz upsert de todos os registros
        count = await self.repository.upsert_many(entries)

        return JobPathRegistryDiscoveryResponse(
            total_discovered=len(entries),
            total_upserted=count,
            message=f"Discovery concluído: {len(entries)} jobs encontrados, {count} registros atualizados.",
        )

    def _parse_jenkins_tree(self, data: dict, jenkins_base_url: str) -> list[JobPathRegistry]:
        """
        Percorre a árvore de jobs do Jenkins e extrai os registros.

        A estrutura esperada é:
        - Nível 1: Environment (ex: PRD, UAT, DEV)
        - Nível 2: Domain (ex: risk-energy, payments)
        - Nível 3: Repository/Job (ex: function-autenticar-securitysvc)

        A URL de cada job segue o padrão:
          <JENKINS_BASE_URL>/job/<ENVIRONMENT>/job/<DOMAIN>/job/<REPOSITORY>/
        """
        entries = []
        top_jobs = data.get("jobs", [])

        for env_folder in top_jobs:
            environment = env_folder.get("name")
            if not environment:
                continue

            domain_jobs = env_folder.get("jobs", [])
            for domain_folder in domain_jobs:
                domain = domain_folder.get("name")
                if not domain:
                    continue

                repo_jobs = domain_folder.get("jobs", [])
                for repo_job in repo_jobs:
                    repository = repo_job.get("name")
                    job_url = repo_job.get("url", "")
                    if not repository:
                        continue

                    # Constrói o path relativo a partir da URL do job
                    path = self._extract_path_from_url(job_url, jenkins_base_url)

                    entries.append(
                        JobPathRegistry(
                            repository=repository,
                            environment=environment,
                            domain=domain,
                            type="jenkins",
                            path=path,
                        )
                    )

        return entries

    def _extract_path_from_url(self, job_url: str, jenkins_base_url: str) -> str:
        """
        Extrai o path relativo do job a partir da URL completa.

        Ex: http://jenkins.dev/job/UAT/job/risk-energy/job/my-repo/
        -> job/UAT/job/risk-energy/job/my-repo
        """
        # Remove a base URL para obter apenas o path relativo
        if job_url.startswith(jenkins_base_url):
            relative = job_url[len(jenkins_base_url):]
        else:
            # Fallback: extrai apenas o path da URL
            parsed = urlparse(job_url)
            relative = parsed.path

        # Remove barras iniciais e finais
        return relative.strip("/")
