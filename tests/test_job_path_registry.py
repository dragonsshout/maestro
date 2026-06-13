"""
Tests for the Job Path Registry feature.
Covers: JobPathRegistryRepository, JobPathRegistryService, resolve_job_path_async, UI routes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from maestro.database.models import JobPathRegistry
from maestro.repositories.job_path_registry import JobPathRegistryRepository
from maestro.schemas.orchestrator import JobSchema, ReleaseSpecSchema, StageSchema, StepSchema
from maestro.services.job_path_registry import JobPathRegistryService
from maestro.services.job_path_resolver import resolve_job_path, resolve_job_path_async

# ===========================================================================
# JobPathRegistryRepository
# ===========================================================================


class TestJobPathRegistryRepository:
    @pytest.fixture
    def repo(self, mock_db_session):
        return JobPathRegistryRepository(db=mock_db_session)

    async def test_get_by_repository_and_environment_found(self, repo, mock_db_session):
        entry = MagicMock(spec=JobPathRegistry)
        entry.repository = "my-repo"
        entry.environment = "PRD"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = entry
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_by_repository_and_environment("my-repo", "PRD")
        assert result.repository == "my-repo"
        assert result.environment == "PRD"

    async def test_get_by_repository_and_environment_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_by_repository_and_environment("nonexistent", "PRD")
        assert result is None

    async def test_get_all_no_search(self, repo, mock_db_session):
        e1 = MagicMock(spec=JobPathRegistry)
        e2 = MagicMock(spec=JobPathRegistry)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [e1, e2]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_all(skip=0, limit=15)
        assert len(result) == 2

    async def test_get_all_with_search(self, repo, mock_db_session):
        e1 = MagicMock(spec=JobPathRegistry)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [e1]
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_all(skip=0, limit=15, search="api")
        assert len(result) == 1

    async def test_get_all_empty(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_all()
        assert result == []

    async def test_get_count_no_search(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_count()
        assert result == 42

    async def test_get_count_with_search(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_db_session.execute.return_value = mock_result

        result = await repo.get_count(search="api")
        assert result == 5

    async def test_upsert_new_entry(self, repo, mock_db_session):
        """When entry doesn't exist, should add it."""
        # get_by_repository_and_environment returns None (not found)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        entry = JobPathRegistry(
            repository="new-repo",
            environment="PRD",
            domain="my-domain",
            type="jenkins",
            path="job/PRD/job/my-domain/job/new-repo",
        )

        await repo.upsert(entry)

        mock_db_session.add.assert_called_once_with(entry)
        mock_db_session.commit.assert_awaited()
        mock_db_session.refresh.assert_awaited_once_with(entry)

    async def test_upsert_existing_entry(self, repo, mock_db_session):
        """When entry exists, should update fields."""
        existing = MagicMock(spec=JobPathRegistry)
        existing.repository = "my-repo"
        existing.environment = "PRD"
        existing.domain = "old-domain"
        existing.type = "jenkins"
        existing.path = "job/PRD/job/old-domain/job/my-repo"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = existing
        mock_db_session.execute.return_value = mock_result

        entry = JobPathRegistry(
            repository="my-repo",
            environment="PRD",
            domain="new-domain",
            type="jenkins",
            path="job/PRD/job/new-domain/job/my-repo",
        )

        await repo.upsert(entry)

        assert existing.domain == "new-domain"
        assert existing.path == "job/PRD/job/new-domain/job/my-repo"
        mock_db_session.commit.assert_awaited()
        mock_db_session.refresh.assert_awaited_once_with(existing)

    async def test_upsert_many(self, repo, mock_db_session):
        """Should call upsert for each entry and return the count."""
        # Mock get_by_repository_and_environment to return None (new entries)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        entries = [
            JobPathRegistry(repository="repo-a", environment="PRD", type="jenkins", path="job/PRD/job/d/job/repo-a"),
            JobPathRegistry(repository="repo-b", environment="PRD", type="jenkins", path="job/PRD/job/d/job/repo-b"),
            JobPathRegistry(repository="repo-c", environment="UAT", type="jenkins", path="job/UAT/job/d/job/repo-c"),
        ]

        count = await repo.upsert_many(entries)
        assert count == 3

    async def test_delete_found(self, repo, mock_db_session):
        entry = MagicMock(spec=JobPathRegistry)
        entry.id = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = entry
        mock_db_session.execute.return_value = mock_result

        result = await repo.delete(1)
        assert result is True
        mock_db_session.delete.assert_awaited_once_with(entry)
        mock_db_session.commit.assert_awaited()

    async def test_delete_not_found(self, repo, mock_db_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await repo.delete(999)
        assert result is False


# ===========================================================================
# JobPathRegistryService
# ===========================================================================


class TestJobPathRegistryService:
    @pytest.fixture
    def service(self):
        svc = JobPathRegistryService.__new__(JobPathRegistryService)
        svc.repository = AsyncMock()
        svc.repository.db = AsyncMock()
        return svc

    async def test_get_all_paginated(self, service):
        entries = [MagicMock(spec=JobPathRegistry) for _ in range(3)]
        service.repository.get_all = AsyncMock(return_value=entries)
        service.repository.get_count = AsyncMock(return_value=30)

        result, total_pages = await service.get_all_paginated(page=1, per_page=15)

        assert len(result) == 3
        assert total_pages == 2
        service.repository.get_all.assert_awaited_once_with(skip=0, limit=15, search=None)

    async def test_get_all_paginated_with_search(self, service):
        service.repository.get_all = AsyncMock(return_value=[])
        service.repository.get_count = AsyncMock(return_value=0)

        result, total_pages = await service.get_all_paginated(page=1, per_page=15, search="api")

        assert result == []
        assert total_pages == 1
        service.repository.get_all.assert_awaited_once_with(skip=0, limit=15, search="api")

    async def test_get_all_paginated_page_2(self, service):
        service.repository.get_all = AsyncMock(return_value=[])
        service.repository.get_count = AsyncMock(return_value=20)

        _, total_pages = await service.get_all_paginated(page=2, per_page=15)

        assert total_pages == 2
        service.repository.get_all.assert_awaited_once_with(skip=15, limit=15, search=None)

    def test_parse_jenkins_tree_basic(self, service):
        """Test parsing a basic Jenkins tree structure."""
        jenkins_base_url = "http://jenkins.dev.shared.cld.internal"
        data = {
            "jobs": [
                {
                    "name": "UAT",
                    "url": f"{jenkins_base_url}/job/UAT/",
                    "jobs": [
                        {
                            "name": "risk-energy",
                            "url": f"{jenkins_base_url}/job/UAT/job/risk-energy/",
                            "jobs": [
                                {
                                    "name": "function-autenticar-securitysvc",
                                    "url": (
                                        f"{jenkins_base_url}/job/UAT/job/risk-energy"
                                        "/job/function-autenticar-securitysvc/"
                                    ),
                                },
                                {
                                    "name": "api-gateway",
                                    "url": f"{jenkins_base_url}/job/UAT/job/risk-energy/job/api-gateway/",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "PRD",
                    "url": f"{jenkins_base_url}/job/PRD/",
                    "jobs": [
                        {
                            "name": "payments",
                            "url": f"{jenkins_base_url}/job/PRD/job/payments/",
                            "jobs": [
                                {
                                    "name": "payment-service",
                                    "url": f"{jenkins_base_url}/job/PRD/job/payments/job/payment-service/",
                                },
                            ],
                        },
                    ],
                },
            ],
        }

        entries = service._parse_jenkins_tree(data, jenkins_base_url)

        assert len(entries) == 3

        # First entry: UAT/risk-energy/function-autenticar-securitysvc
        assert entries[0].repository == "function-autenticar-securitysvc"
        assert entries[0].environment == "UAT"
        assert entries[0].domain == "risk-energy"
        assert entries[0].type == "jenkins"
        assert entries[0].path == "job/UAT/job/risk-energy/job/function-autenticar-securitysvc"

        # Second entry: UAT/risk-energy/api-gateway
        assert entries[1].repository == "api-gateway"
        assert entries[1].environment == "UAT"
        assert entries[1].domain == "risk-energy"

        # Third entry: PRD/payments/payment-service
        assert entries[2].repository == "payment-service"
        assert entries[2].environment == "PRD"
        assert entries[2].domain == "payments"
        assert entries[2].path == "job/PRD/job/payments/job/payment-service"

    def test_parse_jenkins_tree_empty(self, service):
        """Test parsing an empty Jenkins tree."""
        entries = service._parse_jenkins_tree({"jobs": []}, "http://jenkins:8080")
        assert entries == []

    def test_parse_jenkins_tree_missing_jobs_at_level_2(self, service):
        """Test parsing when some folders have no sub-jobs."""
        data = {
            "jobs": [
                {
                    "name": "PRD",
                    "url": "http://j/job/PRD/",
                    "jobs": [
                        {
                            "name": "empty-domain",
                            "url": "http://j/job/PRD/job/empty-domain/",
                            # No "jobs" key at this level
                        },
                    ],
                },
            ],
        }

        entries = service._parse_jenkins_tree(data, "http://j")
        assert entries == []

    def test_parse_jenkins_tree_missing_name(self, service):
        """Test parsing when a job entry is missing the name field."""
        data = {
            "jobs": [
                {
                    "name": "PRD",
                    "url": "http://j/job/PRD/",
                    "jobs": [
                        {
                            "name": "domain",
                            "url": "http://j/job/PRD/job/domain/",
                            "jobs": [
                                {"url": "http://j/job/PRD/job/domain/job/no-name/"},  # missing "name"
                                {"name": "valid-repo", "url": "http://j/job/PRD/job/domain/job/valid-repo/"},
                            ],
                        },
                    ],
                },
            ],
        }

        entries = service._parse_jenkins_tree(data, "http://j")
        assert len(entries) == 1
        assert entries[0].repository == "valid-repo"

    def test_extract_path_from_url_standard(self, service):
        """Test extracting relative path from a standard Jenkins job URL."""
        jenkins_base_url = "http://jenkins.dev.shared.cld.internal"
        job_url = f"{jenkins_base_url}/job/UAT/job/risk-energy/job/my-repo/"

        path = service._extract_path_from_url(job_url, jenkins_base_url)
        assert path == "job/UAT/job/risk-energy/job/my-repo"

    def test_extract_path_from_url_different_host(self, service):
        """Test fallback when URL doesn't start with the base."""
        job_url = "http://other-jenkins/job/PRD/job/domain/job/repo/"
        jenkins_base_url = "http://jenkins:8080"

        path = service._extract_path_from_url(job_url, jenkins_base_url)
        assert path == "job/PRD/job/domain/job/repo"

    @patch("maestro.services.app_settings.get_integration_settings")
    async def test_discover_from_jenkins_no_url_configured(self, mock_get_settings, service):
        """Should raise ValueError when Jenkins URL is not configured."""
        mock_get_settings.return_value = MagicMock(jenkins_url=None)

        with pytest.raises(ValueError, match="URL base do Jenkins não configurada"):
            await service.discover_from_jenkins()

    @patch("maestro.services.job_path_registry.httpx.AsyncClient")
    @patch("maestro.services.app_settings.get_integration_settings")
    async def test_discover_from_jenkins_success(self, mock_get_settings, mock_client_cls, service):
        """Test full discovery flow with mocked HTTP."""
        mock_get_settings.return_value = MagicMock(
            jenkins_url="http://jenkins:8080",
            jenkins_username="user",
            jenkins_token="token",
            http_trust_env=True,
        )

        jenkins_response = {
            "jobs": [
                {
                    "name": "PRD",
                    "url": "http://jenkins:8080/job/PRD/",
                    "jobs": [
                        {
                            "name": "core",
                            "url": "http://jenkins:8080/job/PRD/job/core/",
                            "jobs": [
                                {
                                    "name": "api-service",
                                    "url": "http://jenkins:8080/job/PRD/job/core/job/api-service/",
                                },
                            ],
                        },
                    ],
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = jenkins_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        service.repository.upsert_many = AsyncMock(return_value=1)

        result = await service.discover_from_jenkins()

        assert result.total_discovered == 1
        assert result.total_upserted == 1
        assert "Discovery concluído" in result.message
        service.repository.upsert_many.assert_awaited_once()


# ===========================================================================
# resolve_job_path_async
# ===========================================================================


class TestResolveJobPath:
    def _make_step(self, repository="my-repo", job_path=None) -> StepSchema:
        """Helper to create a StepSchema."""
        job = JobSchema(type="jenkins", path=job_path) if job_path else None
        return StepSchema(id="step-1", repository=repository, release="release/v1", job=job)

    def _make_spec(self, environment="PRD") -> ReleaseSpecSchema:
        """Helper to create a ReleaseSpecSchema."""
        return ReleaseSpecSchema(
            environment=environment,
            stages=[StageSchema(id="stage-1", steps=[])],
        )

    def test_resolve_job_path_explicit(self):
        """When job.path is explicit, should return it directly."""
        step = self._make_step(job_path="job/custom/path")
        spec = self._make_spec()

        result = resolve_job_path(step, spec)
        assert result == "job/custom/path"

    def test_resolve_job_path_fallback_default_env(self):
        """When no job.path, should generate the fallback pattern."""
        step = self._make_step(repository="api-teste")
        spec = self._make_spec(environment="PRD")

        result = resolve_job_path(step, spec)
        assert result == "job/PRD/job/api-teste/job/api-teste"

    def test_resolve_job_path_fallback_custom_env(self):
        """Fallback should use the spec environment."""
        step = self._make_step(repository="web-app")
        spec = self._make_spec(environment="UAT")

        result = resolve_job_path(step, spec)
        assert result == "job/UAT/job/web-app/job/web-app"

    def test_resolve_job_path_fallback_no_env_defaults_prd(self):
        """When environment is None, should default to PRD."""
        step = self._make_step(repository="svc")
        spec = self._make_spec(environment=None)

        result = resolve_job_path(step, spec)
        assert result == "job/PRD/job/svc/job/svc"

    async def test_resolve_job_path_async_explicit_path(self):
        """Explicit job.path should always take priority."""
        step = self._make_step(job_path="job/explicit/path")
        spec = self._make_spec()
        registry_repo = AsyncMock(spec=JobPathRegistryRepository)

        result = await resolve_job_path_async(step, spec, registry_repo)

        assert result == "job/explicit/path"
        # Should not query the DB when path is explicit
        registry_repo.get_by_repository_and_environment.assert_not_awaited()

    async def test_resolve_job_path_async_found_in_registry(self):
        """When registry has a matching entry, should return its path."""
        step = self._make_step(repository="api-service")
        spec = self._make_spec(environment="PRD")

        registry_entry = MagicMock(spec=JobPathRegistry)
        registry_entry.path = "job/PRD/job/core-domain/job/api-service"

        registry_repo = AsyncMock(spec=JobPathRegistryRepository)
        registry_repo.get_by_repository_and_environment = AsyncMock(return_value=registry_entry)

        result = await resolve_job_path_async(step, spec, registry_repo)

        assert result == "job/PRD/job/core-domain/job/api-service"
        registry_repo.get_by_repository_and_environment.assert_awaited_once_with("api-service", "PRD")

    async def test_resolve_job_path_async_not_in_registry_fallback(self):
        """When registry has no match, should use the fallback pattern."""
        step = self._make_step(repository="unknown-repo")
        spec = self._make_spec(environment="UAT")

        registry_repo = AsyncMock(spec=JobPathRegistryRepository)
        registry_repo.get_by_repository_and_environment = AsyncMock(return_value=None)

        result = await resolve_job_path_async(step, spec, registry_repo)

        assert result == "job/UAT/job/unknown-repo/job/unknown-repo"
        registry_repo.get_by_repository_and_environment.assert_awaited_once_with("unknown-repo", "UAT")

    async def test_resolve_job_path_async_none_environment_defaults_prd(self):
        """When environment is None, should default to PRD for registry lookup."""
        step = self._make_step(repository="my-svc")
        spec = self._make_spec(environment=None)

        registry_repo = AsyncMock(spec=JobPathRegistryRepository)
        registry_repo.get_by_repository_and_environment = AsyncMock(return_value=None)

        result = await resolve_job_path_async(step, spec, registry_repo)

        assert result == "job/PRD/job/my-svc/job/my-svc"
        registry_repo.get_by_repository_and_environment.assert_awaited_once_with("my-svc", "PRD")


# ===========================================================================
# UI Routes for Job Registry
# ===========================================================================


class TestJobRegistryRoutes:
    async def test_job_registry_page(self, async_client):
        """GET /ui/job-registry/ should return the page."""
        response = await async_client.get("/ui/job-registry/")
        assert response.status_code == 200
        assert "Job Registry" in response.text

    async def test_job_registry_partials_list(self, async_client, mock_db_session):
        """GET /ui/job-registry/partials/list should return HTML partial."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(side_effect=[mock_result, mock_count_result])

        response = await async_client.get("/ui/job-registry/partials/list")
        assert response.status_code == 200
        assert "job-registry-container" in response.text

    async def test_job_registry_partials_list_with_search(self, async_client, mock_db_session):
        """GET /ui/job-registry/partials/list?search=api should filter."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(side_effect=[mock_result, mock_count_result])

        response = await async_client.get("/ui/job-registry/partials/list?search=api")
        assert response.status_code == 200

    @patch("maestro.services.job_path_registry.httpx.AsyncClient")
    @patch("maestro.services.app_settings.get_integration_settings")
    async def test_job_registry_discover(self, mock_get_settings, mock_client_cls, async_client, mock_db_session):
        """POST /ui/job-registry/discover should trigger discovery."""
        mock_get_settings.return_value = MagicMock(
            jenkins_url="http://jenkins:8080",
            jenkins_username="user",
            jenkins_token="token",
            http_trust_env=True,
        )

        jenkins_response = {
            "jobs": [
                {
                    "name": "PRD",
                    "url": "http://jenkins:8080/job/PRD/",
                    "jobs": [
                        {
                            "name": "core",
                            "url": "http://jenkins:8080/job/PRD/job/core/",
                            "jobs": [
                                {
                                    "name": "svc",
                                    "url": "http://jenkins:8080/job/PRD/job/core/job/svc/",
                                },
                            ],
                        },
                    ],
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = jenkins_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        # Mock the upsert and the subsequent get_all for the refreshed table
        mock_result_upsert = MagicMock()
        mock_result_upsert.scalars.return_value.first.return_value = None  # upsert: not existing

        mock_result_list = MagicMock()
        mock_result_list.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_db_session.execute = AsyncMock(side_effect=[mock_result_upsert, mock_result_list, mock_count_result])

        response = await async_client.post("/ui/job-registry/discover")
        assert response.status_code == 200

    @patch("maestro.services.app_settings.get_integration_settings")
    async def test_job_registry_discover_no_jenkins_url(self, mock_get_settings, async_client, mock_db_session):
        """POST /ui/job-registry/discover with no Jenkins URL returns error."""
        mock_get_settings.return_value = MagicMock(jenkins_url=None)

        response = await async_client.post("/ui/job-registry/discover")
        assert response.status_code == 200
        assert "URL base do Jenkins" in response.text or "job-registry-container" in response.text
