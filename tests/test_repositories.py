"""
Tests for repository layer.
Covers: OrchestratorDescriptorRepository, ExecutionRepository, UISettingsRepository.
All DB interactions are mocked at the AsyncSession level.
"""

from unittest.mock import MagicMock

import pytest

from maestro.database.models import (
    OrchestratorDescriptor,
    ReleaseExecution,
    ReleaseStepExecution,
    StepEvent,
    UISettings,
)
from maestro.repositories.execution import ExecutionRepository
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository
from maestro.repositories.settings import UISettingsRepository
from maestro.schemas.enums import ExecutionStatus

# ===========================================================================
# OrchestratorDescriptorRepository
# ===========================================================================


class TestOrchestratorDescriptorRepository:
    @pytest.fixture
    def repo(self, mock_db_session):
        return OrchestratorDescriptorRepository(db=mock_db_session)

    async def test_add(self, repo, mock_db_session):
        descriptor = OrchestratorDescriptor(name="test", yaml="content")
        await repo.add(descriptor)

        mock_db_session.add.assert_called_once_with(descriptor)
        mock_db_session.commit.assert_awaited_once()
        mock_db_session.refresh.assert_awaited_once_with(descriptor)

    async def test_get_by_id_found(self, repo, mock_db_session):
        mock_descriptor = MagicMock(spec=OrchestratorDescriptor)
        mock_descriptor.id = 1
        mock_descriptor.name = "test"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_descriptor
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_by_id(1)
        assert result == mock_descriptor

    async def test_get_by_id_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_by_id(999)
        assert result is None

    async def test_get_by_name_found(self, repo, mock_db_session):
        mock_descriptor = MagicMock(spec=OrchestratorDescriptor)
        mock_descriptor.name = "my-release"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_descriptor
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_by_name("my-release")
        assert result.name == "my-release"

    async def test_get_by_name_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_by_name("nonexistent")
        assert result is None

    async def test_get_all(self, repo, mock_db_session):
        d1 = MagicMock(spec=OrchestratorDescriptor)
        d2 = MagicMock(spec=OrchestratorDescriptor)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [d1, d2]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_all()
        assert len(result) == 2

    async def test_get_all_empty(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_all()
        assert result == []


# ===========================================================================
# ExecutionRepository
# ===========================================================================


class TestExecutionRepository:
    @pytest.fixture
    def repo(self, mock_db_session):
        return ExecutionRepository(db=mock_db_session)

    async def test_add_release_execution(self, repo, mock_db_session):
        execution = ReleaseExecution(name="test", status=ExecutionStatus.PENDING, orchestrator_descriptor_id=1)
        await repo.add_release_execution(execution)

        mock_db_session.add.assert_called_once_with(execution)
        mock_db_session.commit.assert_awaited_once()
        mock_db_session.refresh.assert_awaited_once_with(execution)

    async def test_update_release_execution(self, repo, mock_db_session):
        execution = MagicMock(spec=ReleaseExecution)
        await repo.update_release_execution(execution)

        mock_db_session.add.assert_called_once_with(execution)
        mock_db_session.commit.assert_awaited_once()

    async def test_get_execution_by_id_found(self, repo, mock_db_session):
        mock_exec = MagicMock(spec=ReleaseExecution)
        mock_exec.id = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_exec
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_execution_by_id(1)
        assert result.id == 1

    async def test_get_execution_by_id_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_execution_by_id(999)
        assert result is None

    async def test_add_step_execution(self, repo, mock_db_session):
        step = ReleaseStepExecution(
            release_execution_id=1, stage_id="stage-1", step_id="step-1", status=ExecutionStatus.PENDING
        )
        await repo.add_step_execution(step)

        mock_db_session.add.assert_called_once_with(step)
        mock_db_session.commit.assert_awaited_once()

    async def test_update_step_execution(self, repo, mock_db_session):
        step = MagicMock(spec=ReleaseStepExecution)
        await repo.update_step_execution(step)

        mock_db_session.add.assert_called_once_with(step)
        mock_db_session.commit.assert_awaited_once()

    async def test_get_steps_by_execution_id(self, repo, mock_db_session):
        s1 = MagicMock(spec=ReleaseStepExecution)
        s2 = MagicMock(spec=ReleaseStepExecution)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [s1, s2]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_steps_by_execution_id(1)
        assert len(result) == 2

    async def test_get_specific_step(self, repo, mock_db_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.stage_id = "stage-1"
        step.step_id = "step-1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_specific_step(1, "stage-1", "step-1")
        assert result.stage_id == "stage-1"

    async def test_get_step_by_correlation_id_found(self, repo, mock_db_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.job_execution_correlation_id = 42

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_step_by_correlation_id(42)
        assert result.job_execution_correlation_id == 42

    async def test_get_step_by_correlation_id_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_step_by_correlation_id(999)
        assert result is None

    async def test_get_step_by_id(self, repo, mock_db_session):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = 5

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = step
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_step_by_id(5)
        assert result.id == 5

    async def test_exists_by_name_true(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = MagicMock()
        mock_db_session.execute.return_value = mock_result

        result = await repo.exists_by_name("existing-release")
        assert result is True

    async def test_exists_by_name_false(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.exists_by_name("nonexistent")
        assert result is False

    async def test_get_latest_execution_by_name(self, repo, mock_db_session):
        exec_mock = MagicMock(spec=ReleaseExecution)
        exec_mock.name = "my-release"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = exec_mock
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_latest_execution_by_name("my-release")
        assert result.name == "my-release"

    async def test_get_all_executions(self, repo, mock_db_session):
        e1 = MagicMock(spec=ReleaseExecution)
        e2 = MagicMock(spec=ReleaseExecution)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [e1, e2]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_all_executions()
        assert len(result) == 2

    async def test_add_step_event(self, repo, mock_db_session):
        event = StepEvent(job_execution_correlation_id=100, message="Build started")
        await repo.add_step_event(event)

        mock_db_session.add.assert_called_once_with(event)
        mock_db_session.commit.assert_awaited_once()

    async def test_get_events_by_correlation_id(self, repo, mock_db_session):
        ev1 = MagicMock(spec=StepEvent)
        ev2 = MagicMock(spec=StepEvent)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ev1, ev2]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_events_by_correlation_id(100)
        assert len(result) == 2

    async def test_get_active_execution_by_name_found(self, repo, mock_db_session):
        exec_mock = MagicMock(spec=ReleaseExecution)
        exec_mock.name = "my-release"
        exec_mock.status = ExecutionStatus.IN_PROGRESS

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = exec_mock
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_active_execution_by_name("my-release")
        assert result is not None
        assert result.name == "my-release"

    async def test_get_active_execution_by_name_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_active_execution_by_name("no-active")
        assert result is None

    async def test_add_action_log(self, repo, mock_db_session):
        from maestro.database.models import ExecutionActionLog

        log = ExecutionActionLog(
            release_execution_id=1,
            action="approve",
            detail="Approved",
        )
        await repo.add_action_log(log)

        mock_db_session.add.assert_called_once_with(log)
        mock_db_session.commit.assert_awaited_once()
        mock_db_session.refresh.assert_awaited_once_with(log)

    async def test_get_action_logs_by_execution_id(self, repo, mock_db_session):
        from maestro.database.models import ExecutionActionLog

        log1 = MagicMock(spec=ExecutionActionLog)
        log2 = MagicMock(spec=ExecutionActionLog)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [log1, log2]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_action_logs_by_execution_id(1)
        assert len(result) == 2


# ===========================================================================
# UISettingsRepository
# ===========================================================================


class TestUISettingsRepository:
    @pytest.fixture
    def repo(self, mock_db_session):
        return UISettingsRepository(db=mock_db_session)

    async def test_get_all(self, repo, mock_db_session):
        s1 = MagicMock(spec=UISettings)
        s1.key = "jenkins_base_url"
        s1.value = "http://jenkins:8080"
        s2 = MagicMock(spec=UISettings)
        s2.key = "github_base_url"
        s2.value = "https://github.com"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [s1, s2]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_all()
        assert result == {"jenkins_base_url": "http://jenkins:8080", "github_base_url": "https://github.com"}

    async def test_get_found(self, repo, mock_db_session):
        setting = MagicMock(spec=UISettings)
        setting.value = "http://jenkins:8080"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = setting
        mock_db_session.execute.return_value = mock_result

        result = await repo.get("jenkins_base_url")
        assert result == "http://jenkins:8080"

    async def test_get_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.get("nonexistent_key")
        assert result is None

    async def test_upsert(self, repo, mock_db_session):
        await repo.upsert("jenkins_base_url", "http://new:8080")

        mock_db_session.execute.assert_awaited_once()
        mock_db_session.commit.assert_awaited_once()

    async def test_upsert_many(self, repo, mock_db_session):
        settings = {"key1": "val1", "key2": "val2", "key3": None}
        await repo.upsert_many(settings)

        # upsert is called for each key
        assert mock_db_session.execute.await_count == 3
        assert mock_db_session.commit.await_count == 3
