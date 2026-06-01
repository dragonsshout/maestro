import httpx
from typing import Optional
from maestro.schemas.github import PullRequestSchema, PullRequestDetailSchema

class GithubIntegration:
    def __init__(self, organization: str, token: Optional[str] = None):
        """
        Inicializa a integração com o GitHub.
        
        :param organization: Nome da organização ou usuário no GitHub.
        :param token: Token de acesso pessoal (PAT) do GitHub (opcional, mas recomendado).
        """
        self.base_url = "https://api.github.com"
        self.organization = organization
        self.token = token

    def _get_client(self) -> httpx.AsyncClient:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            
        return httpx.AsyncClient(base_url=self.base_url, headers=headers)

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

    async def branch_exists(self, repo_name: str, branch_name: str) -> bool:
        """
        Verifica se uma branch existe no repositório.

        :param repo_name: Nome do repositório.
        :param branch_name: Nome da branch.
        :return: True se a branch existir, False caso contrário.
        """
        async with self._get_client() as client:
            endpoint = f"/repos/{self.organization}/{repo_name}/branches/{branch_name}"
            response = await client.get(endpoint)
            return response.status_code == 200

    async def get_pull_request_by_branch(self, repo_name: str, branch_name: str) -> Optional[PullRequestSchema]:
        """
        Obtém o Pull Request aberto associado a uma determinada branch.

        :param repo_name: Nome do repositório (ex: 'Hello-World').
        :param branch_name: Nome da branch de origem (ex: 'feature-nova').
        :return: Schema com os dados do Pull Request se encontrado, caso contrário None.
        """
        async with self._get_client() as client:
            endpoint = f"/repos/{self.organization}/{repo_name}/pulls"
            params = {
                "head": f"{self.organization}:{branch_name}",
                "state": "open"
            }
            
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
            
            prs = response.json()
            if prs and len(prs) > 0:
                return PullRequestSchema(**prs[0])
            
            return None
