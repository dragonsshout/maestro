"""
Tests for the scheduler service layer and background task.
Covers: SchedulerService, _process_due_schedules, and schedule API endpoints.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from maestro.services.scheduler import SchedulerService, _process_due_schedules
from maestro.schemas.enums import ScheduledReleaseStatus
from maestro.database.models import ScheduledRelease


# ===========================================================================
# SchedulerService.schedule_release
# ===========================================================================


class TestSchedulerServiceScheduleRelease:
    @pytest.fixture
    def service(self):
        svc = SchedulerService.__new__(SchedulerService)
        svc.schedule_repo = AsyncMock()
        svc.orchestrator_repo = AsyncMock()
        svc.execution_repo = AsyncMock()
        return svc

    async def test_schedule_release_success(self, service):
        future_dt = datetime.now(timezone.utc) + timedelta(hours=2)
        service.schedule_repo.has_pending_schedule_for_release = AsyncMock(return_value=False)

        descriptor = MagicMock()
        descriptor.id = 10
        service.orchestrator_repo.get_by_name = AsyncMock(return_value=descriptor)

        created_schedule = MagicMock(spec=ScheduledRelease)
        created_schedule.id = 1
        created_schedule.name = "my-release"
        service.schedule_repo.create_schedule = AsyncMock(return_value=created_schedule)

        result = await service.schedule_release("my-release", future_dt)

        assert result == created_schedule
        service.schedule_repo.create_schedule.assert_awaited_once()
        call_args = service.schedule_repo.create_schedule.call_args[0][0]
        assert call_args.name == "my-release"
        assert call_args.orchestrator_descriptor_id == 10
        assert call_args.status == ScheduledReleaseStatus.PENDING.value

    async def test_schedule_release_in_the_past(self, service):
        past_dt = datetime.now(timezone.utc) - timedelta(hours=1)

        with pytest.raises(ValueError, match="futuro"):
            await service.schedule_release("my-release", past_dt)

    async def test_schedule_release_duplicate_pending(self, service):
        future_dt = datetime.now(timezone.utc) + timedelta(hours=2)
        service.schedule_repo.has_pending_schedule_for_release = AsyncMock(return_value=True)

        with pytest.raises(ValueError, match="pendente"):
            await service.schedule_release("my-release", future_dt)

    async def test_schedule_release_descriptor_not_found(self, service):
        future_dt = datetime.now(timezone.utc) + timedelta(hours=2)
        service.schedule_repo.has_pending_schedule_for_release = AsyncMock(return_value=False)
        service.orchestrator_repo.get_by_name = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="nao encontrado"):
            await service.schedule_release("nonexistent", future_dt)


# ===========================================================================
# SchedulerService.cancel_schedule
# ===========================================================================


class TestSchedulerServiceCancelSchedule:
    @pytest.fixture
    def service(self):
        svc = SchedulerService.__new__(SchedulerService)
        svc.schedule_repo = AsyncMock()
        svc.orchestrator_repo = AsyncMock()
        svc.execution_repo = AsyncMock()
        return svc

    async def test_cancel_schedule_success(self, service):
        cancelled = MagicMock(spec=ScheduledRelease)
        cancelled.id = 1
        cancelled.status = ScheduledReleaseStatus.CANCELLED.value
        service.schedule_repo.cancel_schedule = AsyncMock(return_value=cancelled)

        result = await service.cancel_schedule(1)

        assert result == cancelled
        service.schedule_repo.cancel_schedule.assert_awaited_once_with(1)

    async def test_cancel_schedule_not_found_or_not_pending(self, service):
        service.schedule_repo.cancel_schedule = AsyncMock(
            side_effect=ValueError("Agendamento #99 nao encontrado.")
        )

        with pytest.raises(ValueError, match="nao encontrado"):
            await service.cancel_schedule(99)


# ===========================================================================
# _process_due_schedules background task
# ===========================================================================


class TestProcessDueSchedules:
    @patch("maestro.repositories.schedule.ScheduleRepository")
    @patch("maestro.repositories.execution.ExecutionRepository")
    @patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository")
    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_no_pending_schedules(
        self, mock_session_local, mock_orch_repo_cls, mock_exec_repo_cls, mock_sched_repo_cls
    ):
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        mock_sched_repo = AsyncMock()
        mock_sched_repo.get_pending_due_schedules = AsyncMock(return_value=[])
        mock_sched_repo_cls.return_value = mock_sched_repo

        mock_exec_repo = AsyncMock()
        mock_exec_repo_cls.return_value = mock_exec_repo

        mock_orch_repo = AsyncMock()
        mock_orch_repo_cls.return_value = mock_orch_repo

        await _process_due_schedules()

        # No execution should have been triggered
        mock_exec_repo.get_active_execution_by_name.assert_not_awaited()
        mock_sched_repo.mark_executed.assert_not_awaited()
        mock_sched_repo.mark_failed.assert_not_awaited()

    @patch("maestro.services.scheduler.asyncio.create_task")
    @patch("maestro.services.orchestrator.OrchestratorService.execute_release", new_callable=AsyncMock)
    @patch("maestro.services.jenkins.JenkinsService")
    @patch("maestro.repositories.schedule.ScheduleRepository")
    @patch("maestro.repositories.execution.ExecutionRepository")
    @patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository")
    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_due_schedule_triggers_execution(
        self, mock_session_local, mock_orch_repo_cls, mock_exec_repo_cls,
        mock_sched_repo_cls, mock_jenkins_cls, mock_execute_release, mock_create_task
    ):
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        schedule = MagicMock(spec=ScheduledRelease)
        schedule.id = 5
        schedule.name = "my-release"

        mock_sched_repo = AsyncMock()
        mock_sched_repo.get_pending_due_schedules = AsyncMock(return_value=[schedule])
        mock_sched_repo_cls.return_value = mock_sched_repo

        mock_exec_repo = AsyncMock()
        mock_exec_repo.get_active_execution_by_name = AsyncMock(return_value=None)
        mock_exec_repo_cls.return_value = mock_exec_repo

        mock_orch_repo = AsyncMock()
        mock_orch_repo_cls.return_value = mock_orch_repo

        mock_execute_release.return_value = 42

        await _process_due_schedules()

        mock_sched_repo.mark_executed.assert_awaited_once_with(5, 42)
        mock_sched_repo.mark_failed.assert_not_awaited()

    @patch("maestro.services.scheduler.asyncio.create_task")
    @patch("maestro.repositories.schedule.ScheduleRepository")
    @patch("maestro.repositories.execution.ExecutionRepository")
    @patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository")
    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_due_schedule_with_active_execution_marks_failed(
        self, mock_session_local, mock_orch_repo_cls, mock_exec_repo_cls,
        mock_sched_repo_cls, mock_create_task
    ):
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        schedule = MagicMock(spec=ScheduledRelease)
        schedule.id = 7
        schedule.name = "busy-release"

        active_exec = MagicMock()
        active_exec.id = 100

        mock_sched_repo = AsyncMock()
        mock_sched_repo.get_pending_due_schedules = AsyncMock(return_value=[schedule])
        mock_sched_repo_cls.return_value = mock_sched_repo

        mock_exec_repo = AsyncMock()
        mock_exec_repo.get_active_execution_by_name = AsyncMock(return_value=active_exec)
        mock_exec_repo_cls.return_value = mock_exec_repo

        mock_orch_repo = AsyncMock()
        mock_orch_repo_cls.return_value = mock_orch_repo

        await _process_due_schedules()

        mock_sched_repo.mark_failed.assert_awaited_once()
        failed_call_args = mock_sched_repo.mark_failed.call_args
        assert failed_call_args[0][0] == 7
        assert "#100" in failed_call_args[0][1]

    @patch("maestro.services.scheduler.asyncio.create_task")
    @patch("maestro.services.orchestrator.OrchestratorService.execute_release", new_callable=AsyncMock)
    @patch("maestro.services.jenkins.JenkinsService")
    @patch("maestro.repositories.schedule.ScheduleRepository")
    @patch("maestro.repositories.execution.ExecutionRepository")
    @patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository")
    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_due_schedule_execution_raises_exception_marks_failed(
        self, mock_session_local, mock_orch_repo_cls, mock_exec_repo_cls,
        mock_sched_repo_cls, mock_jenkins_cls, mock_execute_release, mock_create_task
    ):
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        schedule = MagicMock(spec=ScheduledRelease)
        schedule.id = 9
        schedule.name = "failing-release"

        mock_sched_repo = AsyncMock()
        mock_sched_repo.get_pending_due_schedules = AsyncMock(return_value=[schedule])
        mock_sched_repo_cls.return_value = mock_sched_repo

        mock_exec_repo = AsyncMock()
        mock_exec_repo.get_active_execution_by_name = AsyncMock(return_value=None)
        mock_exec_repo_cls.return_value = mock_exec_repo

        mock_orch_repo = AsyncMock()
        mock_orch_repo_cls.return_value = mock_orch_repo

        mock_execute_release.side_effect = ValueError("PR nao esta clean")

        await _process_due_schedules()

        mock_sched_repo.mark_failed.assert_awaited_once()
        failed_call_args = mock_sched_repo.mark_failed.call_args
        assert failed_call_args[0][0] == 9
        assert "PR nao esta clean" in failed_call_args[0][1]


# ===========================================================================
# Schedule API Routes
# ===========================================================================


class TestScheduleAPIRoutes:
    @pytest.fixture
    def mock_scheduler_service(self):
        return AsyncMock(spec=SchedulerService)

    @pytest.fixture
    def app_with_scheduler_override(self, override_get_db, mock_scheduler_service):
        with patch("subprocess.run"):
            from maestro.main import app
            from maestro.database.session import get_db

            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[SchedulerService] = lambda: mock_scheduler_service
            yield app
            app.dependency_overrides.clear()

    @pytest.fixture
    async def client(self, app_with_scheduler_override):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=app_with_scheduler_override)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_post_schedule_success(self, client, mock_scheduler_service):
        future_dt = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.name = "my-release"
        mock_schedule.scheduled_at = future_dt
        mock_schedule.status = ScheduledReleaseStatus.PENDING
        mock_schedule.release_execution_id = None
        mock_schedule.created_at = datetime.now(timezone.utc)
        mock_schedule.created_by = None
        mock_schedule.error_message = None
        mock_scheduler_service.schedule_release = AsyncMock(return_value=mock_schedule)

        response = await client.post(
            "/orchestrator/schedule",
            json={"name": "my-release", "scheduled_at": future_dt.isoformat()},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-release"
        assert data["status"] == "pending"

    async def test_post_schedule_validation_error(self, client, mock_scheduler_service):
        future_dt = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_scheduler_service.schedule_release = AsyncMock(
            side_effect=ValueError("A data de agendamento deve ser no futuro.")
        )

        response = await client.post(
            "/orchestrator/schedule",
            json={"name": "my-release", "scheduled_at": future_dt.isoformat()},
        )

        assert response.status_code == 400
        assert "futuro" in response.json()["detail"]

    async def test_get_schedules(self, client, mock_scheduler_service):
        sched1 = MagicMock()
        sched1.id = 1
        sched1.name = "release-a"
        sched1.scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        sched1.status = ScheduledReleaseStatus.PENDING
        sched1.release_execution_id = None
        sched1.created_at = datetime.now(timezone.utc)
        sched1.created_by = None
        sched1.error_message = None

        sched2 = MagicMock()
        sched2.id = 2
        sched2.name = "release-b"
        sched2.scheduled_at = datetime.now(timezone.utc) + timedelta(hours=2)
        sched2.status = ScheduledReleaseStatus.EXECUTED
        sched2.release_execution_id = 42
        sched2.created_at = datetime.now(timezone.utc)
        sched2.created_by = "user"
        sched2.error_message = None

        mock_scheduler_service.get_all_schedules = AsyncMock(return_value=[sched1, sched2])

        response = await client.get("/orchestrator/schedules")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "release-a"
        assert data[1]["name"] == "release-b"

    async def test_delete_schedule_success(self, client, mock_scheduler_service):
        mock_scheduler_service.cancel_schedule = AsyncMock(return_value=MagicMock())

        response = await client.delete("/orchestrator/schedule/1")

        assert response.status_code == 200
        assert "cancelado" in response.json()["message"].lower()

    async def test_delete_schedule_not_found(self, client, mock_scheduler_service):
        mock_scheduler_service.cancel_schedule = AsyncMock(
            side_effect=ValueError("Agendamento #999 nao encontrado.")
        )

        response = await client.delete("/orchestrator/schedule/999")

        assert response.status_code == 400
        assert "nao encontrado" in response.json()["detail"]
