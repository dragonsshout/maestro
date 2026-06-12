"""
Tests for disabled-state rendering in UI templates.

Verifies that when a user has restricted permissions (all False),
the HTML contains tooltip text and disabled attributes on action buttons.
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
from maestro.database.models import User
from maestro.database.session import get_db


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def app_as_viewer(mock_session):
    """App fixture with a user who has NO permissions (viewer only)."""
    with patch("subprocess.run"):
        from maestro.main import app

        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "viewer"
        mock_user.full_name = "Viewer User"
        mock_user.is_active = True

        async def _get_db_override():
            yield mock_session

        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[can_view] = lambda: mock_user
        app.dependency_overrides[can_approve] = lambda: mock_user
        app.dependency_overrides[can_operate] = lambda: mock_user
        app.dependency_overrides[can_admin] = lambda: mock_user
        app.dependency_overrides[get_user_permissions] = lambda: {
            "can_operate": False,
            "can_approve": False,
            "can_admin": False,
        }
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def viewer_client(app_as_viewer):
    transport = ASGITransport(app=app_as_viewer)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestReleasesDisabledState:
    """Test that releases page shows disabled buttons and tooltips for viewers."""

    async def test_releases_page_shows_disabled_upload_button(self, viewer_client):
        """A user without can_operate sees a disabled upload button with tooltip."""
        response = await viewer_client.get("/ui/releases")
        assert response.status_code == 200
        html = response.text

        # The submit button should be disabled
        assert "btn-disabled" in html
        assert "disabled" in html
        # Tooltip explaining the required permission should be present
        assert "Voce nao tem permissao para enviar releases" in html
        # The file input should also be disabled
        assert 'disabled' in html

    @patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository.get_all")
    @patch("maestro.repositories.orchestrator.OrchestratorDescriptorRepository.get_count")
    @patch("maestro.repositories.execution.ExecutionRepository.get_active_execution_by_name")
    async def test_releases_table_shows_disabled_execute_button(
        self, mock_active, mock_count, mock_get_all, viewer_client
    ):
        """A user without can_operate sees disabled Execute/Schedule/Dry-run buttons."""
        descriptor = MagicMock()
        descriptor.id = 1
        descriptor.name = "test-release"
        descriptor.created_at = MagicMock()
        descriptor.created_at.strftime = MagicMock(return_value="01/01/2025 10:00")
        mock_get_all.return_value = [descriptor]
        mock_count.return_value = 1
        mock_active.return_value = None

        response = await viewer_client.get("/ui/partials/releases")
        assert response.status_code == 200
        html = response.text

        # Tooltip text for disabled buttons
        assert "Voce nao tem permissao. Necessario: Operators ou Administrators." in html
        # Multiple disabled buttons (execute, schedule, dry-run)
        assert html.count("btn-disabled") >= 3
        # The YAML button should still be present and NOT disabled
        assert "YAML" in html


class TestExecutionDetailDisabledState:
    """Test that execution detail shows disabled cancel/approve buttons for viewers."""

    @patch("maestro.services.ui.UIService.get_execution_with_stages")
    @patch("maestro.services.settings.UISettingsService.get")
    async def test_execution_detail_disabled_cancel_button(
        self, mock_settings_get, mock_get_execution, viewer_client
    ):
        """A user without can_operate sees a disabled cancel button with tooltip."""
        from maestro.schemas.enums import ExecutionStatus

        execution = MagicMock()
        execution.id = 1
        execution.name = "test-release"
        execution.status = ExecutionStatus.IN_PROGRESS
        execution.message = None
        execution.created_at = MagicMock()
        execution.created_at.strftime = MagicMock(return_value="01/01/2025 10:00")
        execution.orchestrator_descriptor_id = 1

        mock_get_execution.return_value = (execution, [], [])
        mock_settings_get.return_value = None

        response = await viewer_client.get("/ui/execution/1")
        assert response.status_code == 200
        html = response.text

        # Cancel button should be disabled with tooltip
        assert "Voce nao tem permissao. Necessario: Operators ou Administrators." in html
        assert "btn-disabled" in html
        assert "Cancelar" in html

    @patch("maestro.services.ui.UIService.get_execution_with_stages")
    @patch("maestro.services.settings.UISettingsService.get")
    async def test_execution_detail_disabled_approve_buttons(
        self, mock_settings_get, mock_get_execution, viewer_client
    ):
        """A user without can_approve sees disabled approve/deny buttons with tooltip."""
        from maestro.schemas.enums import ExecutionStatus

        execution = MagicMock()
        execution.id = 1
        execution.name = "test-release"
        execution.status = ExecutionStatus.WAITING_APPROVAL
        execution.message = None
        execution.created_at = MagicMock()
        execution.created_at.strftime = MagicMock(return_value="01/01/2025 10:00")
        execution.orchestrator_descriptor_id = 1

        mock_get_execution.return_value = (execution, [], [])
        mock_settings_get.return_value = None

        response = await viewer_client.get("/ui/execution/1")
        assert response.status_code == 200
        html = response.text

        # Approve/Deny buttons should show tooltip about required permission
        assert "Voce nao tem permissao. Necessario: Approver, Operators ou Administrators." in html
        # Both Negar and Aprovar buttons should be disabled
        assert "Negar" in html
        assert "Aprovar" in html
        assert html.count("btn-disabled") >= 2


class TestSidebarLockIcons:
    """Test that sidebar shows lock icons for non-admin users."""

    async def test_sidebar_shows_lock_icons_for_non_admin(self, viewer_client):
        """A user without can_admin sees lock icons on Settings and Users sidebar items."""
        response = await viewer_client.get("/ui/releases")
        assert response.status_code == 200
        html = response.text

        # Lock icon SVG path should appear near Settings and Users links
        # The lock icon SVG uses a specific path for the padlock
        assert "M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6" in html
