import json
import httpx
from typing import Optional, Dict, Any

from maestro.schemas.jenkins import JenkinsQueueItemSchema, JenkinsPendingInputSchema

class JenkinsIntegration:
    def __init__(self, base_url: str, username: Optional[str] = None, token: Optional[str] = None, trust_env: bool = True):
        """
        Inicializa a integração com o Jenkins.

        :param base_url: URL base do Jenkins (ex: 'http://jenkins.local:8080')
        :param username: Usuário para autenticação (opcional)
        :param token: Token de API ou senha para autenticação (opcional)
        :param trust_env: Se True, httpx respeita variáveis de ambiente (HTTP_PROXY, SSL_CERT_FILE, etc).
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.token = token
        self.trust_env = trust_env

    def _get_client(self) -> httpx.AsyncClient:
        auth = (self.username, self.token) if self.username and self.token else None
        return httpx.AsyncClient(base_url=self.base_url, auth=auth, trust_env=self.trust_env)

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
            
            if response.status_code not in (200, 201, 202, 302, 303):
                response.raise_for_status()
            
            # Jenkins returns 201 Created (ou 303 See Other) with Location header pointing to the queue item
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

    async def approve_pipeline(self, job_name: str, build_number: int, input_id: Optional[str] = None, status: str = "Sucesso") -> None:

        async with self._get_client() as client:
            proceed_url = f"/{job_name.strip('/')}/{build_number}/input/{input_id}/proceed"
            
            form_data = {
                "json": json.dumps({"parameter": [{"name": "STATUS", "value": status}]})
            }
            
            response = await client.post(proceed_url, data=form_data)
            if response.status_code not in (200, 302):
                response.raise_for_status()

    async def abort_build(self, job_name: str, build_number: int) -> None:
        """
        Envia um request de abort (stop) para um build específico no Jenkins.

        :param job_name: Nome/caminho do job.
        :param build_number: Número do build a ser abortado.
        """
        async with self._get_client() as client:
            endpoint = f"/{job_name.strip('/')}/{build_number}/stop"
            response = await client.post(endpoint)
            if response.status_code not in (200, 302):
                response.raise_for_status()

    async def job_exists(self, job_name: str) -> bool:
        """
        Verifica se um job existe no Jenkins.

        :param job_name: Nome/caminho do job.
        :return: True se o job existir, False caso contrário.
        """
        async with self._get_client() as client:
            endpoint = f"/{job_name.strip('/')}/api/json"
            response = await client.get(endpoint)
            return response.status_code == 200
