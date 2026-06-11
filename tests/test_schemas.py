"""
Tests for Pydantic schemas and enums.
Covers: ExecutionStatus enum, callback schemas, orchestrator schemas,
GitHub schemas, Jenkins schemas.
"""
import pytest
from pydantic import ValidationError

from maestro.schemas.callback import ReleaseCallbackSchema, StepEventSchema
from maestro.schemas.enums import ExecutionStatus
from maestro.schemas.github import PullRequestDetailSchema, PullRequestSchema
from maestro.schemas.jenkins import JenkinsExecutableSchema, JenkinsQueueItemSchema
from maestro.schemas.orchestrator import (
    ApproveReleaseRequest,
    DryRunResponse,
    DryRunStageResult,
    DryRunStepResult,
    ExecuteReleaseRequest,
    JobSchema,
    ReleaseConfigSchema,
    StageSchema,
    StepSchema,
)

# ===========================================================================
# ExecutionStatus Enum
# ===========================================================================

class TestExecutionStatus:
    def test_all_members(self):
        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.IN_PROGRESS == "in_progress"
        assert ExecutionStatus.SUCCESS == "success"
        assert ExecutionStatus.FAILURE == "failure"
        assert ExecutionStatus.ERROR == "error"
        assert ExecutionStatus.ABORTED == "aborted"
        assert ExecutionStatus.WAITING_APPROVAL == "waiting_approval"
        assert ExecutionStatus.TIMEOUT == "timeout"

    def test_from_string_valid(self):
        assert ExecutionStatus.from_string("pending") == ExecutionStatus.PENDING
        assert ExecutionStatus.from_string("in_progress") == ExecutionStatus.IN_PROGRESS
        assert ExecutionStatus.from_string("success") == ExecutionStatus.SUCCESS
        assert ExecutionStatus.from_string("failure") == ExecutionStatus.FAILURE
        assert ExecutionStatus.from_string("waiting_approval") == ExecutionStatus.WAITING_APPROVAL
        assert ExecutionStatus.from_string("timeout") == ExecutionStatus.TIMEOUT

    def test_from_string_case_insensitive(self):
        assert ExecutionStatus.from_string("PENDING") == ExecutionStatus.PENDING
        assert ExecutionStatus.from_string("In_Progress") == ExecutionStatus.IN_PROGRESS
        assert ExecutionStatus.from_string("SUCCESS") == ExecutionStatus.SUCCESS

    def test_from_string_invalid_raises(self):
        with pytest.raises(ValueError, match="is not a valid"):
            ExecutionStatus.from_string("invalid_status")

    def test_from_string_empty_raises(self):
        with pytest.raises(ValueError):
            ExecutionStatus.from_string("")

    def test_str_enum_behavior(self):
        """ExecutionStatus extends str, so it can be compared as a string."""
        status = ExecutionStatus.PENDING
        assert status == "pending"
        assert status.value == "pending"
        assert str(status.value) == "pending"


# ===========================================================================
# Callback Schemas
# ===========================================================================

class TestReleaseCallbackSchema:
    def test_valid_minimal(self):
        data = {"job_execution_correlation_id": 123, "status": "success"}
        schema = ReleaseCallbackSchema(**data)
        assert schema.job_execution_correlation_id == 123
        assert schema.status == ExecutionStatus.SUCCESS
        assert schema.message is None
        assert schema.input_id is None

    def test_valid_full(self):
        data = {
            "job_execution_correlation_id": 456,
            "status": "waiting_approval",
            "message": "Awaiting manual approval",
            "input_id": "input-abc-123",
        }
        schema = ReleaseCallbackSchema(**data)
        assert schema.job_execution_correlation_id == 456
        assert schema.status == ExecutionStatus.WAITING_APPROVAL
        assert schema.message == "Awaiting manual approval"
        assert schema.input_id == "input-abc-123"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            ReleaseCallbackSchema()

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            ReleaseCallbackSchema(job_execution_correlation_id=1, status="invalid")

    def test_invalid_correlation_id_type(self):
        with pytest.raises(ValidationError):
            ReleaseCallbackSchema(job_execution_correlation_id="not-int", status="success")


class TestStepEventSchema:
    def test_valid(self):
        schema = StepEventSchema(job_execution_correlation_id=100, message="Build started")
        assert schema.job_execution_correlation_id == 100
        assert schema.message == "Build started"

    def test_missing_message(self):
        with pytest.raises(ValidationError):
            StepEventSchema(job_execution_correlation_id=100)

    def test_missing_correlation_id(self):
        with pytest.raises(ValidationError):
            StepEventSchema(message="test")


# ===========================================================================
# Orchestrator Schemas
# ===========================================================================

class TestJobSchema:
    def test_valid(self):
        job = JobSchema(type="jenkins", path="job/deploy")
        assert job.type == "jenkins"
        assert job.path == "job/deploy"

    def test_missing_fields(self):
        """path is optional — only type without path should still be valid."""
        job = JobSchema(type="jenkins")
        assert job.type == "jenkins"
        assert job.path is None


class TestStepSchema:
    def test_valid_minimal(self):
        step = StepSchema(
            id="step-1",
            repository="my-repo",
            release="feature/branch",
            job={"type": "jenkins", "path": "job/path"},
        )
        assert step.id == "step-1"
        assert step.critical is False
        assert step.requires_approval is False

    def test_valid_with_optionals(self):
        step = StepSchema(
            id="step-1",
            repository="my-repo",
            release="feature/branch",
            critical=True,
            requires_approval=True,
            job={"type": "jenkins", "path": "job/path"},
        )
        assert step.critical is True
        assert step.requires_approval is True


