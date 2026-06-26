"""
Tests for service layer.
Covers: OrchestratorService, JenkinsService, ReleaseValidationService,
UISettingsService, UIService.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from maestro.schemas.enums import ExecutionStatus
from maestro.schemas.github import PullRequestDetailSchema, PullRequestSchema
from maestro.schemas.orchestrator import ReleaseConfigSchema
from maestro.services.jenkins import JenkinsService
from maestro.services.orchestrator import OrchestratorService
from maestro.services.settings import KNOWN_SETTINGS, UISettingsService
from maestro.services.ui import UIService, _assemble_stages, _build_snapshot
from maestro.services.validation import ReleaseValidationService
from tests.conftest import SAMPLE_RELEASE_YAML, SAMPLE_RELEASE_YAML_UAT

# ===========================================================================
# OrchestratorService
# ===========================================================================


class TestOrchestratorServiceSaveDescriptor:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    @patch("maestro.services.orchestrator.ReleaseValidationService")
    async def test_save_descriptor_success(self, mock_validation_cls, service):
        mock_validation = AsyncMock()
        mock_validation_cls.return_value = mock_validation
        mock_validation.validate = AsyncMock()

        service.repository.get_by_name = AsyncMock(return_value=None)
        service.repository.add = AsyncMock(return_value=MagicMock(id=1, name="test-release"))

        result = await service.save_descriptor(SAMPLE_RELEASE_YAML)

        mock_validation.validate.assert_awaited_once()
        service.repository.add.assert_awaited_once()
        assert result.id == 1

    async def test_save_descriptor_invalid_yaml(self, service):
        with pytest.raises(ValueError, match="Erro de validação"):
            await service.save_descriptor("not: valid: yaml: {{{")

    async def test_save_descriptor_invalid_schema(self, service):
        invalid_yaml = "apiVersion: v1\nkind: NotRelease\nmetadata:\n  name: x\n  author: y\nspec:\n  stages: []\n"
        with pytest.raises(ValueError, match="Erro de validação"):
            await service.save_descriptor(invalid_yaml)

    @patch("maestro.services.orchestrator.ReleaseValidationService")
    async def test_save_descriptor_duplicate_name(self, mock_validation_cls, service):
        from sqlalchemy.exc import IntegrityError

        mock_validation_cls.return_value.validate = AsyncMock()
        service.repository.get_by_name = AsyncMock(return_value=None)
        service.repository.add = AsyncMock(side_effect=IntegrityError("", "", Exception()))

        with pytest.raises(ValueError, match="Já existe"):
            await service.save_descriptor(SAMPLE_RELEASE_YAML)


class TestOrchestratorServiceDryRun:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.JenkinsIntegration")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_dry_run_not_found(self, mock_github_cls, mock_jenkins_cls, mock_get_settings, service):
        service.repository.get_by_name = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="não encontrado"):
            await service.dry_run_release("nonexistent")

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.JenkinsIntegration")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_dry_run_all_valid(self, mock_github_cls, mock_jenkins_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )
        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_name = AsyncMock(return_value=descriptor)

        mock_github = AsyncMock()
        mock_github.branch_exists.return_value = True
        mock_github.get_pull_request_by_branch.return_value = PullRequestSchema(number=1, state="open", title="PR")
        mock_github.get_pull_request_details.return_value = PullRequestDetailSchema(
            number=1, state="open", title="PR", mergeable_state="clean", mergeable=True
        )
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = True
        mock_jenkins_cls.return_value = mock_jenkins

        result = await service.dry_run_release("test-release")

        assert result.valid is True
        assert result.name == "test-release"
        assert len(result.stages) == 1
        step = result.stages[0].steps[0]
        assert step.branch_exists is True
        assert step.pr_found is True
        assert step.pr_is_clean is True
        assert step.jenkins_job_exists is True

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.JenkinsIntegration")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_dry_run_branch_not_found(self, mock_github_cls, mock_jenkins_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )
        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_name = AsyncMock(return_value=descriptor)

        mock_github = AsyncMock()
        mock_github.branch_exists.return_value = False
        mock_github.get_pull_request_by_branch.return_value = None
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = True
        mock_jenkins_cls.return_value = mock_jenkins

        result = await service.dry_run_release("test-release")
        assert result.valid is False
        assert result.stages[0].steps[0].branch_exists is False

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.JenkinsIntegration")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_dry_run_jenkins_not_found(self, mock_github_cls, mock_jenkins_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )
        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_name = AsyncMock(return_value=descriptor)

        mock_github = AsyncMock()
        mock_github.branch_exists.return_value = True
        mock_github.get_pull_request_by_branch.return_value = PullRequestSchema(number=1, state="open", title="PR")
        mock_github.get_pull_request_details.return_value = PullRequestDetailSchema(
            number=1, state="open", title="PR", mergeable_state="clean", mergeable=True
        )
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = False
        mock_jenkins_cls.return_value = mock_jenkins

        result = await service.dry_run_release("test-release")
        assert result.valid is False
        assert result.stages[0].steps[0].jenkins_job_exists is False

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.JenkinsIntegration")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_dry_run_uat_valid_without_pr(self, mock_github_cls, mock_jenkins_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )
        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML_UAT
        service.repository.get_by_name = AsyncMock(return_value=descriptor)

        mock_github = AsyncMock()
        mock_github.branch_exists.return_value = True
        mock_github.get_pull_request_by_branch.return_value = None
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = True
        mock_jenkins_cls.return_value = mock_jenkins

        result = await service.dry_run_release("test-release")

        assert result.valid is True
        assert result.environment == "UAT"
        step = result.stages[0].steps[0]
        assert step.branch_exists is True
        assert step.pr_found is False
        assert step.jenkins_job_exists is True

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.JenkinsIntegration")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_dry_run_prd_invalid_without_pr(self, mock_github_cls, mock_jenkins_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )
        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_name = AsyncMock(return_value=descriptor)

        mock_github = AsyncMock()
        mock_github.branch_exists.return_value = True
        mock_github.get_pull_request_by_branch.return_value = None
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = True
        mock_jenkins_cls.return_value = mock_jenkins

        result = await service.dry_run_release("test-release")

        assert result.valid is False
        assert result.environment == "PRD"
        step = result.stages[0].steps[0]
        assert step.branch_exists is True
        assert step.pr_found is False
        assert step.jenkins_job_exists is True


class TestOrchestratorServiceExecuteRelease:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_execute_not_found(self, mock_github_cls, mock_get_settings, service):
        service.repository.get_by_name = AsyncMock(return_value=None)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="não encontrado"):
            await service.execute_release("nonexistent", background_tasks)

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_execute_duplicate(self, mock_github_cls, mock_get_settings, service):
        service.repository.get_by_name = AsyncMock(return_value=MagicMock())
        active_mock = MagicMock()
        active_mock.id = 99
        active_mock.status = ExecutionStatus.IN_PROGRESS
        service.execution_repo.get_active_execution_by_name = AsyncMock(return_value=active_mock)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="Já existe"):
            await service.execute_release("test-release", background_tasks)

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_execute_success(self, mock_github_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
        )
        descriptor = MagicMock()
        descriptor.id = 1
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_name = AsyncMock(return_value=descriptor)
        service.execution_repo.get_active_execution_by_name = AsyncMock(return_value=None)

        exec_mock = MagicMock()
        exec_mock.id = 42
        service.execution_repo.add_release_execution = AsyncMock(return_value=exec_mock)
        service.execution_repo.add_step_execution = AsyncMock()

        mock_github = AsyncMock()
        mock_github.get_pull_request_by_branch.return_value = PullRequestSchema(number=1, state="open", title="PR")
        mock_github.get_pull_request_details.return_value = PullRequestDetailSchema(
            number=1, state="open", title="PR", mergeable_state="clean", mergeable=True
        )
        mock_github_cls.return_value = mock_github

        background_tasks = MagicMock()
        result = await service.execute_release("test-release", background_tasks)

        assert result == 42
        background_tasks.add_task.assert_called_once()

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_execute_pr_not_clean_fails(self, mock_github_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
        )
        descriptor = MagicMock()
        descriptor.id = 1
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_name = AsyncMock(return_value=descriptor)
        service.execution_repo.get_active_execution_by_name = AsyncMock(return_value=None)

        exec_mock = MagicMock()
        exec_mock.id = 1
        exec_mock.status = ExecutionStatus.PENDING
        service.execution_repo.add_release_execution = AsyncMock(return_value=exec_mock)
        service.execution_repo.update_release_execution = AsyncMock()

        mock_github = AsyncMock()
        mock_github.get_pull_request_by_branch.return_value = PullRequestSchema(number=1, state="open", title="PR")
        mock_github.get_pull_request_details.return_value = PullRequestDetailSchema(
            number=1, state="open", title="PR", mergeable_state="dirty", mergeable=False
        )
        mock_github_cls.return_value = mock_github

        background_tasks = MagicMock()
        with pytest.raises(ValueError, match="não está no estado 'clean'"):
            await service.execute_release("test-release", background_tasks)


class TestOrchestratorServiceExecuteReleaseUAT:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_execute_uat_skips_pr_validation(self, mock_github_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
        )
        descriptor = MagicMock()
        descriptor.id = 1
        descriptor.yaml = SAMPLE_RELEASE_YAML_UAT
        service.repository.get_by_name = AsyncMock(return_value=descriptor)
        service.execution_repo.get_active_execution_by_name = AsyncMock(return_value=None)

        exec_mock = MagicMock()
        exec_mock.id = 42
        service.execution_repo.add_release_execution = AsyncMock(return_value=exec_mock)
        service.execution_repo.add_step_execution = AsyncMock()

        mock_github = AsyncMock()
        mock_github_cls.return_value = mock_github

        background_tasks = MagicMock()
        result = await service.execute_release("test-release", background_tasks)

        assert result == 42
        mock_github.get_pull_request_by_branch.assert_not_called()
        background_tasks.add_task.assert_called_once()

    @patch("maestro.services.app_settings.get_integration_settings")
    @patch("maestro.services.orchestrator.GithubIntegration")
    async def test_execute_prd_still_validates_pr(self, mock_github_cls, mock_get_settings, service):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
        )
        descriptor = MagicMock()
        descriptor.id = 1
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_name = AsyncMock(return_value=descriptor)
        service.execution_repo.get_active_execution_by_name = AsyncMock(return_value=None)

        exec_mock = MagicMock()
        exec_mock.id = 42
        service.execution_repo.add_release_execution = AsyncMock(return_value=exec_mock)
        service.execution_repo.add_step_execution = AsyncMock()

        mock_github = AsyncMock()
        mock_github.get_pull_request_by_branch.return_value = PullRequestSchema(number=1, state="open", title="PR")
        mock_github.get_pull_request_details.return_value = PullRequestDetailSchema(
            number=1, state="open", title="PR", mergeable_state="clean", mergeable=True
        )
        mock_github_cls.return_value = mock_github

        background_tasks = MagicMock()
        result = await service.execute_release("test-release", background_tasks)

        assert result == 42
        mock_github.get_pull_request_by_branch.assert_called_once()
        background_tasks.add_task.assert_called_once()


class TestOrchestratorServiceCancelExecution:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    async def test_cancel_not_found(self, service):
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="não encontrada"):
            await service.cancel_execution(999)

    async def test_cancel_already_terminal(self, service):
        execution = MagicMock()
        execution.status = ExecutionStatus.SUCCESS
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        with pytest.raises(ValueError, match="terminal"):
            await service.cancel_execution(1)

    async def test_cancel_maestro_only(self, service):
        execution = MagicMock()
        execution.id = 1
        execution.status = ExecutionStatus.IN_PROGRESS
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)
        service.execution_repo.update_release_execution = AsyncMock()

        result = await service.cancel_execution(1, abort_jobs=False)

        assert result.status == ExecutionStatus.ABORTED
        assert "manualmente" in result.message
        service.jenkins_service.abort_build.assert_not_awaited()

    async def test_cancel_with_abort_jobs(self, service):
        execution = MagicMock()
        execution.id = 1
        execution.status = ExecutionStatus.IN_PROGRESS
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)
        service.execution_repo.update_release_execution = AsyncMock()
        service.execution_repo.update_step_execution = AsyncMock()

        step_active = MagicMock()
        step_active.status = ExecutionStatus.IN_PROGRESS
        step_active.job_execution_correlation_id = 100
        step_active.release_execution_id = 1
        step_active.stage_id = "stage-1"
        step_active.step_id = "step-1"

        step_pending = MagicMock()
        step_pending.status = ExecutionStatus.PENDING
        step_pending.job_execution_correlation_id = None

        service.execution_repo.get_steps_by_execution_id = AsyncMock(return_value=[step_active, step_pending])

        # Mock _resolve_job_path
        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        service.jenkins_service.abort_build = AsyncMock()

        result = await service.cancel_execution(1, abort_jobs=True)

        assert result.status == ExecutionStatus.ABORTED
        assert "1 job(s)" in result.message
        assert step_active.status == ExecutionStatus.ABORTED
        service.jenkins_service.abort_build.assert_awaited_once_with("job/path/deploy", 100)
        # The pending step without correlation_id should NOT be aborted
        assert step_pending.status == ExecutionStatus.PENDING

    async def test_cancel_with_abort_jenkins_error_continues(self, service):
        """If Jenkins abort fails for one step, the execution is still cancelled."""
        execution = MagicMock()
        execution.id = 1
        execution.status = ExecutionStatus.IN_PROGRESS
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)
        service.execution_repo.update_release_execution = AsyncMock()
        service.execution_repo.update_step_execution = AsyncMock()

        step = MagicMock()
        step.status = ExecutionStatus.IN_PROGRESS
        step.job_execution_correlation_id = 100
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        service.execution_repo.get_steps_by_execution_id = AsyncMock(return_value=[step])

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        service.jenkins_service.abort_build = AsyncMock(side_effect=Exception("Connection refused"))

        result = await service.cancel_execution(1, abort_jobs=True)

        # Execution still cancelled despite Jenkins error
        assert result.status == ExecutionStatus.ABORTED
        # Step still marked aborted even though Jenkins call failed
        assert step.status == ExecutionStatus.ABORTED


class TestOrchestratorServiceRetryStep:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    async def test_retry_step_not_found(self, service):
        service.execution_repo.get_step_by_id = AsyncMock(return_value=None)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="não encontrado"):
            await service.retry_step(999, background_tasks)

    async def test_retry_step_wrong_status(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.SUCCESS
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="Só é possível reexecutar"):
            await service.retry_step(1, background_tasks)

    async def test_retry_step_success(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.FAILURE
        step.release_execution_id = 10
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        service.execution_repo.update_step_execution = AsyncMock()

        execution = MagicMock()
        execution.status = ExecutionStatus.FAILURE
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)
        service.execution_repo.update_release_execution = AsyncMock()

        background_tasks = MagicMock()
        result = await service.retry_step(1, background_tasks)

        assert result.status == ExecutionStatus.PENDING
        background_tasks.add_task.assert_called_once()


class TestOrchestratorServiceApproveRelease:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    async def test_approve_not_found(self, service):
        service.execution_repo.get_latest_execution_by_name = AsyncMock(return_value=None)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="Nenhuma execução encontrada"):
            await service.approve_release("no-exist", background_tasks)

    async def test_approve_wrong_status(self, service):
        execution = MagicMock()
        execution.status = ExecutionStatus.IN_PROGRESS
        service.execution_repo.get_latest_execution_by_name = AsyncMock(return_value=execution)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="não está aguardando aprovação"):
            await service.approve_release("test", background_tasks)

    async def test_approve_success(self, service):
        execution = MagicMock()
        execution.id = 1
        execution.status = ExecutionStatus.WAITING_APPROVAL
        execution.orchestrator_descriptor_id = 1
        service.execution_repo.get_latest_execution_by_name = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        step_exec = MagicMock()
        step_exec.id = 10
        step_exec.stage_id = "stage-1"
        step_exec.step_id = "step-1"
        step_exec.status = ExecutionStatus.WAITING_APPROVAL
        step_exec.job_execution_correlation_id = 42
        step_exec.job_input_id = "input-1"
        service.execution_repo.get_steps_by_execution_id = AsyncMock(return_value=[step_exec])
        service.execution_repo.update_step_execution = AsyncMock()
        service.execution_repo.update_release_execution = AsyncMock()

        service.jenkins_service.approve_job = AsyncMock()

        background_tasks = MagicMock()
        result = await service.approve_release("test-release", background_tasks)

        assert "Aprovação enviada" in result["message"]
        assert 10 in result["approved_steps"]
        service.jenkins_service.approve_job.assert_awaited_once()


# ===========================================================================
# JenkinsService
# ===========================================================================


class TestJenkinsService:
    @pytest.fixture
    def service(self):
        svc = JenkinsService.__new__(JenkinsService)
        svc.execution_repo = AsyncMock()
        svc._jenkins_integration = AsyncMock()
        return svc

    @patch("maestro.services.jenkins.asyncio.create_task")
    async def test_trigger_job(self, mock_create_task, service):
        service._jenkins_integration.trigger_job_and_get_queue_url = AsyncMock(
            return_value="http://jenkins/queue/item/1"
        )

        await service.trigger_job("job/path", step_execution_id=5, release_branch="feature/x")

        service._jenkins_integration.trigger_job_and_get_queue_url.assert_awaited_once_with(
            "job/path", parameters={"BRANCH": "feature/x"}
        )
        mock_create_task.assert_called_once()

    async def test_approve_job(self, service):
        service._jenkins_integration.approve_pipeline = AsyncMock()

        await service.approve_job("job/deploy", build_number=42, input_id="input-1", status="Sucesso")

        service._jenkins_integration.approve_pipeline.assert_awaited_once_with(
            "job/deploy", 42, "input-1", status="Sucesso"
        )


# ===========================================================================
# ReleaseValidationService
# ===========================================================================


class TestReleaseValidationService:
    @patch("maestro.services.validation.get_integration_settings", new_callable=AsyncMock)
    @patch("maestro.services.validation.JenkinsIntegration")
    @patch("maestro.services.validation.GithubIntegration")
    async def test_validate_all_pass(self, mock_github_cls, mock_jenkins_cls, mock_get_settings):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )

        mock_github = AsyncMock()
        mock_github.repository_exists.return_value = True
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = True
        mock_jenkins_cls.return_value = mock_jenkins

        config = ReleaseConfigSchema(**yaml.safe_load(SAMPLE_RELEASE_YAML))
        svc = ReleaseValidationService()
        # Should not raise
        await svc.validate(config)

    @patch("maestro.services.validation.get_integration_settings", new_callable=AsyncMock)
    @patch("maestro.services.validation.JenkinsIntegration")
    @patch("maestro.services.validation.GithubIntegration")
    async def test_validate_branch_not_found(self, mock_github_cls, mock_jenkins_cls, mock_get_settings):
        """Repository not found raises error (branch validation removed)."""
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )

        mock_github = AsyncMock()
        mock_github.repository_exists.return_value = False
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = True
        mock_jenkins_cls.return_value = mock_jenkins

        config = ReleaseConfigSchema(**yaml.safe_load(SAMPLE_RELEASE_YAML))
        svc = ReleaseValidationService()

        with pytest.raises(ValueError, match="Repositório.*não encontrado"):
            await svc.validate(config)

    @patch("maestro.services.validation.get_integration_settings", new_callable=AsyncMock)
    @patch("maestro.services.validation.JenkinsIntegration")
    @patch("maestro.services.validation.GithubIntegration")
    async def test_validate_jenkins_job_not_found(self, mock_github_cls, mock_jenkins_cls, mock_get_settings):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )

        mock_github = AsyncMock()
        mock_github.repository_exists.return_value = True
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = False
        mock_jenkins_cls.return_value = mock_jenkins

        config = ReleaseConfigSchema(**yaml.safe_load(SAMPLE_RELEASE_YAML))
        svc = ReleaseValidationService()

        with pytest.raises(ValueError, match="Job.*não encontrado"):
            await svc.validate(config)

    @patch("maestro.services.validation.get_integration_settings", new_callable=AsyncMock)
    @patch("maestro.services.validation.JenkinsIntegration")
    @patch("maestro.services.validation.GithubIntegration")
    async def test_validate_multiple_errors(self, mock_github_cls, mock_jenkins_cls, mock_get_settings):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )

        mock_github = AsyncMock()
        mock_github.repository_exists.return_value = False
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = False
        mock_jenkins_cls.return_value = mock_jenkins

        config = ReleaseConfigSchema(**yaml.safe_load(SAMPLE_RELEASE_YAML))
        svc = ReleaseValidationService()

        with pytest.raises(ValueError) as exc_info:
            await svc.validate(config)

        error_msg = str(exc_info.value)
        assert "Repositório" in error_msg
        assert "Job" in error_msg

    @patch("maestro.services.validation.get_integration_settings", new_callable=AsyncMock)
    @patch("maestro.services.validation.JenkinsIntegration")
    @patch("maestro.services.validation.GithubIntegration")
    async def test_validate_github_exception_treated_as_not_found(
        self, mock_github_cls, mock_jenkins_cls, mock_get_settings
    ):
        mock_get_settings.return_value = MagicMock(
            github_organization="org",
            github_token="t",
            github_base_url=None,
            http_trust_env=True,
            jenkins_url="http://j:8080",
            jenkins_username="u",
            jenkins_token="t",
        )

        mock_github = AsyncMock()
        mock_github.repository_exists.side_effect = Exception("connection error")
        mock_github_cls.return_value = mock_github

        mock_jenkins = AsyncMock()
        mock_jenkins.job_exists.return_value = True
        mock_jenkins_cls.return_value = mock_jenkins

        config = ReleaseConfigSchema(**yaml.safe_load(SAMPLE_RELEASE_YAML))
        svc = ReleaseValidationService()

        with pytest.raises(ValueError, match="Repositório.*não encontrado"):
            await svc.validate(config)


# ===========================================================================
# UISettingsService
# ===========================================================================


class TestUISettingsService:
    @pytest.fixture
    def service(self):
        svc = UISettingsService.__new__(UISettingsService)
        svc.repo = AsyncMock()
        return svc

    async def test_get_all(self, service):
        service.repo.get_all = AsyncMock(return_value={"jenkins_base_url": "http://j:8080"})
        result = await service.get_all()

        # Should return all known keys, filling missing ones with None
        for key in KNOWN_SETTINGS:
            assert key in result

    async def test_get(self, service):
        service.repo.get = AsyncMock(return_value="http://jenkins:8080")
        result = await service.get("jenkins_base_url")
        assert result == "http://jenkins:8080"

    async def test_save_filters_unknown_keys(self, service):
        service.repo.upsert_many = AsyncMock()
        data = {
            "jenkins_base_url": "http://j:8080",
            "unknown_key": "should_be_filtered",
            "github_base_url": "https://github.com",
        }
        await service.save(data)

        call_args = service.repo.upsert_many.call_args[0][0]
        assert "unknown_key" not in call_args
        assert "jenkins_base_url" in call_args
        assert "github_base_url" in call_args


# ===========================================================================
# UIService
# ===========================================================================


class TestUIService:
    @pytest.fixture
    def service(self):
        svc = UIService.__new__(UIService)
        svc.execution_repo = AsyncMock()
        svc.orchestrator_repo = AsyncMock()
        return svc

    async def test_get_all_executions(self, service):
        service.execution_repo.get_all_executions = AsyncMock(return_value=[MagicMock(), MagicMock()])
        result = await service.get_all_executions()
        assert len(result) == 2

    async def test_get_execution_with_stages_not_found(self, service):
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=None)
        result = await service.get_execution_with_stages(999)
        assert result is None

    async def test_get_execution_with_stages_found(self, service):
        execution = MagicMock()
        execution.id = 1
        execution.orchestrator_descriptor_id = 1
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.orchestrator_repo.get_by_id = AsyncMock(return_value=descriptor)

        step = MagicMock()
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        step.status = ExecutionStatus.SUCCESS
        service.execution_repo.get_steps_by_execution_id = AsyncMock(return_value=[step])
        service.execution_repo.get_action_logs_by_execution_id = AsyncMock(return_value=[])

        result = await service.get_execution_with_stages(1)
        assert result is not None
        exec_result, stages, action_logs = result
        assert exec_result == execution
        assert len(stages) == 1
        assert stages[0]["id"] == "stage-1"
        assert action_logs == []


class TestExecutionSSEStreamCloseEvent:
    """Tests that SSE stream emits a 'close' event when execution reaches a terminal status."""

    @pytest.fixture
    def service(self):
        svc = UIService.__new__(UIService)
        svc.execution_repo = AsyncMock()
        svc.orchestrator_repo = AsyncMock()
        return svc

    async def test_emits_close_event_on_terminal_status(self, service):
        """When execution status is terminal, stream should yield a close event after stage-update."""
        execution = MagicMock()
        execution.id = 1
        execution.status = ExecutionStatus.SUCCESS
        execution.orchestrator_descriptor_id = 1

        step = MagicMock()
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        step.status = ExecutionStatus.SUCCESS

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_scoped_service = AsyncMock()
        mock_scoped_service.get_execution_with_stages = AsyncMock(
            return_value=(execution, [{"id": "stage-1", "steps": [{"execution": step}]}], [])
        )

        mock_settings_repo = AsyncMock()
        mock_settings_repo.get = AsyncMock(return_value="")

        with patch("maestro.database.session.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("maestro.repositories.settings.UISettingsRepository", return_value=mock_settings_repo), \
             patch("maestro.services.ui.ExecutionRepository"), \
             patch("maestro.services.ui.OrchestratorDescriptorRepository"), \
             patch("maestro.services.ui.UIService", return_value=mock_scoped_service), \
             patch("maestro.services.ui._render_partial", return_value="<div>html</div>"):
            events = []
            async for event in service.execution_sse_stream(1):
                events.append(event)

        # Should emit stage-update followed by close
        assert len(events) == 2
        assert events[0]["event"] == "stage-update"
        assert events[1] == {"event": "close", "data": ""}

    async def test_emits_close_event_for_failure_status(self, service):
        """Close event is emitted for FAILURE status as well."""
        execution = MagicMock()
        execution.id = 2
        execution.status = ExecutionStatus.FAILURE
        execution.orchestrator_descriptor_id = 1

        step = MagicMock()
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        step.status = ExecutionStatus.FAILURE

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_scoped_service = AsyncMock()
        mock_scoped_service.get_execution_with_stages = AsyncMock(
            return_value=(execution, [{"id": "stage-1", "steps": [{"execution": step}]}], [])
        )

        mock_settings_repo = AsyncMock()
        mock_settings_repo.get = AsyncMock(return_value="")

        with patch("maestro.database.session.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("maestro.repositories.settings.UISettingsRepository", return_value=mock_settings_repo), \
             patch("maestro.services.ui.ExecutionRepository"), \
             patch("maestro.services.ui.OrchestratorDescriptorRepository"), \
             patch("maestro.services.ui.UIService", return_value=mock_scoped_service), \
             patch("maestro.services.ui._render_partial", return_value="<div>html</div>"):
            events = []
            async for event in service.execution_sse_stream(2):
                events.append(event)

        assert any(e == {"event": "close", "data": ""} for e in events)


class TestAssembleStages:
    async def test_assemble_stages_basic(self):
        config = ReleaseConfigSchema(**yaml.safe_load(SAMPLE_RELEASE_YAML))
        step = MagicMock()
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        step.status = ExecutionStatus.PENDING

        registry_repo = MagicMock()
        result = await _assemble_stages(config, [step], registry_repo)
        assert len(result) == 1
        assert result[0]["id"] == "stage-1"
        assert len(result[0]["steps"]) == 1
        assert result[0]["steps"][0]["repository"] == "my-repo"
        assert result[0]["steps"][0]["job_path"] == "job/path/deploy"

    async def test_assemble_stages_no_matching_steps(self):
        config = ReleaseConfigSchema(**yaml.safe_load(SAMPLE_RELEASE_YAML))
        # Step with mismatched IDs
        step = MagicMock()
        step.stage_id = "stage-99"
        step.step_id = "step-99"

        registry_repo = MagicMock()
        result = await _assemble_stages(config, [step], registry_repo)
        assert len(result) == 1
        assert result[0]["steps"] == []


class TestBuildSnapshot:
    def test_snapshot_format(self):
        stages = [
            {
                "id": "stage-1",
                "steps": [
                    {"execution": MagicMock(step_id="step-1", status="pending")},
                ],
            }
        ]
        snapshot = _build_snapshot(stages, "pending")
        assert "stage-1" in snapshot
        assert "step-1" in snapshot
        assert "pending" in snapshot

    def test_snapshot_changes_with_status(self):
        def make_stages(status):
            return [
                {
                    "id": "stage-1",
                    "steps": [
                        {"execution": MagicMock(step_id="step-1", status=status)},
                    ],
                }
            ]

        s1 = _build_snapshot(make_stages("pending"), "pending")
        s2 = _build_snapshot(make_stages("success"), "success")
        assert s1 != s2
