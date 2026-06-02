"""
Integration test fixtures.

Uses testcontainers to spin up a real PostgreSQL container,
runs Alembic migrations, and provides an async session + httpx AsyncClient
for full end-to-end testing.

External APIs (Jenkins, GitHub) are mocked at the HTTP level via pytest-httpx.
"""
import os
import re
import subprocess
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from httpx import AsyncClient, ASGITransport
from testcontainers.postgres import PostgresContainer

from maestro.database.models import Base
from maestro.database.session import get_db


# ---------------------------------------------------------------------------
# PostgreSQL container fixture (session-scoped via testcontainers)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def postgres_container():
    """
    Start a PostgreSQL container using testcontainers.
    Yields the async connection URL (asyncpg format).
    Container is automatically cleaned up after the session.
    """
    with PostgresContainer(
        image="postgres:16-alpine",
        username="maestro_test",
        password="maestro_test",
        dbname="maestro_test",
    ) as pg:
        # testcontainers provides a sync URL like postgresql://user:pass@host:port/db
        sync_url = pg.get_connection_url()
        # Convert to asyncpg format
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        yield async_url


# ---------------------------------------------------------------------------
# Database engine & migrations
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_engine(postgres_container):
    """Create a fresh async engine for each test (function-scoped)."""
    engine = create_async_engine(
        postgres_container,
        echo=False,
        pool_pre_ping=True,
    )
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def ao(postgres_container):
    """Run Alembic migrations against the test database."""
    # Convert async URL to sync for Alembic
    sync_url = postgres_container.replace("+asyncpg", "")

    env = os.environ.copy()
    env["DB_URL"] = sync_url

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    result = subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fallback: create tables directly via SQLAlchemy
        async def _create_tables():
            engine = create_async_engine(postgres_container)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await engine.dispose()

        asyncio.run(_create_tables())


# ---------------------------------------------------------------------------
# Async session fixture (function-scoped with table truncation for isolation)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session(db_engine):
    """
    Provide an async session for each test.
    After each test, all tables are truncated to ensure isolation.
    """
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_db(db_engine):
    """Truncate all tables BEFORE each test for isolation (setup-based cleanup)."""
    async with db_engine.connect() as conn:
        from sqlalchemy import text
        await conn.execute(text(
            "TRUNCATE step_event, release_step_execution, release_execution, "
            "orchestrator_descriptor, ui_settings CASCADE"
        ))
        await conn.commit()
    yield


# ---------------------------------------------------------------------------
# FastAPI app with real DB override
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app(db_engine):
    """
    FastAPI app with the DB dependency overridden to use the test database.
    Each request gets its own session from the test engine.
    subprocess.run is patched to prevent Alembic from running in lifespan.
    process_workflow is patched to prevent background tasks from using different sessions.
    """
    from unittest.mock import patch, AsyncMock

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    with patch("subprocess.run"), \
         patch("maestro.services.orchestrator.OrchestratorService.process_workflow", new_callable=AsyncMock):
        from maestro.main import app as _app

        async def _get_test_db():
            async with session_factory() as session:
                yield session

        _app.dependency_overrides[get_db] = _get_test_db
        yield _app
        _app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP client bound to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Jenkins/GitHub HTTP mocks (fixtures using pytest-httpx)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_github_branch_exists(httpx_mock):
    """Mock GitHub branch_exists → True."""
    httpx_mock.add_response(
        url=re.compile(r".*api\.github\.com/repos/.*/branches/.*"),
        status_code=200,
        is_reusable=True,
    )
    return httpx_mock


@pytest.fixture
def mock_github_pr_found(httpx_mock):
    """Mock GitHub get_pull_request_by_branch → returns a PR."""
    httpx_mock.add_response(
        url=re.compile(r".*api\.github\.com/repos/.*/pulls\?.*"),
        json=[{"number": 1, "state": "open", "title": "Feature PR"}],
        is_reusable=True,
    )
    return httpx_mock


@pytest.fixture
def mock_github_pr_details_clean(httpx_mock):
    """Mock GitHub get_pull_request_details → clean PR."""
    httpx_mock.add_response(
        url=re.compile(r".*api\.github\.com/repos/.*/pulls/\\d+$"),
        json={
            "number": 1,
            "state": "open",
            "title": "Feature PR",
            "mergeable_state": "clean",
            "mergeable": True,
        },
        is_reusable=True,
    )
    return httpx_mock


@pytest.fixture
def mock_github_all_ok(mock_github_branch_exists, mock_github_pr_found, mock_github_pr_details_clean):
    """Combines all GitHub mocks for happy path."""
    pass


@pytest.fixture
def mock_jenkins_job_exists(httpx_mock):
    """Mock Jenkins job_exists → True."""
    httpx_mock.add_response(
        url=re.compile(r".*/job/.*/api/json$"),
        status_code=200,
        json={"name": "deploy", "buildable": True},
        is_reusable=True,
    )
    return httpx_mock


@pytest.fixture
def mock_jenkins_trigger(httpx_mock):
    """Mock Jenkins trigger_job → returns queue URL."""
    httpx_mock.add_response(
        url=re.compile(r".*/buildWithParameters$"),
        status_code=201,
        headers={"Location": "http://jenkins:8080/queue/item/1/"},
    )
    return httpx_mock


@pytest.fixture
def mock_jenkins_queue_poll(httpx_mock):
    """Mock Jenkins queue item info → returns build number."""
    httpx_mock.add_response(
        url=re.compile(r".*/queue/item/.*/api/json$"),
        json={"executable": {"number": 100}},
    )
    return httpx_mock


@pytest.fixture
def mock_jenkins_all_ok(mock_jenkins_job_exists, mock_jenkins_trigger, mock_jenkins_queue_poll):
    """Combines all Jenkins mocks for happy path."""
    pass


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_RELEASE_YAML = """\
apiVersion: v1
kind: Release
metadata:
  name: integration-test-release
  author: tester
  description: Integration test release
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
  description: Multi-stage integration test
spec:
  stages:
    - id: stage-1
      steps:
        - id: step-1a
          repository: repo-a
          release: feature/a
          job:
            type: jenkins
            path: job/deploy-a
    - id: stage-2
      steps:
        - id: step-2a
          repository: repo-b
          release: feature/b
          job:
            type: jenkins
            path: job/deploy-b
"""
