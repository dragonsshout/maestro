from typing import Optional

import httpx

from maestro.schemas.github import PullRequestDetailSchema, PullRequestSchema


class GithubIntegration:
    def __init__(
        self,
        organization: str,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        trust_env: bool = True,
    ):
        """
        Inicializa a integração com o GitHub.

        :param organization: Nome da organização ou usuário no GitHub.
        :param token: Token de acesso pessoal (PAT) do GitHub (opcional, mas recomendado).
        :param base_url: URL base da instância GitHub. Para GitHub.com usa a API pública.
                         Para GitHub Enterprise, converte automaticamente para o endpoint /api/v3.
        :param trust_env: Se True, httpx respeita variáveis de ambiente (HTTP_PROXY, SSL_CERT_FILE, etc).
        """
        self.base_url = self._resolve_api_url(base_url)
        self.organization = organization
        self.token = token
        self.trust_env = trust_env

    @staticmethod
    def _resolve_api_url(base_url: Optional[str]) -> str:
        """
        Resolve a URL de API a partir da base_url fornecida.
        - Se None ou vazio: usa https://api.github.com
        - Se for https://github.com: usa https://api.github.com
        - Se for GitHub Enterprise (ex: https://github.minha-empresa.com): usa {base}/api/v3
        """
        if not base_url:
            return "https://api.github.com"

        url = base_url.rstrip("/")

        # GitHub.com public
        if url in ("https://github.com", "http://github.com"):
            return "https://api.github.com"

        # GitHub Enterprise: appenda /api/v3 se ainda nao tem
        if url.endswith("/api/v3"):
            return url

        return f"{url}/api/v3"

    def _get_client(self) -> httpx.AsyncClient:
        headers = {"Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return httpx.AsyncClient(base_url=self.base_url, headers=headers, trust_env=self.trust_env)

    async def repository_exists(self, repo_name: str) -> bool:
        """
        Verifica se um repositório existe na organização.

        :param repo_name: Nome do repositório (ex: 'Hello-World').
        :return: True se o repositório existir, False caso contrário.
        """
        async with self._get_client() as client:
            endpoint = f"/repos/{self.organization}/{repo_name}"
            response = await client.get(endpoint)
            return response.status_code == 200

    async def branch_exists(self, repo_name: str, branch_name: str) -> bool:
        """
        Verifica se uma branch existe no repositório.

        :param repo_name: Nome do repositório (ex: 'Hello-World').
        :param branch_name: Nome da branch (ex: 'release/v1.0').
        :return: True se a branch existir, False caso contrário.
        """
        async with self._get_client() as client:
            endpoint = f"/repos/{self.organization}/{repo_name}/branches/{branch_name}"
            response = await client.get(endpoint)
            return response.status_code == 200

    async def get_pull_request_details(self, repo_name: str, pr_number: int) -> PullRequestDetailSchema:
        """
        Obtém os detalhes completos de um Pull Request pelo seu número.

        :param repo_name: Nome do repositório (ex: 'Hello-World').
        :param pr_number: Número do Pull Request.
        :return: Schema com os dados detalhados do Pull Request.
        """
        async with self._get_client() as client:
            endpoint = f"/repos/{self.organization}/{repo_name}/pulls/{pr_number}"
            response = await client.get(endpoint)
            response.raise_for_status()
            return PullRequestDetailSchema(**response.json())

    async def get_pull_request_by_branch(self, repo_name: str, branch_name: str) -> Optional[PullRequestSchema]:
        """
        Obtém o Pull Request aberto associado a uma determinada branch.

        :param repo_name: Nome do repositório (ex: 'Hello-World').
        :param branch_name: Nome da branch de origem (ex: 'feature-nova').
        :return: Schema com os dados do Pull Request se encontrado, caso contrário None.
        """
        async with self._get_client() as client:
            endpoint = f"/repos/{self.organization}/{repo_name}/pulls"
            params = {"head": f"{self.organization}:{branch_name}", "state": "open"}

            response = await client.get(endpoint, params=params)
            response.raise_for_status()

            prs = response.json()
            if prs and len(prs) > 0:
                return PullRequestSchema(**prs[0])

            return None
