"""
Tests for the OrchestratorService.process_workflow state machine.
Covers: pending->in_progress, step failure->execution failure, all success,
waiting approval, timeout halts, and multi-stage progression.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from maestro.services.orchestrator import OrchestratorService
from maestro.schemas.enums import ExecutionStatus
from maestro.database.models import ReleaseExecution, ReleaseStepExecution

from tests.conftest import SAMPLE_RELEASE_YAML, SAMPLE_RELEASE_YAML_MULTI_STAGE


@pytest.fixture
def service():
    """OrchestratorService with mocked dependencies."""
    svc = OrchestratorService.__new__(OrchestratorService)
    svc.repository = AsyncMock()
    svc.execution_repo = AsyncMock()
    svc.jenkins_service = AsyncMock()
    svc.job_path_registry_repo = AsyncMock()
    return svc


def _make_execution(id=1, status=ExecutionStatus.PENDING, descriptor_id=1, name="test-release"):
    execution = MagicMock(spec=ReleaseExecution)
    execution.id = id
    execution.name = name
    execution.status = status
    execution.orchestrator_descriptor_id = descriptor_id
    return execution


def _make_step(stage_id="stage-1", step_id="step-1", status=ExecutionStatus.PENDING,
               release_execution_id=1, correlation_id=None):
    step = MagicMock(spec=ReleaseStepExecution)
    step.release_execution_id = release_execution_id
    step.stage_id = stage_id
    step.step_id = step_id
    step.status = status
    step.job_execution_correlation_id = correlation_id
    return step


def _make_descriptor(yaml_content=SAMPLE_RELEASE_YAML, id=1):
    descriptor = MagicMock()
    descriptor.id = id
    descriptor.yaml = yaml_content
    return descriptor


def _patch_session_local(exec_repo, orch_repo):
    """Creates a patch context for AsyncSessionLocal used inside process_workflow."""
    session_mock = AsyncMock()

    class FakeSessionLocal:
        async def __aenter__(self):
            return session_mock
        async def __aexit__(self, *args):
            pass

    return patch.dict(
        "maestro.services.orchestrator.__builtins__", {}
    )  # placeholder - we'll use a different approach


class TestProcessWorkflowBasic:
    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_execution_not_found(self, mock_session_local, service):
        """process_workflow returns early if execution not found."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = None

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=AsyncMock()):
            await service.process_workflow(999)

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_already_terminal_returns_early(self, mock_session_local, service):
        """process_workflow does nothing if execution is already SUCCESS."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.SUCCESS)
        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=AsyncMock()):
            await service.process_workflow(1)

        exec_repo.update_release_execution.assert_not_awaited()

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_pending_transitions_to_in_progress(self, mock_session_local, service):
        """A PENDING execution transitions to IN_PROGRESS when workflow starts."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.PENDING)
        descriptor = _make_descriptor()
        step = _make_step(status=ExecutionStatus.PENDING)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step]
        exec_repo.update_release_execution.return_value = execution
        exec_repo.update_step_execution.return_value = step

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        service._trigger_step_standalone = AsyncMock(return_value=ExecutionStatus.IN_PROGRESS)

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        assert execution.status == ExecutionStatus.IN_PROGRESS


