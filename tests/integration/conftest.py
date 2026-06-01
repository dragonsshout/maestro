"""
Integration test fixtures.

Spins up a real PostgreSQL container (via podman/docker CLI),
runs Alembic migrations, and provides an async session + httpx AsyncClient
for full end-to-end testing.

External APIs (Jenkins, GitHub) are mocked at the HTTP level via pytest-httpx.
"""
import os
import re
import subprocess
import socket
import time
import asyncio
from contextlib import closing

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from httpx import AsyncClient, ASGITransport

from maestro.database.models import Base
from maestro.database.session import get_db


# ---------------------------------------------------------------------------
# Container management helpers
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _container_runtime() -> str:
    """Detect available container runtime (podman or docker)."""
    for cmd in ("podman", "docker"):
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    pytest.skip("No container runtime (podman/docker) available")


def _wait_for_postgres(host: str, port: int, timeout: int = 30):
    """Wait until PostgreSQL is accepting connections."""
    import psycopg2
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host=host, port=port, user="maestro_test",
                password="maestro_test", dbname="maestro_test"
            )
            conn.close()
            return
        except psycopg2.OperationalError:
            time.sleep(0.5)
    raise TimeoutError(f"PostgreSQL not ready after {timeout}s on port {port}")


# ---------------------------------------------------------------------------
# PostgreSQL container fixture (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def postgres_container():
    """
    Start a PostgreSQL container for the test session.
    Yields the connection URL (asyncpg format).
    Cleans up after all tests.
    """
    runtime = _container_runtime()
    port = _find_free_port()
    container_name = f"maestro-test-pg-{port}"

    # Start postgres container
    subprocess.run(
        [
            runtime, "run", "--rm", "-d",
            "--name", container_name,
            "-e", "POSTGRES_USER=maestro_test",
            "-e", "POSTGRES_PASSWORD=maestro_test",
            "-e", "POSTGRES_DB=maestro_test",
            "-p", f"{port}:5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
    )

    try:
        _wait_for_postgres("localhost", port)
        db_url = f"postgresql+asyncpg://maestro_test:maestro_test@localhost:{port}/maestro_test"
        yield db_url
    finally:
        # Stop and remove container
        subprocess.run([runtime, "rm", "-f", container_name], capture_output=True)


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
def run_migrations(postgres_container):
    """Run Alembic migrations against the test database."""
    # Convert async URL to sync for Alembic
    sync_url = postgres_container.replace("+asyncpg", "")

    env = os.environ.copy()
    env["DB_URL"] = sync_url

    result = subprocess.run(
        ["python3.11", "-m", "alembic", "upgrade", "head"],
        cwd="/projects/sandbox/maestro",
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fallback: create tables directly via SQLAlchemy
        import asyncio
        from sqlalchemy.ext.asyncio import create_async_engine as _create_engine

        async def _create_tables():
            engine = _create_engine(postgres_container)
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
    We use real commits since the app code uses commit().
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_db(postgres_container):
    """Truncate all tables BEFORE each test for isolation (setup-based cleanup)."""
    cleanup_engine = create_async_engine(postgres_container, echo=False)
    async with cleanup_engine.connect() as conn:
        from sqlalchemy import text
        await conn.execute(text("TRUNCATE step_event, release_step_execution, release_execution, orchestrator_descriptor, ui_settings CASCADE"))
        await conn.commit()
    await cleanup_engine.dispose()
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
    """
    from unittest.mock import patch
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    with patch("subprocess.run"):
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
        url=re.compile(r".*api\.github\.com/repos/.*/pulls/\d+$"),
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
