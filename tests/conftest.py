"""
Shared fixtures for the Maestro test suite.

Provides:
- Mocked async DB session
- FastAPI TestClient with dependency overrides
- Common test data (sample YAML, model factories)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from maestro.auth.dependencies import (
    can_admin,
    can_approve,
    can_operate,
    can_view,
    get_current_user,
    get_user_permissions,
)
from maestro.database.models import (
    OrchestratorDescriptor,
    ReleaseExecution,
    ReleaseStepExecution,
    StepEvent,
    User,
)
from maestro.database.session import get_db
from maestro.schemas.enums import ExecutionStatus

# ---------------------------------------------------------------------------
# Sample YAML for tests
# ---------------------------------------------------------------------------

SAMPLE_RELEASE_YAML = """\
apiVersion: v1
kind: Release
metadata:
  name: test-release
  author: tester
  description: A test release
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

SAMPLE_RELEASE_YAML_MULTI_STAGE = """\
apiVersion: v1
kind: Release
metadata:
  name: multi-stage-release
  author: tester
  description: Multi stage release
spec:
  stages:
    - id: stage-1
      steps:
        - id: step-1
          repository: repo-a
          release: feature/a
          job:
            type: jenkins
            path: job/deploy-a
    - id: stage-2
      steps:
        - id: step-2
          repository: repo-b
          release: feature/b
          job:
            type: jenkins
            path: job/deploy-b
"""

INVALID_YAML = "not: valid: yaml: {{{"

INVALID_SCHEMA_YAML = """\
apiVersion: v1
kind: NotRelease
metadata:
  name: bad
spec:
  stages: []
"""


# ---------------------------------------------------------------------------
# Database session mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_session():
    """Returns a mocked AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def override_get_db(mock_db_session):
    """Dependency override for get_db that yields the mock session."""
    async def _override():
        yield mock_db_session
    return _override


# ---------------------------------------------------------------------------
# Mock admin user for auth bypass in tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_admin_user():
    """Returns a mock admin User to bypass auth in tests."""
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "admin"
    user.full_name = "Admin User"
    user.is_active = True
    user.password_hash = "hashed"
    return user


# ---------------------------------------------------------------------------
# FastAPI app with overrides
# ---------------------------------------------------------------------------

@pytest.fixture
def app_with_db_override(override_get_db, mock_admin_user):
    """Returns the FastAPI app with the DB and auth dependencies overridden."""
    with patch("subprocess.run"):  # Prevent alembic migrations in lifespan
        from maestro.main import app
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: mock_admin_user
        app.dependency_overrides[can_view] = lambda: mock_admin_user
        app.dependency_overrides[can_approve] = lambda: mock_admin_user
        app.dependency_overrides[can_operate] = lambda: mock_admin_user
        app.dependency_overrides[can_admin] = lambda: mock_admin_user
        app.dependency_overrides[get_user_permissions] = lambda: {
            "can_operate": True, "can_approve": True, "can_admin": True
        }
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def async_client(app_with_db_override):
    """Async HTTP client for testing endpoints."""
    transport = ASGITransport(app=app_with_db_override)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Model factories
# ---------------------------------------------------------------------------

@pytest.fixture
def make_descriptor():
    """Factory for OrchestratorDescriptor instances."""
    def _factory(id=1, name="test-release", yaml_content=SAMPLE_RELEASE_YAML):
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = id
        descriptor.name = name
        descriptor.yaml = yaml_content
        return descriptor
    return _factory


@pytest.fixture
def make_execution():
    """Factory for ReleaseExecution instances."""
    def _factory(
        id=1,
        name="test-release",
        status=ExecutionStatus.PENDING,
        message=None,
        orchestrator_descriptor_id=1,
    ):
        execution = MagicMock(spec=ReleaseExecution)
        execution.id = id
        execution.name = name
        execution.status = status
        execution.message = message
        execution.orchestrator_descriptor_id = orchestrator_descriptor_id
        return execution
    return _factory


@pytest.fixture
def make_step_execution():
    """Factory for ReleaseStepExecution instances."""
    def _factory(
        id=1,
        release_execution_id=1,
        stage_id="stage-1",
        step_id="step-1",
        status=ExecutionStatus.PENDING,
        message=None,
        job_execution_correlation_id=None,
        job_input_id=None,
    ):
        step = MagicMock(spec=ReleaseStepExecution)
        step.id = id
        step.release_execution_id = release_execution_id
        step.stage_id = stage_id
        step.step_id = step_id
        step.status = status
        step.message = message
        step.job_execution_correlation_id = job_execution_correlation_id
        step.job_input_id = job_input_id
        return step
    return _factory


@pytest.fixture
def make_step_event():
    """Factory for StepEvent instances."""
    def _factory(id=1, job_execution_correlation_id=100, message="Build started"):
        event = MagicMock(spec=StepEvent)
        event.id = id
        event.job_execution_correlation_id = job_execution_correlation_id
        event.message = message
        return event
    return _factory
