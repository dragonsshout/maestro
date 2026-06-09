"""
Tests for UI API routes.
Covers: cancel execution, override step, resolve timeout, retry step via UI,
execute release via UI, dry-run via UI, releases page, settings page.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from maestro.database.session import get_db
from maestro.schemas.enums import ExecutionStatus
from maestro.database.models import ReleaseExecution, ReleaseStepExecution, ExecutionActionLog


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


# ===========================================================================
# Cancel Execution
# ===========================================================================

class TestCancelExecution:
    @patch("maestro.services.orchestrator.OrchestratorService.cancel_execution")
    async def test_cancel_not_found(self, mock_cancel, client, mock_session):
        mock_cancel.side_effect = ValueError("Execução não encontrada.")

        response = await client.post("/ui/execution/999/cancel")
        assert response.status_code == 400

    @patch("maestro.services.orchestrator.OrchestratorService.cancel_execution")
    async def test_cancel_already_terminal(self, mock_cancel, client, mock_session):
        mock_cancel.side_effect = ValueError("Execução já está em status terminal: success")

        response = await client.post("/ui/execution/1/cancel")
        assert response.status_code == 400
        assert "terminal" in response.json()["detail"]

    @patch("maestro.services.orchestrator.OrchestratorService.cancel_execution")
    async def test_cancel_success_maestro_only(self, mock_cancel, client, mock_session):
        execution = MagicMock(spec=ReleaseExecution)
        execution.id = 1
        execution.name = "test-release"
        execution.status = ExecutionStatus.ABORTED
        execution.message = "Cancelado manualmente pelo operador."
        mock_cancel.return_value = execution

        response = await client.post("/ui/execution/1/cancel")
        assert response.status_code == 200
        mock_cancel.assert_awaited_once_with(1, abort_jobs=False)

    @patch("maestro.services.orchestrator.OrchestratorService.cancel_execution")
    async def test_cancel_with_abort_jobs(self, mock_cancel, client, mock_session):
        execution = MagicMock(spec=ReleaseExecution)
        execution.id = 1
        execution.name = "test-release"
        execution.status = ExecutionStatus.ABORTED
        execution.message = "Cancelado com abort de 2 job(s) no Jenkins."
        mock_cancel.return_value = execution

        response = await client.post("/ui/execution/1/cancel?abort_jobs=true")
        assert response.status_code == 200
        mock_cancel.assert_awaited_once_with(1, abort_jobs=True)


# ===========================================================================
# Override Step
# ===========================================================================

class TestOverrideStep:
    async def test_override_invalid_action(self, client):
        response = await client.post("/ui/step/1/override/invalid_action")
        assert response.status_code == 400
        assert "Ação inválida" in response.json()["detail"]

    async def test_override_step_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/999/override/success")
        assert response.status_code == 404

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_override_step_terminal_status(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.SUCCESS
        step.release_execution_id = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/override/failure")
        assert response.status_code == 400
        assert "terminal" in response.json()["detail"]

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_override_step_to_success(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.FAILURE
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/override/success")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.SUCCESS

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_override_step_to_failure(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.IN_PROGRESS
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/override/failure")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.FAILURE

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_override_step_to_waiting_approval(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.IN_PROGRESS
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/step/1/override/waiting_approval")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.WAITING_APPROVAL


# ===========================================================================
# Resolve Timeout
# ===========================================================================

class TestResolveTimeout:
    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_resolve_timeout_step_not_found(self, mock_process, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/resolve-timeout/999?action=success")
        assert response.status_code == 200
        assert "não encontrado" in response.text.lower()

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_resolve_timeout_not_in_timeout_status(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.IN_PROGRESS

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/resolve-timeout/1?action=success")
        assert response.status_code == 200
        assert "não está em timeout" in response.text.lower()

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_resolve_timeout_success(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.TIMEOUT
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/resolve-timeout/1?action=success")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.SUCCESS

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_resolve_timeout_failure(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.TIMEOUT
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/resolve-timeout/1?action=failure")
        assert response.status_code == 200
        assert step.status == ExecutionStatus.FAILURE

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock)
    async def test_resolve_timeout_invalid_action(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 1
        step.status = ExecutionStatus.TIMEOUT

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/resolve-timeout/1?action=invalid")
        assert response.status_code == 200
        assert "inválida" in response.text.lower()


# ===========================================================================
# Retry Step via UI
# ===========================================================================

class TestRetryStepUI:
    @patch("maestro.services.orchestrator.OrchestratorService.retry_step")
    async def test_retry_step_ui_success(self, mock_retry, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 5
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        mock_retry.return_value = step

        # Mock the action log add
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/retry-step/5")
        assert response.status_code == 200

    @patch("maestro.services.orchestrator.OrchestratorService.retry_step")
    async def test_retry_step_ui_error(self, mock_retry, client, mock_session):
        mock_retry.side_effect = ValueError("Step não encontrado.")

        response = await client.post("/ui/retry-step/999")
        assert response.status_code == 200
        assert "não encontrado" in response.text.lower()


# ===========================================================================
# Execute Release via UI
# ===========================================================================

class TestExecuteReleaseUI:
    @patch("maestro.services.orchestrator.OrchestratorService.execute_release")
    async def test_execute_ui_success(self, mock_execute, client):
        mock_execute.return_value = 42

        response = await client.post("/ui/execute/my-release")
        assert response.status_code == 200

    @patch("maestro.services.orchestrator.OrchestratorService.execute_release")
    async def test_execute_ui_not_found(self, mock_execute, client):
        mock_execute.side_effect = ValueError("Descritor não encontrado.")

        response = await client.post("/ui/execute/nonexistent")
        assert response.status_code == 200
        assert "não encontrado" in response.text.lower()


# ===========================================================================
# Dry-Run via UI
# ===========================================================================

class TestDryRunUI:
    @patch("maestro.services.orchestrator.OrchestratorService.dry_run_release")
    async def test_dry_run_ui_success(self, mock_dry_run, client):
        from maestro.schemas.orchestrator import DryRunResponse, DryRunStageResult, DryRunStepResult

        mock_dry_run.return_value = DryRunResponse(
            name="test",
            valid=True,
            stages=[
                DryRunStageResult(
                    stage_id="stage-1",
                    steps=[
                        DryRunStepResult(
                            step_id="step-1",
                            stage_id="stage-1",
                            repository="repo",
                            branch="feature/x",
                            branch_exists=True,
                            pr_found=True,
                            pr_number=1,
                            pr_mergeable_state="clean",
                            pr_is_clean=True,
                            jenkins_job_path="job/path",
                            jenkins_job_exists=True,
                        )
                    ],
                )
            ],
        )

        response = await client.post("/ui/dry-run/test")
        assert response.status_code == 200

    @patch("maestro.services.orchestrator.OrchestratorService.dry_run_release")
    async def test_dry_run_ui_not_found(self, mock_dry_run, client):
        mock_dry_run.side_effect = ValueError("Descritor não encontrado.")

        response = await client.post("/ui/dry-run/nonexistent")
        assert response.status_code == 200
        assert "não encontrado" in response.text.lower()


# ===========================================================================
# Settings Page
# ===========================================================================

class TestSettingsUI:
    @patch("maestro.services.settings.UISettingsService.get_all_masked")
    async def test_settings_page_get(self, mock_get_all_masked, client):
        mock_get_all_masked.return_value = {
            "jenkins_base_url": "http://j:8080",
            "github_base_url": "https://github.com",
            "github_organization": "my-org",
            "step_timeout_minutes": None,
        }

        response = await client.get("/ui/settings")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("maestro.services.settings.UISettingsService.save")
    @patch("maestro.services.settings.UISettingsService.get_all")
    async def test_settings_page_post(self, mock_get_all, mock_save, client):
        mock_save.return_value = None
        mock_get_all.return_value = {
            "jenkins_base_url": "http://new:8080",
            "github_base_url": "",
            "github_organization": "",
            "step_timeout_minutes": None,
        }

        response = await client.post(
            "/ui/settings",
            data={"jenkins_base_url": "http://new:8080", "github_base_url": "", "github_organization": "", "step_timeout_minutes": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200


# ===========================================================================
# Approve Execution via UI
# ===========================================================================

class TestApproveExecutionUI:
    @patch("maestro.services.orchestrator.OrchestratorService.approve_release")
    async def test_approve_execution_not_found(self, mock_approve, client, mock_session):
        # Mock UIService.get_execution_with_stages returning None
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post(
            "/ui/execution/999/approve",
            json={"status": "Sucesso"},
        )
        assert response.status_code == 404