class TestStageSchema:
    def test_valid(self):
        stage = StageSchema(
            id="stage-1",
            steps=[
                {"id": "s1", "repository": "repo", "release": "branch", "job": {"type": "jenkins", "path": "p"}}
            ],
        )
        assert stage.id == "stage-1"
        assert len(stage.steps) == 1

    def test_empty_steps(self):
        stage = StageSchema(id="stage-empty", steps=[])
        assert stage.steps == []


class TestReleaseConfigSchema:
    def test_valid_full_yaml_structure(self):
        data = {
            "apiVersion": "v1",
            "kind": "Release",
            "metadata": {"name": "my-release", "author": "dev"},
            "spec": {
                "stages": [
                    {
                        "id": "stage-1",
                        "steps": [
                            {
                                "id": "step-1",
                                "repository": "repo",
                                "release": "feature/x",
                                "job": {"type": "jenkins", "path": "deploy"},
                            }
                        ],
                    }
                ]
            },
        }
        config = ReleaseConfigSchema(**data)
        assert config.metadata.name == "my-release"
        assert config.kind == "Release"
        assert len(config.spec.stages) == 1

    def test_invalid_kind(self):
        data = {
            "apiVersion": "v1",
            "kind": "NotRelease",
            "metadata": {"name": "bad", "author": "x"},
            "spec": {"stages": []},
        }
        with pytest.raises(ValidationError):
            ReleaseConfigSchema(**data)

    def test_missing_metadata(self):
        data = {
            "apiVersion": "v1",
            "kind": "Release",
            "spec": {"stages": []},
        }
        with pytest.raises(ValidationError):
            ReleaseConfigSchema(**data)

    def test_optional_strategy(self):
        data = {
            "apiVersion": "v1",
            "kind": "Release",
            "metadata": {"name": "r", "author": "a"},
            "spec": {
                "strategy": {"type": "all-or-nothing"},
                "stages": [],
            },
        }
        config = ReleaseConfigSchema(**data)
        assert config.spec.strategy.type == "all-or-nothing"

    def test_invalid_strategy_type(self):
        data = {
            "apiVersion": "v1",
            "kind": "Release",
            "metadata": {"name": "r", "author": "a"},
            "spec": {
                "strategy": {"type": "invalid-strategy"},
                "stages": [],
            },
        }
        with pytest.raises(ValidationError):
            ReleaseConfigSchema(**data)


class TestExecuteReleaseRequest:
    def test_valid(self):
        req = ExecuteReleaseRequest(name="my-release")
        assert req.name == "my-release"

    def test_missing_name(self):
        with pytest.raises(ValidationError):
            ExecuteReleaseRequest()


class TestApproveReleaseRequest:
    def test_default_status(self):
        req = ApproveReleaseRequest()
        assert req.status == "Sucesso"

    def test_custom_status(self):
        req = ApproveReleaseRequest(status="Rejeitado")
        assert req.status == "Rejeitado"


class TestDryRunSchemas:
    def test_dry_run_step_result(self):
        step = DryRunStepResult(
            step_id="s1",
            stage_id="st1",
            repository="repo",
            branch="feature/x",
            branch_exists=True,
            pr_found=True,
            pr_number=42,
            pr_mergeable_state="clean",
            pr_is_clean=True,
            jenkins_job_path="job/path",
            jenkins_job_exists=True,
        )
        assert step.pr_number == 42
        assert step.pr_is_clean is True

    def test_dry_run_response(self):
        response = DryRunResponse(
            name="test",
            valid=True,
            stages=[
                DryRunStageResult(
                    stage_id="stage-1",
                    steps=[
                        DryRunStepResult(
                            step_id="s1",
                            stage_id="stage-1",
                            repository="repo",
                            branch="b",
                            branch_exists=True,
                            pr_found=True,
                            pr_is_clean=True,
                            jenkins_job_path="p",
                            jenkins_job_exists=True,
                        )
                    ],
                )
            ],
        )
        assert response.valid is True
        assert len(response.stages) == 1


# ===========================================================================
# GitHub Schemas
# ===========================================================================

class TestPullRequestSchema:
    def test_valid(self):
        pr = PullRequestSchema(number=1, state="open", title="My PR")
        assert pr.number == 1
        assert pr.state == "open"

    def test_missing_field(self):
        with pytest.raises(ValidationError):
            PullRequestSchema(number=1, state="open")


class TestPullRequestDetailSchema:
    def test_valid_with_details(self):
        pr = PullRequestDetailSchema(
            number=10, state="open", title="PR", mergeable_state="clean", mergeable=True
        )
        assert pr.mergeable_state == "clean"
        assert pr.mergeable is True

    def test_optional_fields_default_none(self):
        pr = PullRequestDetailSchema(number=10, state="open", title="PR")
        assert pr.mergeable_state is None
        assert pr.mergeable is None


# ===========================================================================
# Jenkins Schemas
# ===========================================================================

class TestJenkinsSchemas:
    def test_queue_item_without_executable(self):
        item = JenkinsQueueItemSchema()
        assert item.executable is None

    def test_queue_item_with_executable(self):
        item = JenkinsQueueItemSchema(executable={"number": 42})
        assert item.executable.number == 42

    def test_executable_schema(self):
        exe = JenkinsExecutableSchema(number=100)
        assert exe.number == 100

    def test_executable_missing_number(self):
        with pytest.raises(ValidationError):
            JenkinsExecutableSchema()
