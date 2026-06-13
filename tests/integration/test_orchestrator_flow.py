"""
Integration tests for the Orchestrator flow.

Tests the full lifecycle:
- Upload release YAML → persists in real DB
- Dry-run → validates with mocked GitHub/Jenkins APIs
- Execute release → creates execution + steps in real DB
- Retry step → resets failed step status in DB

All tests use a real PostgreSQL database and mock external HTTP APIs.
"""
import re

import pytest

from maestro.schemas.enums import ExecutionStatus
from tests.integration.conftest import SAMPLE_RELEASE_YAML

pytestmark = [
    pytest.mark.integration,
    pytest.mark.httpx_mock(assert_all_responses_were_requested=False, assert_all_requests_were_expected=False),
]


# ===========================================================================
# Upload Config (save descriptor)
# ===========================================================================


class TestUploadConfig:
    async def test_upload_yaml_success(self, client, mock_github_repo_exists, mock_jenkins_job_exists):
        """Upload a valid YAML file → descriptor saved in DB."""
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("release.yaml", SAMPLE_RELEASE_YAML.encode(), "application/x-yaml")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] is not None
        assert "sucesso" in data["message"]

    async def test_upload_yaml_duplicate_name(self, client, mock_github_repo_exists, mock_jenkins_job_exists):
        """Uploading the same YAML twice should fail with duplicate error."""
        yaml_content = SAMPLE_RELEASE_YAML.replace("integration-test-release", "duplicate-test")

        # First upload
        response1 = await client.post(
            "/orchestrator/config",
            files={"file": ("r1.yaml", yaml_content.encode(), "application/x-yaml")},
        )
        assert response1.status_code == 200

        # Second upload with same name
        response2 = await client.post(
            "/orchestrator/config",
            files={"file": ("r2.yaml", yaml_content.encode(), "application/x-yaml")},
        )
        assert response2.status_code == 400
        assert "Já existe" in response2.json()["detail"]

    async def test_upload_invalid_yaml(self, client):
        """Invalid YAML content should return 400."""
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("bad.yaml", b"not: valid: yaml: {{{", "application/x-yaml")},
        )
        assert response.status_code == 400
        assert "Erro de validação" in response.json()["detail"]

    async def test_upload_wrong_extension(self, client):
        """Non-YAML file extension should be rejected."""
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("config.txt", b"content", "text/plain")},
        )
        assert response.status_code == 400
        assert "extensão" in response.json()["detail"]

    async def test_upload_invalid_schema(self, client):
        """YAML with wrong schema (kind != Release) should fail."""
        bad_schema = "apiVersion: v1\nkind: NotRelease\nmetadata:\n  name: bad\n  author: x\nspec:\n  stages: []\n"
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("bad.yaml", bad_schema.encode(), "application/x-yaml")},
        )
        assert response.status_code == 400

    async def test_upload_branch_not_found_fails_validation(self, client, httpx_mock):
        """If repository doesn't exist in GitHub, upload should fail validation."""
        # Mock GitHub repo check → 404
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/[^/]+/[^/]+$"),
            status_code=404,
        )
        # Mock Jenkins job → exists
        httpx_mock.add_response(
            url=re.compile(r".*/api/json$"),
            status_code=200,
            json={"name": "deploy"},
        )

        yaml_content = SAMPLE_RELEASE_YAML.replace("integration-test-release", "repo-fail-test")
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("r.yaml", yaml_content.encode(), "application/x-yaml")},
        )
        assert response.status_code == 400
        assert "não encontrado" in response.json()["detail"]


# ===========================================================================
# Dry-Run
# ===========================================================================