class TestProcessWorkflowStepOutcomes:
    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_step_failure_marks_execution_failure(self, mock_session_local, service):
        """When a step fails during trigger, execution is marked as FAILURE."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor()
        step = _make_step(status=ExecutionStatus.PENDING)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        service._trigger_step_standalone = AsyncMock(return_value=ExecutionStatus.FAILURE)

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        assert execution.status == ExecutionStatus.FAILURE

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_all_steps_success_marks_execution_success(self, mock_session_local, service):
        """When all steps are SUCCESS, execution is marked SUCCESS."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor()
        step = _make_step(status=ExecutionStatus.SUCCESS)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        assert execution.status == ExecutionStatus.SUCCESS

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_step_in_progress_keeps_execution_in_progress(self, mock_session_local, service):
        """When a step is IN_PROGRESS, execution stays IN_PROGRESS."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor()
        step = _make_step(status=ExecutionStatus.IN_PROGRESS)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        assert execution.status == ExecutionStatus.IN_PROGRESS

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_waiting_approval_marks_execution_waiting(self, mock_session_local, service):
        """When all steps done except one WAITING_APPROVAL, execution goes to WAITING_APPROVAL."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor()
        step = _make_step(status=ExecutionStatus.WAITING_APPROVAL)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        assert execution.status == ExecutionStatus.WAITING_APPROVAL

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_timeout_step_halts_workflow(self, mock_session_local, service):
        """When a step is in TIMEOUT status, workflow halts (returns early)."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor()
        step = _make_step(status=ExecutionStatus.TIMEOUT)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        # Workflow halts - execution stays IN_PROGRESS (not updated to terminal)
        assert execution.status == ExecutionStatus.IN_PROGRESS

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_existing_failure_step_marks_execution_failure(self, mock_session_local, service):
        """When a step already has FAILURE status, execution goes to FAILURE."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor()
        step = _make_step(status=ExecutionStatus.FAILURE)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        assert execution.status == ExecutionStatus.FAILURE


class TestProcessWorkflowMultiStage:
    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_multi_stage_first_complete_second_pending(self, mock_session_local, service):
        """Multi-stage: stage-1 SUCCESS triggers stage-2 pending steps."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor(yaml_content=SAMPLE_RELEASE_YAML_MULTI_STAGE)

        step1 = _make_step(stage_id="stage-1", step_id="step-1", status=ExecutionStatus.SUCCESS)
        step2 = _make_step(stage_id="stage-2", step_id="step-2", status=ExecutionStatus.PENDING)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step1, step2]
        exec_repo.update_release_execution.return_value = execution
        exec_repo.update_step_execution.return_value = step2

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        service._trigger_step_standalone = AsyncMock(return_value=ExecutionStatus.IN_PROGRESS)

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        # Stage-2 step should have been triggered
        service._trigger_step_standalone.assert_awaited_once()
        assert execution.status == ExecutionStatus.IN_PROGRESS

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_multi_stage_all_success(self, mock_session_local, service):
        """Multi-stage: all steps SUCCESS -> execution SUCCESS."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor(yaml_content=SAMPLE_RELEASE_YAML_MULTI_STAGE)

        step1 = _make_step(stage_id="stage-1", step_id="step-1", status=ExecutionStatus.SUCCESS)
        step2 = _make_step(stage_id="stage-2", step_id="step-2", status=ExecutionStatus.SUCCESS)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step1, step2]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        assert execution.status == ExecutionStatus.SUCCESS

    @patch("maestro.database.session.AsyncSessionLocal")
    async def test_multi_stage_first_failure_stops_second(self, mock_session_local, service):
        """Multi-stage: stage-1 FAILURE stops entire execution (stage-2 not triggered)."""
        session = AsyncMock()

        class FakeCtx:
            async def __aenter__(self_):
                return session
            async def __aexit__(self_, *a):
                pass

        mock_session_local.return_value = FakeCtx()

        execution = _make_execution(status=ExecutionStatus.IN_PROGRESS)
        descriptor = _make_descriptor(yaml_content=SAMPLE_RELEASE_YAML_MULTI_STAGE)

        step1 = _make_step(stage_id="stage-1", step_id="step-1", status=ExecutionStatus.FAILURE)
        step2 = _make_step(stage_id="stage-2", step_id="step-2", status=ExecutionStatus.PENDING)

        exec_repo = AsyncMock()
        exec_repo.get_execution_by_id.return_value = execution
        exec_repo.get_steps_by_execution_id.return_value = [step1, step2]
        exec_repo.update_release_execution.return_value = execution

        orch_repo = AsyncMock()
        orch_repo.get_by_id.return_value = descriptor

        service._trigger_step_standalone = AsyncMock()

        with patch("maestro.repositories.execution.ExecutionRepository", return_value=exec_repo), \
             patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository", return_value=orch_repo):
            await service.process_workflow(1)

        # Execution failed, stage-2 not triggered
        assert execution.status == ExecutionStatus.FAILURE
        service._trigger_step_standalone.assert_not_awaited()
