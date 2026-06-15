"""
Tests for archive/unarchive releases feature.
Covers: repository filtering, archive/unarchive endpoints, archived page,
and blocking execute/schedule for archived releases.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from maestro.database.models import OrchestratorDescriptor
from maestro.database.session import get_db
from maestro.repositories.orchestrator import OrchestratorDescriptorRepository


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def app_override(mock_session):
    with patch("subprocess.run"):
        from maestro.main import app

        async def _get_db_override():
            yield mock_session

        app.dependency_overrides[get_db] = _get_db_override
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def client(app_override):
    transport = ASGITransport(app=app_override)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ===========================================================================
# Repository Tests
# ===========================================================================


class TestOrchestratorDescriptorRepositoryArchive:
    @pytest.fixture
    def repo(self, mock_session):
        return OrchestratorDescriptorRepository(db=mock_session)

    async def test_get_all_archived_false_filters(self, repo, mock_session):
        """get_all(archived=False) should filter out archived descriptors."""
        d1 = MagicMock(spec=OrchestratorDescriptor)
        d1.archived = 0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [d1]
        mock_session.execute.return_value = mock_result

        result = await repo.get_all(archived=False)
        assert len(result) == 1
        mock_session.execute.assert_awaited_once()

    async def test_get_all_archived_true_filters(self, repo, mock_session):
        """get_all(archived=True) should return only archived descriptors."""
        d1 = MagicMock(spec=OrchestratorDescriptor)
        d1.archived = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [d1]
        mock_session.execute.return_value = mock_result

        result = await repo.get_all(archived=True)
        assert len(result) == 1
        mock_session.execute.assert_awaited_once()

    async def test_get_count_archived_false(self, repo, mock_session):
        """get_count(archived=False) should count only non-archived."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        result = await repo.get_count(archived=False)
        assert result == 5

    async def test_get_count_archived_true(self, repo, mock_session):
        """get_count(archived=True) should count only archived."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 2
        mock_session.execute.return_value = mock_result

        result = await repo.get_count(archived=True)
        assert result == 2

    async def test_set_archived_success(self, repo, mock_session):
        """set_archived should update the descriptor's archived field."""
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = 1
        descriptor.archived = 0

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = descriptor
        mock_session.execute.return_value = mock_result

        result = await repo.set_archived(1, True)
        assert result is not None
        assert descriptor.archived == 1
        mock_session.commit.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(descriptor)

    async def test_set_archived_not_found(self, repo, mock_session):
        """set_archived should return None if descriptor not found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.set_archived(999, True)
        assert result is None
        mock_session.commit.assert_not_awaited()

    async def test_set_unarchived(self, repo, mock_session):
        """set_archived(id, False) should set archived to 0."""
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = 1
        descriptor.archived = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = descriptor
        mock_session.execute.return_value = mock_result

        result = await repo.set_archived(1, False)
        assert result is not None
        assert descriptor.archived == 0


# ===========================================================================
# UI Route Tests
# ===========================================================================


class TestArchiveReleaseUI:
    async def test_archive_release_success(self, client, mock_session):
        """POST /ui/releases/1/archive should return 200 with HX-Trigger."""
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = 1
        descriptor.archived = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = descriptor
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/releases/1/archive")
        assert response.status_code == 200
        assert "refreshReleases" in response.headers.get("hx-trigger", "")

    async def test_archive_release_not_found(self, client, mock_session):
        """POST /ui/releases/999/archive should return 404 when not found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/releases/999/archive")
        assert response.status_code == 404


class TestUnarchiveReleaseUI:
    async def test_unarchive_release_success(self, client, mock_session):
        """POST /ui/releases/1/unarchive should return 200 with HX-Trigger."""
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = 1
        descriptor.archived = 0

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = descriptor
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/releases/1/unarchive")
        assert response.status_code == 200
        assert "refreshReleasesArchived" in response.headers.get("hx-trigger", "")

    async def test_unarchive_release_not_found(self, client, mock_session):
        """POST /ui/releases/999/unarchive should return 404 when not found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/releases/999/unarchive")
        assert response.status_code == 404


class TestArchivedReleasesPage:
    async def test_archived_releases_page(self, client):
        """GET /ui/releases/archived should return 200 HTML."""
        response = await client.get("/ui/releases/archived")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Arquivadas" in response.text


class TestExecuteArchivedRelease:
    async def test_execute_archived_release_blocked(self, client, mock_session):
        """POST /ui/execute/{name} should return error for archived release."""
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = 1
        descriptor.name = "archived-release"
        descriptor.archived = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = descriptor
        mock_session.execute.return_value = mock_result

        response = await client.post("/ui/execute/archived-release")
        assert response.status_code == 200
        assert "arquivada" in response.text.lower()

    @patch("maestro.services.orchestrator.OrchestratorService.execute_release")
    async def test_execute_non_archived_release_allowed(self, mock_execute, client, mock_session):
        """POST /ui/execute/{name} should proceed for non-archived release."""
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = 1
        descriptor.name = "active-release"
        descriptor.archived = 0

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = descriptor
        mock_session.execute.return_value = mock_result

        mock_execute.return_value = 42

        response = await client.post("/ui/execute/active-release")
        assert response.status_code == 200


class TestScheduleArchivedRelease:
    async def test_schedule_archived_release_blocked(self, client, mock_session):
        """POST /ui/schedule/{name} should return error for archived release."""
        descriptor = MagicMock(spec=OrchestratorDescriptor)
        descriptor.id = 1
        descriptor.name = "archived-release"
        descriptor.archived = 1

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = descriptor
        mock_session.execute.return_value = mock_result

        response = await client.post(
            "/ui/schedule/archived-release",
            data={"scheduled_at": "2026-01-01T10:00:00Z"},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200
        assert "arquivada" in response.text.lower()