class TestDryRun:
    @pytest.fixture(autouse=True)
    async def _setup_descriptor(self, client, httpx_mock):
        """Upload a descriptor before each dry-run test."""
        # Mock validations for upload (repo exists + jenkins job exists)
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/[^/]+/[^/]+$"),
            status_code=200,
            json={"name": "my-repo"},
            is_reusable=True,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/api/json$"),
            status_code=200,
            json={"name": "deploy"},
            is_reusable=True,
        )

        yaml_content = SAMPLE_RELEASE_YAML.replace("integration-test-release", "dry-run-test")
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("r.yaml", yaml_content.encode(), "application/x-yaml")},
        )
        assert response.status_code == 200

    async def test_dry_run_all_valid(self, client, httpx_mock):
        """Dry-run with all checks passing returns valid=True."""
        # Mock branch exists
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/branches/.*"),
            status_code=200,
        )
        # Mock PR found
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls\?.*"),
            json=[{"number": 42, "state": "open", "title": "PR"}],
        )
        # Mock PR details clean
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls/42$"),
            json={"number": 42, "state": "open", "title": "PR", "mergeable_state": "clean", "mergeable": True},
        )
        # Mock Jenkins job exists
        httpx_mock.add_response(
            url=re.compile(r".*/api/json$"),
            status_code=200,
            json={"name": "deploy"},
        )

        response = await client.post("/orchestrator/dry-run", json={"name": "dry-run-test"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["name"] == "dry-run-test"
        assert len(data["stages"]) == 1
        step = data["stages"][0]["steps"][0]
        assert step["branch_exists"] is True
        assert step["pr_found"] is True
        assert step["pr_is_clean"] is True
        assert step["jenkins_job_exists"] is True

    async def test_dry_run_not_found(self, client):
        """Dry-run on a nonexistent descriptor returns 400."""
        response = await client.post("/orchestrator/dry-run", json={"name": "nonexistent-xyz"})
        assert response.status_code == 400
        assert "não encontrado" in response.json()["detail"]

    async def test_dry_run_branch_missing(self, client, httpx_mock):
        """Dry-run with missing branch returns valid=False."""
        # Mock branch NOT exists
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/branches/.*"),
            status_code=404,
        )
        # Mock no PR (branch doesn't exist)
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls\?.*"),
            json=[],
        )
        # Mock Jenkins job exists
        httpx_mock.add_response(
            url=re.compile(r".*/api/json$"),
            status_code=200,
            json={"name": "deploy"},
        )

        response = await client.post("/orchestrator/dry-run", json={"name": "dry-run-test"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["stages"][0]["steps"][0]["branch_exists"] is False


# ===========================================================================
# Execute Release
# ===========================================================================


class TestExecuteRelease:
    @pytest.fixture(autouse=True)
    async def _setup_descriptor(self, client, httpx_mock):
        """Upload a descriptor before execute tests."""
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/[^/]+/[^/]+$"),
            status_code=200,
            json={"name": "my-repo"},
            is_reusable=True,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/api/json$"),
            status_code=200,
            json={"name": "deploy"},
            is_reusable=True,
        )

        yaml_content = SAMPLE_RELEASE_YAML.replace("integration-test-release", "execute-test")
        response = await client.post(
            "/orchestrator/config",
            files={"file": ("r.yaml", yaml_content.encode(), "application/x-yaml")},
        )
        assert response.status_code == 200

    async def test_execute_release_success(self, client, httpx_mock):
        """Execute a release creates execution + steps in DB and returns execution ID."""
        # Mock GitHub: PR exists and is clean
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls\?.*"),
            json=[{"number": 1, "state": "open", "title": "Feature PR"}],
        )
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls/1$"),
            json={"number": 1, "state": "open", "title": "Feature PR", "mergeable_state": "clean", "mergeable": True},
        )
        # Mock Jenkins trigger
        httpx_mock.add_response(
            url=re.compile(r".*/buildWithParameters"),
            status_code=201,
            headers={"Location": "http://jenkins:8080/queue/item/1/"},
            is_reusable=True,
            is_optional=True,
        )
        # Mock Jenkins queue poll
        httpx_mock.add_response(
            url=re.compile(r".*/queue/item/.*/api/json$"),
            json={"executable": {"number": 100}},
            is_reusable=True,
            is_optional=True,
        )

        response = await client.post("/orchestrator/execute", json={"name": "execute-test"})
        assert response.status_code == 200
        data = response.json()
        assert data["release_execution_id"] is not None
        assert "sucesso" in data["message"]

        # Execute succeeded - execution was created in DB
        exec_id = data["release_execution_id"]
        assert exec_id > 0

    async def test_execute_release_not_found(self, client):
        """Execute a nonexistent release returns 400."""
        response = await client.post("/orchestrator/execute", json={"name": "no-such-release"})
        assert response.status_code == 400
        assert "não encontrado" in response.json()["detail"]

    async def test_execute_release_duplicate(self, client, httpx_mock):
        """Execute the same release twice should fail (already has execution)."""
        # Mock GitHub
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls\?.*"),
            json=[{"number": 1, "state": "open", "title": "PR"}],
        )
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls/1$"),
            json={"number": 1, "state": "open", "title": "PR", "mergeable_state": "clean", "mergeable": True},
        )
        # Mock Jenkins
        httpx_mock.add_response(
            url=re.compile(r".*/buildWithParameters"),
            status_code=201,
            headers={"Location": "http://jenkins:8080/queue/item/1/"},
            is_reusable=True,
            is_optional=True,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/queue/item/.*/api/json$"),
            json={"executable": {"number": 200}},
            is_reusable=True,
            is_optional=True,
        )

        # First execute
        r1 = await client.post("/orchestrator/execute", json={"name": "execute-test"})
        assert r1.status_code == 200

        # Second execute should fail
        r2 = await client.post("/orchestrator/execute", json={"name": "execute-test"})
        assert r2.status_code == 400
        assert "Já existe" in r2.json()["detail"]

    async def test_execute_release_pr_not_clean(self, client, httpx_mock):
        """Execute fails when PR is not clean."""
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls\?.*"),
            json=[{"number": 1, "state": "open", "title": "PR"}],
        )
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls/1$"),
            json={"number": 1, "state": "open", "title": "PR", "mergeable_state": "dirty", "mergeable": False},
        )

        response = await client.post("/orchestrator/execute", json={"name": "execute-test"})
        assert response.status_code == 400
        assert "clean" in response.json()["detail"]


