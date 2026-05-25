import asyncio
import httpx
from typing import Optional, Dict, Any

from maestro.schemas.jenkins import JenkinsQueueItemSchema

class JenkinsIntegration:
    def __init__(self, base_url: str, username: Optional[str] = None, token: Optional[str] = None):
        """
        Inicializa a integração com o Jenkins.

        :param base_url: URL base do Jenkins (ex: 'http://jenkins.local:8080')
        :param username: Usuário para autenticação (opcional)
        :param token: Token de API ou senha para autenticação (opcional)
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.token = token

    def _get_client(self) -> httpx.AsyncClient:
        auth = (self.username, self.token) if self.username and self.token else None
        return httpx.AsyncClient(base_url=self.base_url, auth=auth)

    async def build_job(self, job_name: str, parameters: Optional[Dict[str, str]] = None, fire_and_forget: bool = False) -> Optional[httpx.Response]:
        """
        Dispara a execução de um job no Jenkins.

        :param job_name: Nome do job a ser executado.
        :param parameters: Dicionário opcional com os parâmetros do job.
        :param fire_and_forget: Se True, dispara a requisição em background e não aguarda a resposta.
        :return: Objeto Response do httpx ou None se fire_and_forget for True.
        """
        async def _do_request():
            async with self._get_client() as client:
                if parameters:
                    endpoint = f"/{job_name.strip('/')}/buildWithParameters"
                    response = await client.post(endpoint, params=parameters)
                else:
                    endpoint = f"/{job_name.strip('/')}/build"
                    response = await client.post(endpoint)
                
                response.raise_for_status()
                return response

        if fire_and_forget:
            asyncio.create_task(_do_request())
            return None
        else:
            return await _do_request()

    async def trigger_job_and_get_queue_url(self, job_name: str, parameters: Optional[Dict[str, str]] = None) -> str:
        """
        Dispara um job no Jenkins e retorna a URL do item na fila (Queue Item).
        """
        async with self._get_client() as client:
            if parameters:
                endpoint = f"/{job_name.strip('/')}/buildWithParameters"
                response = await client.post(endpoint, params=parameters)
            else:
                endpoint = f"/{job_name.strip('/')}/build"
                response = await client.post(endpoint)
            
            response.raise_for_status()
            # Jenkins returns 201 Created with Location header pointing to the queue item
            location = response.headers.get("Location")
            if not location:
                raise ValueError("Jenkins não retornou o header 'Location' ao disparar o job.")
            return location

    async def get_queue_item_info(self, queue_url: str) -> JenkinsQueueItemSchema:
        """
        Obtém informações de um item na fila usando a URL retornada no disparo.
        """
        async with self._get_client() as client:
            # Ensure the URL is just the path if it includes the domain
            if queue_url.startswith(self.base_url):
                queue_url = queue_url[len(self.base_url):]
            
            endpoint = f"{queue_url.rstrip('/')}/api/json"
            response = await client.get(endpoint)
            response.raise_for_status()
            return JenkinsQueueItemSchema(**response.json())

    async def get_job_info(self, job_name: str) -> Dict[str, Any]:
        """
        Obtém os detalhes e as informações gerais de um job no Jenkins.

        :param job_name: Nome do job.
        :return: Dicionário com as informações (JSON) retornadas pelo Jenkins.
        """
        async with self._get_client() as client:
            endpoint = f"/{job_name.strip('/')}/api/json"
            response = await client.get(endpoint)
            response.raise_for_status()
            return response.json()
