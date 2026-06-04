"""
Tests for the two new step-level UI actions:
- POST /ui/step/{id}/abort  (force cancel via Jenkins)
- POST /ui/step/{id}/approve (approve individual step via Jenkins)
Also covers the new JenkinsIntegration.abort_build and JenkinsService.abort_build methods.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
import httpx

from maestro.database.session import get_db
from maestro.schemas.enums import ExecutionStatus
from maestro.database.models import ReleaseExecution, ReleaseStepExecution, OrchestratorDescriptor
from maestro.integration.jenkins import JenkinsIntegration
from maestro.services.jenkins import JenkinsService


SAMPLE_YAML = """\
apiVersion: v1
kind: Release
metadata:
  name: test-release
  author: tester
spec:
  stages:
    - id: stage-1
      steps:
        - id: step-1
          repository: my-repo
          release: feature/branch-1
          job:
            type: jenkins
            path: job/path/deploy
"""


# ===========================================================================
# Fixtures
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


def _make_step(
    id=1,
    status=ExecutionStatus.IN_PROGRESS,
    correlation_id=100,
    input_id=None,
    release_execution_id=1,
    stage_id="stage-1",
    step_id="step-1",
):
    step = MagicMock(spec=ReleaseStepExecution)
    step.id = id
    step.status = status
    step.job_execution_correlation_id = correlation_id
    step.job_input_id = input_id
    step.release_execution_id = release_execution_id
    step.stage_id = stage_id
    step.step_id = step_id
    step.message = None
    return step


def _make_execution(id=1, descriptor_id=1):
    execution = MagicMock(spec=ReleaseExecution)
    execution.id = id
    execution.orchestrator_descriptor_id = descriptor_id
    return execution


def _make_descriptor(id=1, yaml_content=SAMPLE_YAML):
    descriptor = MagicMock(spec=OrchestratorDescriptor)
    descriptor.id = id
    descriptor.yaml = yaml_content
    return descriptor


def _setup_mocks_for_step_action(mock_session, step, execution=None, descriptor=None):
    """Helper to setup mock_session.execute to return step, execution, descriptor in sequence."""
    if execution is None:
        execution = _make_execution()
    if descriptor is None:
        descriptor = _make_descriptor()

    # get_step_by_id → step
    # get_execution_by_id → execution
    # get_by_id (descriptor) → descriptor
    step_result = MagicMock()
    step_result.scalars.return_value.first.return_value = step

    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = execution

    desc_result = MagicMock()
    desc_result.scalars.return_value.first.return_value = descriptor

    mock_session.execute.side_effect = [step_result, exec_result, desc_result]


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
        svc.jenkins_integration = AsyncMock()
        return svc

    async def test_abort_build_delegates(self, service):
        service.jenkins_integration.abort_build = AsyncMock()

        await service.abort_build("job/path", 42)

        service.jenkins_integration.abort_build.assert_awaited_once_with("job/path", 42)


# ===========================================================================
# POST /ui/step/{id}/abort
# ===========================================================================

class TestAbortStepUI:
    @patch("maestro.services.jenkins.JenkinsIntegration.abort_build", new_callable=AsyncMock)
    async def test_abort_step_not_found(self, mock_abort, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/999/abort")
        assert response.status_code == 200
        assert "não encontrado" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.abort_build", new_callable=AsyncMock)
    async def test_abort_step_already_terminal(self, mock_abort, client, mock_session):
        step = _make_step(status=ExecutionStatus.SUCCESS)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/abort")
        assert response.status_code == 200
        assert "terminal" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.abort_build", new_callable=AsyncMock)
    async def test_abort_step_no_correlation_id(self, mock_abort, client, mock_session):
        step = _make_step(correlation_id=None)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/abort")
        assert response.status_code == 200
        assert "correlation_id" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.abort_build", new_callable=AsyncMock)
    async def test_abort_step_success(self, mock_abort, client, mock_session):
        step = _make_step(status=ExecutionStatus.IN_PROGRESS, correlation_id=100)
        execution = _make_execution()
        descriptor = _make_descriptor()
        _setup_mocks_for_step_action(mock_session, step, execution, descriptor)

        response = await client.post("/ui/step/1/abort")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.ABORTED
        assert "abortado" in response.text.lower()
        mock_abort.assert_awaited_once_with("job/path/deploy", 100)

    @patch("maestro.services.jenkins.JenkinsIntegration.abort_build", new_callable=AsyncMock)
    async def test_abort_step_jenkins_error(self, mock_abort, client, mock_session):
        mock_abort.side_effect = Exception("Connection refused")
        step = _make_step(status=ExecutionStatus.IN_PROGRESS, correlation_id=100)
        execution = _make_execution()
        descriptor = _make_descriptor()
        _setup_mocks_for_step_action(mock_session, step, execution, descriptor)

        response = await client.post("/ui/step/1/abort")
        assert response.status_code == 200
        assert "erro" in response.text.lower()
        assert "jenkins" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.abort_build", new_callable=AsyncMock)
    async def test_abort_step_waiting_approval(self, mock_abort, client, mock_session):
        """Abort should also work for steps in waiting_approval status."""
        step = _make_step(status=ExecutionStatus.WAITING_APPROVAL, correlation_id=55)
        execution = _make_execution()
        descriptor = _make_descriptor()
        _setup_mocks_for_step_action(mock_session, step, execution, descriptor)

        response = await client.post("/ui/step/1/abort")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.ABORTED
        mock_abort.assert_awaited_once_with("job/path/deploy", 55)


# ===========================================================================
# POST /ui/step/{id}/approve
# ===========================================================================

class TestApproveStepUI:
    @patch("maestro.services.jenkins.JenkinsIntegration.approve_pipeline", new_callable=AsyncMock)
    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_approve_step_not_found(self, mock_workflow, mock_approve, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/999/approve")
        assert response.status_code == 200
        assert "não encontrado" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.approve_pipeline", new_callable=AsyncMock)
    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_approve_step_wrong_status(self, mock_workflow, mock_approve, client, mock_session):
        step = _make_step(status=ExecutionStatus.IN_PROGRESS, input_id="inp-1")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert "não está aguardando" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.approve_pipeline", new_callable=AsyncMock)
    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_approve_step_no_input_id(self, mock_workflow, mock_approve, client, mock_session):
        step = _make_step(status=ExecutionStatus.WAITING_APPROVAL, input_id=None, correlation_id=42)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert "input_id" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.approve_pipeline", new_callable=AsyncMock)
    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_approve_step_no_correlation_id(self, mock_workflow, mock_approve, client, mock_session):
        step = _make_step(status=ExecutionStatus.WAITING_APPROVAL, input_id="inp-1", correlation_id=None)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert "correlation_id" in response.text.lower()

    @patch("maestro.services.jenkins.JenkinsIntegration.approve_pipeline", new_callable=AsyncMock)
    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_approve_step_success(self, mock_workflow, mock_approve, client, mock_session):
        step = _make_step(
            status=ExecutionStatus.WAITING_APPROVAL,
            input_id="input-abc",
            correlation_id=42,
        )
        execution = _make_execution()
        descriptor = _make_descriptor()
        _setup_mocks_for_step_action(mock_session, step, execution, descriptor)

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.IN_PROGRESS
        assert "aprovado" in response.text.lower()
        mock_approve.assert_awaited_once_with("job/path/deploy", 42, "input-abc", status="Sucesso")

    @patch("maestro.services.jenkins.JenkinsIntegration.approve_pipeline", new_callable=AsyncMock)
    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_approve_step_jenkins_error(self, mock_workflow, mock_approve, client, mock_session):
        mock_approve.side_effect = Exception("Jenkins unreachable")
        step = _make_step(
            status=ExecutionStatus.WAITING_APPROVAL,
            input_id="input-abc",
            correlation_id=42,
        )
        execution = _make_execution()
        descriptor = _make_descriptor()
        _setup_mocks_for_step_action(mock_session, step, execution, descriptor)

        response = await client.post("/ui/step/1/approve")
        assert response.status_code == 200
        assert "erro" in response.text.lower()
        assert "jenkins" in response.text.lower()