# ===========================================================================
# Retry Step
# ===========================================================================


class TestRetryStep:
    async def test_retry_step_not_found(self, client):
        """Retry a nonexistent step returns 400."""
        response = await client.post("/orchestrator/retry-step/99999")
        assert response.status_code == 400
        assert "não encontrado" in response.json()["detail"]

    async def test_retry_step_full_flow(self, client, db_engine, httpx_mock):
        """Full flow: upload → execute → mark step as failed → retry."""
        # Setup: Upload descriptor
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/[^/]+/[^/]+$"),
            status_code=200,
            json={"name": "my-repo"},
            is_reusable=True,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/api/json$"),
            status_code=200,
            json={"name": "deploy"},
            is_reusable=True,
        )

        yaml_content = SAMPLE_RELEASE_YAML.replace("integration-test-release", "retry-flow-test")
        upload = await client.post(
            "/orchestrator/config",
            files={"file": ("r.yaml", yaml_content.encode(), "application/x-yaml")},
        )
        assert upload.status_code == 200

        # Execute
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls\?.*"),
            json=[{"number": 1, "state": "open", "title": "PR"}],
        )
        httpx_mock.add_response(
            url=re.compile(r".*api\.github\.com/repos/.*/pulls/1$"),
            json={"number": 1, "state": "open", "title": "PR", "mergeable_state": "clean", "mergeable": True},
        )
        httpx_mock.add_response(
            url=re.compile(r".*/buildWithParameters"),
            status_code=201,
            headers={"Location": "http://jenkins:8080/queue/item/1/"},
            is_reusable=True,
            is_optional=True,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/queue/item/.*/api/json$"),
            json={"executable": {"number": 300}},
            is_reusable=True,
            is_optional=True,
        )

        exec_response = await client.post("/orchestrator/execute", json={"name": "retry-flow-test"})
        assert exec_response.status_code == 200
        exec_id = exec_response.json()["release_execution_id"]

        # Get step ID from DB
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.future import select

        from maestro.database.models import ReleaseStepExecution

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(ReleaseStepExecution).where(ReleaseStepExecution.release_execution_id == exec_id)
            )
            step_row = result.scalars().first()
            assert step_row is not None
            step_id = step_row.id

        # Manually mark step as failure (simulate Jenkins failure callback)
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.future import select

        from maestro.database.models import ReleaseStepExecution

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(select(ReleaseStepExecution).where(ReleaseStepExecution.id == step_id))
            step = result.scalars().first()
            step.status = ExecutionStatus.FAILURE
            step.message = "Build failed"
            session.add(step)
            await session.commit()

        # Retry the failed step
        httpx_mock.add_response(
            url=re.compile(r".*/buildWithParameters"),
            status_code=201,
            headers={"Location": "http://jenkins:8080/queue/item/2/"},
            is_reusable=True,
            is_optional=True,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/queue/item/.*/api/json$"),
            json={"executable": {"number": 301}},
            is_reusable=True,
            is_optional=True,
        )

        retry_response = await client.post(f"/orchestrator/retry-step/{step_id}")
        assert retry_response.status_code == 200
        assert retry_response.json()["step_execution_id"] == step_id


# ===========================================================================
# Get Status & Details
# ===========================================================================


class TestStatusAndDetails:
    async def test_status_not_found(self, client):
        """Status for nonexistent release returns 404."""
        response = await client.get("/orchestrator/status/absolutely-nonexistent")
        assert response.status_code == 404
