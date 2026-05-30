from typing import Optional
import asyncio
from fastapi import Depends
from maestro.integration.jenkins import JenkinsIntegration
from maestro.repositories.execution import ExecutionRepository
from maestro.config.settings import settings
from maestro.config.logger import get_logger

logger = get_logger(__name__)

class JenkinsService:
    def __init__(self, execution_repo: ExecutionRepository = Depends()):
        self.execution_repo = execution_repo
        self.jenkins_integration = JenkinsIntegration(
            base_url=settings.jenkins_url,
            username=settings.jenkins_username,
            token=settings.jenkins_token
        )

    async def trigger_job(self, job_path: str, step_execution_id: int, release_branch: str):
        # Aqui você passa os parâmetros para o Jenkins. Usaremos BRANCH = release_branch como exemplo
        params = {"BRANCH": release_branch}

        logger.info(f"Triggering job {job_path} for step {step_execution_id} with branch {release_branch}")
        queue_url = await self.jenkins_integration.trigger_job_and_get_queue_url(job_path, parameters=params)
        
        # após trigger o job, aguarda até que o job saia da fila e atualiza o step execution com o correlation_id
        asyncio.create_task(self.poll_and_update_correlation(queue_url, step_execution_id))

    async def poll_and_update_correlation(self, queue_url: str, step_execution_id: int):
        from maestro.database.session import AsyncSessionLocal
        
        for trying in range(1, 60): # Poll for up to 120 seconds
            logger.info(f"Polling queue {queue_url} for step {step_execution_id} - trying {trying}/60")
            
            try:
                info = await self.jenkins_integration.get_queue_item_info(queue_url)
                if info.executable:
                    build_number = info.executable.number

                    if build_number:
                        async with AsyncSessionLocal() as session:
                            # Import locally to avoid circular imports if any, and instantiate with the new session
                            repo = ExecutionRepository(db=session)
                            se = await repo.get_step_by_id(step_execution_id)
                            if se:
                                # salva o correlation id com o valor do build number
                                se.job_execution_correlation_id = build_number
                                await repo.update_step_execution(se)
                                logger.info(f"Updated correlation ID for step {step_execution_id} to {build_number}")
                            else:
                                logger.error(f"Step {step_execution_id} not found")
                        
                        return

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Error polling queue {queue_url}: {e}")
                await asyncio.sleep(2)

        logger.error(f"Timeout waiting for executable for queue {queue_url}")

    async def approve_job(self, job_path: str, build_number: int, input_id: Optional[str] = None, status: str = "Sucesso"):
        logger.info(f"Approving job {job_path} build {build_number} with status {status}")
        await self.jenkins_integration.approve_pipeline(job_path, build_number, input_id, status=status)

