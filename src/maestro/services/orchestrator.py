import asyncio
from fastapi import Depends, BackgroundTasks
from maestro.database.models import OrchestratorDescriptor, ReleaseExecution, ReleaseStepExecution
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.repositories.execution import ExecutionRepository
from maestro.schemas.orchestrator import ReleaseConfigSchema, DryRunResponse, DryRunStageResult, DryRunStepResult
from maestro.config.settings import settings
from maestro.integration.github import GithubIntegration
from maestro.integration.jenkins import JenkinsIntegration
from pydantic import ValidationError
import yaml
from sqlalchemy.exc import IntegrityError
from maestro.config.logger import get_logger
from maestro.services.jenkins import JenkinsService
from maestro.services.validation import ReleaseValidationService
from maestro.schemas.enums import ExecutionStatus

logger = get_logger(__name__)

class OrchestratorService:
    def __init__(
        self, 
        repository: OrchestratorDescriptorRepository = Depends(),
        execution_repo: ExecutionRepository = Depends(),
        jenkins_service: JenkinsService = Depends()
    ):
        self.repository = repository
        self.execution_repo = execution_repo
        self.jenkins_service = jenkins_service

    async def save_descriptor(self, yaml_content: str) -> OrchestratorDescriptor:
        # Validação do formato YAML
        try:
            parsed_yaml = yaml.safe_load(yaml_content)

            # Validação do Schema Pydantic
            release_config = ReleaseConfigSchema(**parsed_yaml)

        except (yaml.YAMLError, ValidationError) as e:
            raise ValueError(f"Erro de validação na estrutura do YAML:\n{e}")

        # Validação de branches (GitHub) e jobs (Jenkins)
        validation_service = ReleaseValidationService()
        await validation_service.validate(release_config)

        descriptor = OrchestratorDescriptor(
            name=release_config.metadata.name,
            yaml=yaml_content
        )

        try:
            return await self.repository.add(descriptor)
        except IntegrityError:
            raise ValueError(f"Já existe uma configuração de release com o nome '{release_config.metadata.name}'.")

    async def dry_run_release(self, name: str) -> DryRunResponse:
        descriptor = await self.repository.get_by_name(name)
        if not descriptor:
            raise ValueError(f"Descritor com nome '{name}' não encontrado.")

        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))

        from maestro.services.app_settings import get_integration_settings
        cfg = await get_integration_settings()
        github = GithubIntegration(
            organization=cfg["github_organization"] or settings.github_organization,
            token=cfg["github_token"] or settings.github_token,
        )
        jenkins = JenkinsIntegration(
            base_url=cfg["jenkins_url"] or settings.jenkins_url,
            username=cfg["jenkins_username"] or settings.jenkins_username,
            token=cfg["jenkins_token"] or settings.jenkins_token,
        )

        all_valid = True
        stages_results: list[DryRunStageResult] = []

        for stage in config.spec.stages:
            steps_results: list[DryRunStepResult] = []

            for step in stage.steps:
                branch_exists = False
                pr_found = False
                pr_number = None
                pr_mergeable_state = None
                pr_is_clean = False
                jenkins_job_exists = False

                try:
                    branch_exists = await github.branch_exists(step.repository, step.release)
                except Exception:
                    branch_exists = False

                if branch_exists:
                    try:
                        pr = await github.get_pull_request_by_branch(step.repository, step.release)
                        if pr:
                            pr_found = True
                            pr_number = pr.number
                            try:
                                pr_detail = await github.get_pull_request_details(step.repository, pr.number)
                                pr_mergeable_state = pr_detail.mergeable_state
                                pr_is_clean = pr_detail.mergeable_state == "clean"
                            except Exception:
                                pr_is_clean = False
                    except Exception:
                        pr_found = False

                try:
                    jenkins_job_exists = await jenkins.job_exists(step.job.path)
                except Exception:
                    jenkins_job_exists = False

                step_valid = branch_exists and pr_found and pr_is_clean and jenkins_job_exists
                if not step_valid:
                    all_valid = False

                steps_results.append(DryRunStepResult(
                    step_id=step.id,
                    stage_id=stage.id,
                    repository=step.repository,
                    branch=step.release,
                    branch_exists=branch_exists,
                    pr_found=pr_found,
                    pr_number=pr_number,
                    pr_mergeable_state=pr_mergeable_state,
                    pr_is_clean=pr_is_clean,
                    jenkins_job_path=step.job.path,
                    jenkins_job_exists=jenkins_job_exists,
                ))

            stages_results.append(DryRunStageResult(
                stage_id=stage.id,
                steps=steps_results,
            ))

        return DryRunResponse(
            name=name,
            valid=all_valid,
            stages=stages_results,
        )

    async def execute_release(self, name: str, background_tasks: BackgroundTasks) -> int:
        descriptor = await self.repository.get_by_name(name)
        if not descriptor:
            raise ValueError(f"Descritor com nome '{name}' não encontrado.")

        active = await self.execution_repo.get_active_execution_by_name(name)
        if active:
            raise ValueError(
                f"Já existe uma execução ativa (#{active.id}) para a release '{name}' "
                f"com status '{active.status}'. Aguarde a conclusão ou abort antes de iniciar uma nova."
            )

        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))

        release_execution = ReleaseExecution(
            name=name,
            status=ExecutionStatus.PENDING,
            orchestrator_descriptor_id=descriptor.id
        )
        release_execution = await self.execution_repo.add_release_execution(release_execution)

        from maestro.services.app_settings import get_integration_settings as _get_cfg
        _cfg = await _get_cfg()
        github = GithubIntegration(
            organization=_cfg["github_organization"] or settings.github_organization,
            token=_cfg["github_token"] or settings.github_token,
        )
        try:
            for stage in config.spec.stages:
                for step in stage.steps:
                    pr = await github.get_pull_request_by_branch(step.repository, step.release)
                    if not pr:
                        raise ValueError(f"Pull Request não encontrado para a branch '{step.release}' no repositório '{step.repository}'.")
                    
                    pr_detail = await github.get_pull_request_details(step.repository, pr.number)
                    if pr_detail.mergeable_state != "clean":
                        raise ValueError(f"O Pull Request para a branch '{step.release}' no repositório '{step.repository}' não está no estado 'clean' (estado atual: '{pr_detail.mergeable_state}').")

        except Exception as e:
            release_execution.status = ExecutionStatus.FAILURE
            release_execution.message = str(e)

            # atualiza dados da falha
            await self.execution_repo.update_release_execution(release_execution)

            raise e

        # cria os steps para cada stage
        for stage in config.spec.stages:
            for step in stage.steps:
                step_execution = ReleaseStepExecution(
                    release_execution_id=release_execution.id,
                    stage_id=stage.id,
                    step_id=step.id,
                    status=ExecutionStatus.PENDING
                )
                await self.execution_repo.add_step_execution(step_execution)

        background_tasks.add_task(self.process_workflow, release_execution.id)
        return release_execution.id

    async def approve_release(self, name: str, background_tasks: BackgroundTasks, status: str = "Sucesso") -> dict:
        execution = await self.execution_repo.get_latest_execution_by_name(name)
        if not execution:
            raise ValueError(f"Nenhuma execução encontrada para a release '{name}'.")

        if execution.status != ExecutionStatus.WAITING_APPROVAL:
            raise ValueError(f"A execução '{name}' não está aguardando aprovação (status atual: {execution.status}).")

        descriptor = await self.repository.get_by_id(execution.orchestrator_descriptor_id)
        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
        
        steps_exec = await self.execution_repo.get_steps_by_execution_id(execution.id)
        
        step_exec_map = {(se.stage_id, se.step_id): se for se in steps_exec}
        
        approved_steps = []
        for stage in config.spec.stages:
            for step in stage.steps:
                se = step_exec_map.get((stage.id, step.id))
                
                if se and se.status == ExecutionStatus.WAITING_APPROVAL:
                    if step.job.type == "jenkins":
                        if not se.job_execution_correlation_id:
                            logger.warning(f"Step {se.id} aguardando aprovação mas sem correlation_id (build_number)")
                            continue
                            
                        # Chama o Jenkins para aprovar
                        try:
                            await self.jenkins_service.approve_job(
                                job_path=step.job.path, 
                                build_number=se.job_execution_correlation_id, 
                                input_id=se.job_input_id,
                                status=status
                            )
                            # Atualiza status para in_progress
                            se.status = ExecutionStatus.IN_PROGRESS
                            await self.execution_repo.update_step_execution(se)
                            approved_steps.append(se.id)

                        except Exception as e:
                            logger.error(f"Erro ao aprovar job {step.job.path}: {e}")
                            raise ValueError(f"Erro ao aprovar job {step.job.path}: {e}")
                    else:
                        logger.warning(f"Aprovação manual para job_type {step.job.type} não suportada")

        if approved_steps:
            execution.status = ExecutionStatus.IN_PROGRESS
            await self.execution_repo.update_release_execution(execution)
            background_tasks.add_task(self.process_workflow, execution.id)
            return {"message": "Aprovação enviada com sucesso ao Jenkins", "approved_steps": approved_steps}
        else:
            return {"message": "Nenhum step pendente de aprovação encontrado que pudesse ser aprovado."}

    async def retry_step(self, step_execution_id: int, background_tasks: BackgroundTasks) -> ReleaseStepExecution:
        """Reexecuta um step que falhou, resetando seu status e continuando o fluxo."""
        step = await self.execution_repo.get_step_by_id(step_execution_id)
        if not step:
            raise ValueError(f"Step de execução #{step_execution_id} não encontrado.")

        if step.status not in (ExecutionStatus.FAILURE, ExecutionStatus.TIMEOUT):
            raise ValueError(f"Só é possível reexecutar steps com status 'failure' ou 'timeout' (status atual: '{step.status}').")

        # Reseta o step
        step.status = ExecutionStatus.PENDING
        step.message = None
        step.job_execution_correlation_id = None
        step.job_input_id = None
        await self.execution_repo.update_step_execution(step)

        # Reseta a execução para IN_PROGRESS para que o workflow continue
        execution = await self.execution_repo.get_execution_by_id(step.release_execution_id)
        if execution and execution.status in (ExecutionStatus.FAILURE, ExecutionStatus.TIMEOUT, ExecutionStatus.SUCCESS):
            execution.status = ExecutionStatus.IN_PROGRESS
            execution.message = None
            await self.execution_repo.update_release_execution(execution)

        # Re-dispara o workflow
        logger.info(f"Retry step {step_execution_id}: step resetado para PENDING, re-disparando workflow {step.release_execution_id}")
        background_tasks.add_task(self.process_workflow, step.release_execution_id)
        return step

    async def cancel_execution(self, execution_id: int, abort_jobs: bool = False) -> ReleaseExecution:
        """
        Cancela uma execução em andamento.

        :param execution_id: ID da execução a cancelar.
        :param abort_jobs: Se True, além de cancelar no Maestro, envia abort ao Jenkins
                           para todos os steps in_progress ou waiting_approval com build number.
        :returns: A execução atualizada.
        """
        execution = await self.execution_repo.get_execution_by_id(execution_id)
        if not execution:
            raise ValueError("Execução não encontrada.")

        terminal = {ExecutionStatus.SUCCESS, ExecutionStatus.FAILURE, ExecutionStatus.ABORTED}
        if execution.status in terminal:
            raise ValueError(f"Execução já está em status terminal: {execution.status}")

        # Se abort_jobs, envia abort ao Jenkins para cada step ativo
        aborted_steps = []
        if abort_jobs:
            steps = await self.execution_repo.get_steps_by_execution_id(execution_id)
            abortable_statuses = {ExecutionStatus.IN_PROGRESS, ExecutionStatus.WAITING_APPROVAL}

            for step in steps:
                if step.status in abortable_statuses and step.job_execution_correlation_id:
                    job_path = await self._resolve_job_path(step)
                    if job_path:
                        try:
                            await self.jenkins_service.abort_build(job_path, step.job_execution_correlation_id)
                        except Exception as e:
                            logger.warning(
                                f"Falha ao enviar abort para step {step.step_id} "
                                f"(build #{step.job_execution_correlation_id}): {e}"
                            )
                    step.status = ExecutionStatus.ABORTED
                    step.message = "Abortado pelo cancelamento da execução."
                    await self.execution_repo.update_step_execution(step)
                    aborted_steps.append(step)

        execution.status = ExecutionStatus.ABORTED
        if abort_jobs and aborted_steps:
            execution.message = f"Cancelado com abort de {len(aborted_steps)} job(s) no Jenkins."
        else:
            execution.message = "Cancelado manualmente pelo operador."
        await self.execution_repo.update_release_execution(execution)
        return execution

    async def abort_step(self, step_execution_id: int) -> ReleaseStepExecution:
        """
        Envia um cancelamento forçado (abort/stop) ao Jenkins e marca o step como ABORTED.
        Requer que o step tenha job_execution_correlation_id preenchido.
        """
        step = await self.execution_repo.get_step_by_id(step_execution_id)
        if not step:
            raise ValueError(f"Step de execução #{step_execution_id} não encontrado.")

        if step.status in (ExecutionStatus.SUCCESS, ExecutionStatus.ABORTED):
            raise ValueError(f"Step já está em status terminal: {step.status}.")

        if not step.job_execution_correlation_id:
            raise ValueError("Step não possui build number associado (correlation_id ausente).")

        job_path = await self._resolve_job_path(step)
        if not job_path:
            raise ValueError("Não foi possível determinar o job path para este step.")

        await self.jenkins_service.abort_build(job_path, step.job_execution_correlation_id)

        step.status = ExecutionStatus.ABORTED
        step.message = f"Cancelamento forçado enviado ao Jenkins (build #{step.job_execution_correlation_id})."
        await self.execution_repo.update_step_execution(step)
        return step

    async def approve_step(self, step_execution_id: int, background_tasks: BackgroundTasks) -> ReleaseStepExecution:
        """
        Aprova individualmente um step que está aguardando aprovação no Jenkins.
        Requer que o step tenha job_input_id preenchido.
        """
        step = await self.execution_repo.get_step_by_id(step_execution_id)
        if not step:
            raise ValueError(f"Step de execução #{step_execution_id} não encontrado.")

        if step.status != ExecutionStatus.WAITING_APPROVAL:
            raise ValueError(f"Step não está aguardando aprovação (status: {step.status}).")

        if not step.job_input_id:
            raise ValueError("Step não possui input_id preenchido. Não é possível aprovar.")

        if not step.job_execution_correlation_id:
            raise ValueError("Step não possui build number associado (correlation_id ausente).")

        job_path = await self._resolve_job_path(step)
        if not job_path:
            raise ValueError("Não foi possível determinar o job path para este step.")

        await self.jenkins_service.approve_job(
            job_path=job_path,
            build_number=step.job_execution_correlation_id,
            input_id=step.job_input_id,
            status="Sucesso",
        )

        step.status = ExecutionStatus.IN_PROGRESS
        step.message = f"Aprovação individual enviada ao Jenkins (build #{step.job_execution_correlation_id})."
        await self.execution_repo.update_step_execution(step)

        background_tasks.add_task(self.process_workflow, step.release_execution_id)
        return step

    async def _resolve_job_path(self, step: ReleaseStepExecution) -> str | None:
        """Resolve o job_path de um step a partir do descritor YAML da execução."""
        execution = await self.execution_repo.get_execution_by_id(step.release_execution_id)
        if not execution:
            return None
        descriptor = await self.repository.get_by_id(execution.orchestrator_descriptor_id)
        if not descriptor:
            return None
        config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
        for stage in config.spec.stages:
            for step_def in stage.steps:
                if stage.id == step.stage_id and step_def.id == step.step_id:
                    return step_def.job.path
        return None

    async def _trigger_step(self, step, se) -> ExecutionStatus:
        """Dispara um único step e retorna o status resultante (usa repo do request)."""
        return await self._trigger_step_standalone(step, se, self.execution_repo)

    async def process_workflow(self, execution_id: int):
        """
        Processa o workflow de uma execução.
        Cria sua própria sessão de banco para funcionar corretamente como background task.
        """
        from maestro.database.session import AsyncSessionLocal
        from maestro.repositories.execution import ExecutionRepository as _ExecRepo
        from maestro.repositories.orchestrator import OrchestratorDescriptorRepository as _OrcRepo

        async with AsyncSessionLocal() as session:
            exec_repo = _ExecRepo(db=session)
            orch_repo = _OrcRepo(db=session)

            execution = await exec_repo.get_execution_by_id(execution_id)
            if not execution:
                logger.warning(f"Execução {execution_id} não encontrada.")
                return

            if execution.status in [ExecutionStatus.SUCCESS, ExecutionStatus.FAILURE]:
                return

            # Garante que a execução está em IN_PROGRESS
            if execution.status == ExecutionStatus.PENDING:
                execution.status = ExecutionStatus.IN_PROGRESS
                await exec_repo.update_release_execution(execution)

            descriptor = await orch_repo.get_by_id(execution.orchestrator_descriptor_id)
            config = ReleaseConfigSchema(**yaml.safe_load(descriptor.yaml))
            steps_exec = await exec_repo.get_steps_by_execution_id(execution_id)

            # Mapear as execuções de step
            step_exec_map = {(se.stage_id, se.step_id): se for se in steps_exec}

            execution_in_progress = False
            execution_failed = False
            execution_waiting_approval = False

            for stage in config.spec.stages:
                # Classifica os steps do stage pelo status atual
                stage_has_failure = False
                stage_has_in_progress = False
                stage_has_waiting_approval = False
                stage_has_timeout = False
                pending_to_trigger = []

                for step in stage.steps:
                    se = step_exec_map.get((stage.id, step.id))
                    if not se:
                        continue

                    if se.status == ExecutionStatus.FAILURE:
                        stage_has_failure = True
                        break
                    elif se.status == ExecutionStatus.TIMEOUT:
                        stage_has_timeout = True
                    elif se.status == ExecutionStatus.IN_PROGRESS:
                        stage_has_in_progress = True
                    elif se.status == ExecutionStatus.WAITING_APPROVAL:
                        stage_has_waiting_approval = True
                    elif se.status == ExecutionStatus.PENDING:
                        pending_to_trigger.append((step, se))

                if stage_has_failure:
                    execution.status = ExecutionStatus.FAILURE
                    await exec_repo.update_release_execution(execution)
                    return

                if stage_has_timeout:
                    execution_in_progress = True
                    return

                # Dispara todos os steps PENDING do stage sequencialmente
                if pending_to_trigger:
                    for step, se in pending_to_trigger:
                        result = await self._trigger_step_standalone(step, se, exec_repo)
                        if result == ExecutionStatus.FAILURE:
                            execution.status = ExecutionStatus.FAILURE
                            await exec_repo.update_release_execution(execution)
                            return
                        elif result == ExecutionStatus.IN_PROGRESS:
                            stage_has_in_progress = True

                if stage_has_waiting_approval:
                    execution_waiting_approval = True

                if stage_has_in_progress:
                    execution_in_progress = True
                    # Enquanto há steps em andamento, a execução permanece IN_PROGRESS,
                    # mesmo que stages anteriores tenham steps aguardando aprovação.
                    # O status WAITING_APPROVAL só é gravado quando todo o fluxo terminar.
                    execution.status = ExecutionStatus.IN_PROGRESS
                    await exec_repo.update_release_execution(execution)
                    return

            # Todos os stages foram processados
            if execution_waiting_approval:
                execution.status = ExecutionStatus.WAITING_APPROVAL
            elif not execution_in_progress:
                execution.status = ExecutionStatus.SUCCESS
            await exec_repo.update_release_execution(execution)

    async def _trigger_step_standalone(self, step, se, exec_repo) -> ExecutionStatus:
        """Dispara um único step usando o repo fornecido (para background tasks)."""
        se.status = ExecutionStatus.IN_PROGRESS
        await exec_repo.update_step_execution(se)

        if step.job.type == "jenkins":
            logger.info(f"Starting job of type {step.job.type} at path {step.job.path} for step {step.id}")
            try:
                await self.jenkins_service.trigger_job(
                    job_path=step.job.path,
                    step_execution_id=se.id,
                    release_branch=step.release
                )
                return ExecutionStatus.IN_PROGRESS

            except Exception as e:
                logger.error(f"Error starting jenkins job {step.job.path}: {e}")
                se.status = ExecutionStatus.FAILURE
                se.message = str(e)
                await exec_repo.update_step_execution(se)
                return ExecutionStatus.FAILURE
        else:
            logger.warning(f"Job type not supported yet: {step.job.type}")
            se.status = ExecutionStatus.SUCCESS
            await exec_repo.update_step_execution(se)
            return ExecutionStatus.SUCCESS
