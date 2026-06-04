"""
Tests for the timeout_checker background service.
Covers: _check_timeouts logic - marking steps as TIMEOUT based on
step-level and global timeout settings.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from maestro.services.timeout_checker import _check_timeouts
from maestro.schemas.enums import ExecutionStatus
from maestro.database.models import ReleaseStepExecution, ReleaseExecution, OrchestratorDescriptor

from tests.conftest import SAMPLE_RELEASE_YAML


YAML_WITH_TIMEOUT = """\
apiVersion: v1
kind: Release
metadata:
  name: timeout-release
  author: tester
spec:
  stages:
    - id: stage-1
      steps:
        - id: step-1
          repository: my-repo
          release: feature/x
          timeout_minutes: 10
          job:
            type: jenkins
            path: job/deploy
"""

YAML_WITHOUT_TIMEOUT = """\
apiVersion: v1
kind: Release
metadata:
  name: no-timeout-release
  author: tester
spec:
  stages:
    - id: stage-1
      steps:
        - id: step-1
          repository: my-repo
          release: feature/x
          job:
            type: jenkins
            path: job/deploy
"""


class TestCheckTimeouts:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        return session

    @patch("maestro.services.timeout_checker.AsyncSessionLocal")
    async def test_no_in_progress_steps(self, mock_session_local):
        """No in-progress steps: nothing to timeout."""
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        # Mock settings repo
        with patch("maestro.services.timeout_checker.UISettingsRepository") as mock_settings_cls:
            mock_settings = AsyncMock()
            mock_settings.get.return_value = "60"
            mock_settings_cls.return_value = mock_settings

            # No in-progress steps
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            session.execute.return_value = mock_result

            await _check_timeouts()
            session.commit.assert_not_awaited()

    @patch("maestro.services.timeout_checker.AsyncSessionLocal")
    async def test_step_timeout_by_step_level_config(self, mock_session_local):
        """Step with step-level timeout_minutes exceeded gets marked as TIMEOUT."""
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        with patch("maestro.services.timeout_checker.UISettingsRepository") as mock_settings_cls:
            mock_settings = AsyncMock()
            mock_settings.get.return_value = None  # No global timeout
            mock_settings_cls.return_value = mock_settings

            # Build a step that's been in_progress for 15 minutes (timeout is 10)
            step = MagicMock(spec=ReleaseStepExecution)
            step.release_execution_id = 1
            step.stage_id = "stage-1"
            step.step_id = "step-1"
            step.status = ExecutionStatus.IN_PROGRESS
            step.updated_at = datetime.now(timezone.utc) - timedelta(minutes=15)

            # Build execution and descriptor
            execution = MagicMock(spec=ReleaseExecution)
            execution.id = 1
            execution.orchestrator_descriptor_id = 10

            descriptor = MagicMock(spec=OrchestratorDescriptor)
            descriptor.id = 10
            descriptor.yaml = YAML_WITH_TIMEOUT

            # Setup execute calls: steps, executions, descriptors
            steps_result = MagicMock()
            steps_result.scalars.return_value.all.return_value = [step]

            exec_result = MagicMock()
            exec_result.scalars.return_value.all.return_value = [execution]

            desc_result = MagicMock()
            desc_result.scalars.return_value.all.return_value = [descriptor]

            session.execute.side_effect = [steps_result, exec_result, desc_result]

            await _check_timeouts()

            # Step should be marked as TIMEOUT
            assert step.status == ExecutionStatus.TIMEOUT
            assert "Timeout" in step.message
            session.add.assert_called_with(step)
            session.commit.assert_awaited_once()

    @patch("maestro.services.timeout_checker.AsyncSessionLocal")
    async def test_step_not_timed_out_yet(self, mock_session_local):
        """Step within timeout window is not marked."""
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        with patch("maestro.services.timeout_checker.UISettingsRepository") as mock_settings_cls:
            mock_settings = AsyncMock()
            mock_settings.get.return_value = None
            mock_settings_cls.return_value = mock_settings

            # Step that's been in_progress for only 5 minutes (timeout is 10)
            step = MagicMock(spec=ReleaseStepExecution)
            step.release_execution_id = 1
            step.stage_id = "stage-1"
            step.step_id = "step-1"
            step.status = ExecutionStatus.IN_PROGRESS
            step.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)

            execution = MagicMock(spec=ReleaseExecution)
            execution.id = 1
            execution.orchestrator_descriptor_id = 10

            descriptor = MagicMock(spec=OrchestratorDescriptor)
            descriptor.id = 10
            descriptor.yaml = YAML_WITH_TIMEOUT

            steps_result = MagicMock()
            steps_result.scalars.return_value.all.return_value = [step]

            exec_result = MagicMock()
            exec_result.scalars.return_value.all.return_value = [execution]

            desc_result = MagicMock()
            desc_result.scalars.return_value.all.return_value = [descriptor]

            session.execute.side_effect = [steps_result, exec_result, desc_result]

            await _check_timeouts()

            # Step should NOT be updated
            assert step.status == ExecutionStatus.IN_PROGRESS
            session.commit.assert_not_awaited()

    @patch("maestro.services.timeout_checker.AsyncSessionLocal")
    async def test_global_timeout_used_when_no_step_level(self, mock_session_local):
        """When no step-level timeout, global setting is used."""
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        with patch("maestro.services.timeout_checker.UISettingsRepository") as mock_settings_cls:
            mock_settings = AsyncMock()
            mock_settings.get.return_value = "30"  # 30 minutes global
            mock_settings_cls.return_value = mock_settings

            # Step that's been in_progress for 45 minutes
            step = MagicMock(spec=ReleaseStepExecution)
            step.release_execution_id = 1
            step.stage_id = "stage-1"
            step.step_id = "step-1"
            step.status = ExecutionStatus.IN_PROGRESS
            step.updated_at = datetime.now(timezone.utc) - timedelta(minutes=45)

            execution = MagicMock(spec=ReleaseExecution)
            execution.id = 1
            execution.orchestrator_descriptor_id = 10

            descriptor = MagicMock(spec=OrchestratorDescriptor)
            descriptor.id = 10
            descriptor.yaml = YAML_WITHOUT_TIMEOUT  # No step-level timeout

            steps_result = MagicMock()
            steps_result.scalars.return_value.all.return_value = [step]

            exec_result = MagicMock()
            exec_result.scalars.return_value.all.return_value = [execution]

            desc_result = MagicMock()
            desc_result.scalars.return_value.all.return_value = [descriptor]

            session.execute.side_effect = [steps_result, exec_result, desc_result]

            await _check_timeouts()

            assert step.status == ExecutionStatus.TIMEOUT
            assert "30" in step.message
            session.commit.assert_awaited_once()

    @patch("maestro.services.timeout_checker.AsyncSessionLocal")
    async def test_no_timeout_configured_step_runs_indefinitely(self, mock_session_local):
        """When no global or step-level timeout configured, step is not timed out."""
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        with patch("maestro.services.timeout_checker.UISettingsRepository") as mock_settings_cls:
            mock_settings = AsyncMock()
            mock_settings.get.return_value = None  # No global timeout
            mock_settings_cls.return_value = mock_settings

            # Step running for days
            step = MagicMock(spec=ReleaseStepExecution)
            step.release_execution_id = 1
            step.stage_id = "stage-1"
            step.step_id = "step-1"
            step.status = ExecutionStatus.IN_PROGRESS
            step.updated_at = datetime.now(timezone.utc) - timedelta(days=7)

            execution = MagicMock(spec=ReleaseExecution)
            execution.id = 1
            execution.orchestrator_descriptor_id = 10

            descriptor = MagicMock(spec=OrchestratorDescriptor)
            descriptor.id = 10
            descriptor.yaml = YAML_WITHOUT_TIMEOUT  # No step-level timeout

            steps_result = MagicMock()
            steps_result.scalars.return_value.all.return_value = [step]

            exec_result = MagicMock()
            exec_result.scalars.return_value.all.return_value = [execution]

            desc_result = MagicMock()
            desc_result.scalars.return_value.all.return_value = [descriptor]

            session.execute.side_effect = [steps_result, exec_result, desc_result]

            await _check_timeouts()

            # Step should NOT be timed out
            assert step.status == ExecutionStatus.IN_PROGRESS
            session.commit.assert_not_awaited()

    @patch("maestro.services.timeout_checker.AsyncSessionLocal")
    async def test_step_level_timeout_takes_precedence_over_global(self, mock_session_local):
        """Step-level timeout_minutes overrides global setting."""
        session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = session

        with patch("maestro.services.timeout_checker.UISettingsRepository") as mock_settings_cls:
            mock_settings = AsyncMock()
            mock_settings.get.return_value = "60"  # 60 min global
            mock_settings_cls.return_value = mock_settings

            # Step at 12 minutes (step timeout is 10, global is 60)
            step = MagicMock(spec=ReleaseStepExecution)
            step.release_execution_id = 1
            step.stage_id = "stage-1"
            step.step_id = "step-1"
            step.status = ExecutionStatus.IN_PROGRESS
            step.updated_at = datetime.now(timezone.utc) - timedelta(minutes=12)

            execution = MagicMock(spec=ReleaseExecution)
            execution.id = 1
            execution.orchestrator_descriptor_id = 10

            descriptor = MagicMock(spec=OrchestratorDescriptor)
            descriptor.id = 10
            descriptor.yaml = YAML_WITH_TIMEOUT  # 10 min step-level timeout

            steps_result = MagicMock()
            steps_result.scalars.return_value.all.return_value = [step]

            exec_result = MagicMock()
            exec_result.scalars.return_value.all.return_value = [execution]

            desc_result = MagicMock()
            desc_result.scalars.return_value.all.return_value = [descriptor]

            session.execute.side_effect = [steps_result, exec_result, desc_result]

            await _check_timeouts()

            # Should timeout because step-level (10 min) is exceeded
            assert step.status == ExecutionStatus.TIMEOUT
            assert "10" in step.message
