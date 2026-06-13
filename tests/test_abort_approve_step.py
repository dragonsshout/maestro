"""
Tests for abort_step and approve_step features.

Covers:
- OrchestratorService.abort_step (unit tests)
- OrchestratorService.approve_step (unit tests)
- OrchestratorService._resolve_job_path (unit tests)
- JenkinsIntegration.abort_build (integration client)
- JenkinsService.abort_build (service delegation)
- POST /ui/step/{id}/abort (thin route test)
- POST /ui/step/{id}/approve (thin route test)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from maestro.database.session import get_db
from maestro.integration.jenkins import JenkinsIntegration
from maestro.schemas.enums import ExecutionStatus
from maestro.services.jenkins import JenkinsService
from maestro.services.orchestrator import OrchestratorService
from tests.conftest import SAMPLE_RELEASE_YAML

# ===========================================================================
# JenkinsIntegration.abort_build
# ===========================================================================


class TestJenkinsIntegrationAbortBuild:
    @pytest.fixture
    def jenkins(self):
        return JenkinsIntegration(
            base_url="http://jenkins.local:8080",
            username="admin",
            token="token",
        )

    async def test_abort_build_success(self, jenkins):
        mock_response = httpx.Response(200)
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            await jenkins.abort_build("job/deploy", 42)

    async def test_abort_build_redirect_accepted(self, jenkins):
        mock_response = httpx.Response(302)
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            await jenkins.abort_build("job/deploy", 10)

    async def test_abort_build_error(self, jenkins):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                await jenkins.abort_build("job/deploy", 99)


# ===========================================================================
# JenkinsService.abort_build
# ===========================================================================


class TestJenkinsServiceAbortBuild:
    @pytest.fixture
    def service(self):
        svc = JenkinsService.__new__(JenkinsService)
        svc.execution_repo = AsyncMock()
        svc._jenkins_integration = AsyncMock()
        return svc

    async def test_abort_build_delegates(self, service):
        service._jenkins_integration.abort_build = AsyncMock()
        await service.abort_build("job/path", 42)
        service._jenkins_integration.abort_build.assert_awaited_once_with("job/path", 42)


# ===========================================================================
# OrchestratorService.abort_step (unit tests)
# ===========================================================================


class TestOrchestratorServiceAbortStep:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    async def test_abort_step_not_found(self, service):
        service.execution_repo.get_step_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="não encontrado"):
            await service.abort_step(999)

    async def test_abort_step_already_terminal_success(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.SUCCESS
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)

        with pytest.raises(ValueError, match="terminal"):
            await service.abort_step(1)

    async def test_abort_step_already_terminal_aborted(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.ABORTED
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)

        with pytest.raises(ValueError, match="terminal"):
            await service.abort_step(1)

    async def test_abort_step_no_correlation_id(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.IN_PROGRESS
        step.job_execution_correlation_id = None
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)

        with pytest.raises(ValueError, match="correlation_id"):
            await service.abort_step(1)

    async def test_abort_step_success(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.IN_PROGRESS
        step.job_execution_correlation_id = 100
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        service.execution_repo.update_step_execution = AsyncMock()

        # Mock _resolve_job_path
        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        service.jenkins_service.abort_build = AsyncMock()

        result = await service.abort_step(1)

        assert result.status == ExecutionStatus.ABORTED
        assert "Cancelamento forçado" in result.message
        service.jenkins_service.abort_build.assert_awaited_once_with("job/path/deploy", 100)
        service.execution_repo.update_step_execution.assert_awaited_once()

    async def test_abort_step_waiting_approval(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.WAITING_APPROVAL
        step.job_execution_correlation_id = 55
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        service.execution_repo.update_step_execution = AsyncMock()

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        service.jenkins_service.abort_build = AsyncMock()

        result = await service.abort_step(1)

        assert result.status == ExecutionStatus.ABORTED
        service.jenkins_service.abort_build.assert_awaited_once_with("job/path/deploy", 55)

    async def test_abort_step_jenkins_error_propagates(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.IN_PROGRESS
        step.job_execution_correlation_id = 100
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        service.jenkins_service.abort_build = AsyncMock(side_effect=Exception("Connection refused"))

        with pytest.raises(Exception, match="Connection refused"):
            await service.abort_step(1)

    async def test_abort_step_no_job_path_found(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.IN_PROGRESS
        step.job_execution_correlation_id = 100
        step.release_execution_id = 1
        step.stage_id = "stage-99"  # doesn't match YAML
        step.step_id = "step-99"

        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        with pytest.raises(ValueError, match="job path"):
            await service.abort_step(1)


# ===========================================================================
# OrchestratorService.approve_step (unit tests)
# ===========================================================================


class TestOrchestratorServiceApproveStep:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    async def test_approve_step_not_found(self, service):
        service.execution_repo.get_step_by_id = AsyncMock(return_value=None)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="não encontrado"):
            await service.approve_step(999, background_tasks)

    async def test_approve_step_wrong_status(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.IN_PROGRESS
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="não está aguardando"):
            await service.approve_step(1, background_tasks)

    async def test_approve_step_no_input_id(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.WAITING_APPROVAL
        step.job_input_id = None
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="input_id"):
            await service.approve_step(1, background_tasks)

    async def test_approve_step_no_correlation_id(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.WAITING_APPROVAL
        step.job_input_id = "inp-1"
        step.job_execution_correlation_id = None
        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        background_tasks = MagicMock()

        with pytest.raises(ValueError, match="correlation_id"):
            await service.approve_step(1, background_tasks)

    async def test_approve_step_success(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.WAITING_APPROVAL
        step.job_input_id = "input-abc"
        step.job_execution_correlation_id = 42
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)
        service.execution_repo.update_step_execution = AsyncMock()

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        service.jenkins_service.approve_job = AsyncMock()

        background_tasks = MagicMock()
        result = await service.approve_step(1, background_tasks)

        assert result.status == ExecutionStatus.IN_PROGRESS
        assert "Aprovação individual" in result.message
        service.jenkins_service.approve_job.assert_awaited_once_with(
            job_path="job/path/deploy",
            build_number=42,
            input_id="input-abc",
            status="Sucesso",
        )
        service.execution_repo.update_step_execution.assert_awaited_once()
        background_tasks.add_task.assert_called_once()

    async def test_approve_step_jenkins_error_propagates(self, service):
        step = MagicMock()
        step.status = ExecutionStatus.WAITING_APPROVAL
        step.job_input_id = "input-abc"
        step.job_execution_correlation_id = 42
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        service.execution_repo.get_step_by_id = AsyncMock(return_value=step)

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        service.jenkins_service.approve_job = AsyncMock(side_effect=Exception("Jenkins unreachable"))

        background_tasks = MagicMock()
        with pytest.raises(Exception, match="Jenkins unreachable"):
            await service.approve_step(1, background_tasks)


# ===========================================================================
# OrchestratorService._resolve_job_path (unit tests)
# ===========================================================================


class TestResolveJobPath:
    @pytest.fixture
    def service(self):
        svc = OrchestratorService.__new__(OrchestratorService)
        svc.repository = AsyncMock()
        svc.execution_repo = AsyncMock()
        svc.jenkins_service = AsyncMock()
        svc.job_path_registry_repo = AsyncMock()
        return svc

    async def test_resolve_job_path_found(self, service):
        step = MagicMock()
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        result = await service._resolve_job_path(step)
        assert result == "job/path/deploy"

    async def test_resolve_job_path_not_found_wrong_ids(self, service):
        step = MagicMock()
        step.release_execution_id = 1
        step.stage_id = "nonexistent-stage"
        step.step_id = "nonexistent-step"

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 10
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)

        descriptor = MagicMock()
        descriptor.yaml = SAMPLE_RELEASE_YAML
        service.repository.get_by_id = AsyncMock(return_value=descriptor)

        result = await service._resolve_job_path(step)
        assert result is None

    async def test_resolve_job_path_execution_not_found(self, service):
        step = MagicMock()
        step.release_execution_id = 999
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=None)

        result = await service._resolve_job_path(step)
        assert result is None

    async def test_resolve_job_path_descriptor_not_found(self, service):
        step = MagicMock()
        step.release_execution_id = 1

        execution = MagicMock()
        execution.orchestrator_descriptor_id = 99
        service.execution_repo.get_execution_by_id = AsyncMock(return_value=execution)
        service.repository.get_by_id = AsyncMock(return_value=None)

        result = await service._resolve_job_path(step)
        assert result is None


# ===========================================================================
# Route tests (thin — only verify delegation and template rendering)
# ===========================================================================


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def app_override(mock_session):
    with patch("subprocess.run"):
        from maestro.main import app

        async def _get_db_override():
            yield mock_session

        app.dependency_overrides[get_db] = _get_db_override
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def client(app_override):
    transport = ASGITransport(app=app_override)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestAbortStepRoute:
    @patch("maestro.services.orchestrator.OrchestratorService.abort_step")
    async def test_abort_route_success(self, mock_abort, client):
        step = MagicMock()
        step.id = 1
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        step.status = ExecutionStatus.ABORTED
        step.message = "Cancelamento forçado enviado ao Jenkins (build #100)."
        mock_abort.return_value = step

        response = await client.post("/ui/step/1/abort")
        assert response.status_code == 200
        assert "abortado" in response.text.lower()

    @patch("maestro.services.orchestrator.OrchestratorService.abort_step")
    async def test_abort_route_value_error(self, mock_abort, client):
        mock_abort.side_effect = ValueError("Step não encontrado.")

        response = await client.post("/ui/step/999/abort")
        assert response.status_code == 200
        assert "não encontrado" in response.text.lower()

    @patch("maestro.services.orchestrator.OrchestratorService.abort_step")
    async def test_abort_route_unexpected_error(self, mock_abort, client):
        mock_abort.side_effect = Exception("Connection refused")

        response = await client.post("/ui/step/1/abort")
        assert response.status_code == 200
        assert "jenkins" in response.text.lower()


class TestApproveStepRoute:
    @patch("maestro.services.orchestrator.OrchestratorService.approve_step")
    async def test_approve_route_success(self, mock_approve, client):
        step = MagicMock()
        step.id = 1
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        step.status = ExecutionStatus.IN_PROGRESS
        step.message = "Aprovação individual enviada ao Jenkins (build #42)."
        mock_approve.return_value = step

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert "aprovado" in response.text.lower()

    @patch("maestro.services.orchestrator.OrchestratorService.approve_step")
    async def test_approve_route_value_error(self, mock_approve, client):
        mock_approve.side_effect = ValueError("Step não está aguardando aprovação.")

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert "não está aguardando" in response.text.lower()

    @patch("maestro.services.orchestrator.OrchestratorService.approve_step")
    async def test_approve_route_unexpected_error(self, mock_approve, client):
        mock_approve.side_effect = Exception("Jenkins unreachable")

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert "jenkins" in response.text.lower()
