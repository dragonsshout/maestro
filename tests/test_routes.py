"""
Tests for API routes.
Covers: orchestrator routes, callback routes.
Uses httpx AsyncClient with FastAPI app dependency overrides.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from maestro.auth.dependencies import can_admin, can_approve, can_operate, can_view, get_current_user
from maestro.database.models import ReleaseStepExecution
from maestro.database.session import get_db
from maestro.schemas.enums import ExecutionStatus


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

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.full_name = "Admin"
        mock_user.is_active = True

        async def _get_db_override():
            yield mock_session

        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[can_view] = lambda: mock_user
        app.dependency_overrides[can_approve] = lambda: mock_user
        app.dependency_overrides[can_operate] = lambda: mock_user
        app.dependency_overrides[can_admin] = lambda: mock_user
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def client(app_override):
    transport = ASGITransport(app=app_override)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ===========================================================================
# Health Check
# ===========================================================================

class TestHealthCheck:
    async def test_health_check(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "Maestro" in data["message"]


# ===========================================================================
# Orchestrator Routes
# ===========================================================================

class TestOrchestratorRoutes:
    async def test_upload_config_wrong_extension(self, client):
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("config.txt", b"content", "text/plain")},
        )
        assert response.status_code == 400
        assert "extensão" in response.json()["detail"]

    @patch("maestro.services.orchestrator.OrchestratorService.save_descriptor")
    async def test_upload_config_success(self, mock_save, client):
        mock_save.return_value = MagicMock(id=1)

        response = await client.post(
            "/orchestrator/config",
            files={"file": ("release.yaml", b"apiVersion: v1", "application/x-yaml")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert "sucesso" in data["message"]

    @patch("maestro.services.orchestrator.OrchestratorService.save_descriptor")
    async def test_upload_config_validation_error(self, mock_save, client):
        mock_save.side_effect = ValueError("YAML inválido")

        response = await client.post(
            "/orchestrator/config",
            files={"file": ("release.yaml", b"bad: yaml", "application/x-yaml")},
        )
        assert response.status_code == 400
        assert "YAML inválido" in response.json()["detail"]

    @patch("maestro.services.orchestrator.OrchestratorService.execute_release")
    async def test_execute_release_success(self, mock_execute, client):
        mock_execute.return_value = 42

        response = await client.post("/orchestrator/execute", json={"name": "my-release"})
        assert response.status_code == 200
        data = response.json()
        assert data["release_execution_id"] == 42

    @patch("maestro.services.orchestrator.OrchestratorService.execute_release")
    async def test_execute_release_not_found(self, mock_execute, client):
        mock_execute.side_effect = ValueError("Descritor não encontrado.")

        response = await client.post("/orchestrator/execute", json={"name": "nonexistent"})
        assert response.status_code == 400

    @patch("maestro.services.orchestrator.OrchestratorService.dry_run_release")
    async def test_dry_run_success(self, mock_dry_run, client):
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

        response = await client.post("/orchestrator/dry-run", json={"name": "test"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["name"] == "test"

    @patch("maestro.services.orchestrator.OrchestratorService.dry_run_release")
    async def test_dry_run_not_found(self, mock_dry_run, client):
        mock_dry_run.side_effect = ValueError("Descritor com nome 'x' não encontrado.")

        response = await client.post("/orchestrator/dry-run", json={"name": "x"})
        assert response.status_code == 400
        assert "não encontrado" in response.json()["detail"]

    @patch("maestro.services.orchestrator.OrchestratorService.retry_step")
    async def test_retry_step_success(self, mock_retry, client):
        step = MagicMock()
        step.id = 5
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        mock_retry.return_value = step

        response = await client.post("/orchestrator/retry-step/5")
        assert response.status_code == 200
        data = response.json()
        assert data["step_execution_id"] == 5

    @patch("maestro.services.orchestrator.OrchestratorService.retry_step")
    async def test_retry_step_not_found(self, mock_retry, client):
        mock_retry.side_effect = ValueError("Step não encontrado.")

        response = await client.post("/orchestrator/retry-step/999")
        assert response.status_code == 400

    @patch("maestro.services.orchestrator.OrchestratorService.approve_release")
    async def test_approve_release_success(self, mock_approve, client):
        mock_approve.return_value = {"message": "Aprovação enviada com sucesso ao Jenkins", "approved_steps": [1]}

        response = await client.post("/orchestrator/approve/my-release", json={"status": "Sucesso"})
        assert response.status_code == 200
        data = response.json()
        assert "Aprovação" in data["message"]

    @patch("maestro.services.orchestrator.OrchestratorService.approve_release")
    async def test_approve_release_not_waiting(self, mock_approve, client):
        mock_approve.side_effect = ValueError("não está aguardando aprovação")

        response = await client.post("/orchestrator/approve/my-release", json={"status": "Sucesso"})
        assert response.status_code == 400

    async def test_get_release_status_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.get("/orchestrator/status/nonexistent")
        assert response.status_code == 404

    async def test_get_release_details_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.get("/orchestrator/details/nonexistent")
        assert response.status_code == 404


# ===========================================================================
# Callback Routes
# ===========================================================================

class TestCallbackRoutes:
    async def test_release_callback_step_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        payload = {
            "job_execution_correlation_id": 999,
            "status": "success",
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 404

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow")
    async def test_release_callback_success(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.release_execution_id = 1
        step.stage_id = "stage-1"
        step.step_id = "step-1"
        step.status = ExecutionStatus.SUCCESS

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        payload = {
            "job_execution_correlation_id": 42,
            "status": "success",
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["job_execution_correlation_id"] == 42

    @patch("maestro.services.orchestrator.OrchestratorService.process_workflow")
    async def test_release_callback_waiting_approval_without_input_id(self, mock_process, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.release_execution_id = 1
        step.status = ExecutionStatus.PENDING

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        payload = {
            "job_execution_correlation_id": 42,
            "status": "waiting_approval",
            # No input_id
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 400
        assert "input_id" in response.json()["detail"].lower()

    async def test_event_callback_step_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        payload = {"job_execution_correlation_id": 999, "message": "test log"}
        response = await client.post("/callback/event", json=payload)
        assert response.status_code == 404

    async def test_event_callback_success(self, client, mock_session):
        step = MagicMock(spec=ReleaseStepExecution)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_session.execute.return_value = mock_result

        payload = {"job_execution_correlation_id": 100, "message": "Build #5 started"}
        response = await client.post("/callback/event", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "Evento registrado" in data["message"]

    async def test_release_callback_invalid_payload(self, client):
        response = await client.post("/callback/release", json={})
        assert response.status_code == 422

    async def test_event_callback_invalid_payload(self, client):
        response = await client.post("/callback/event", json={"message": "no correlation"})
        assert response.status_code == 422
