"""Tests for auth routes and authorization enforcement.

Covers:
- Login/logout flow
- Authorization enforcement (group-based access control)
- User management routes (admin only)
- Change password functionality
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
)
from maestro.database.models import User
from maestro.database.session import get_db

# ---------------------------------------------------------------------------
# Helpers: mock users with different permission levels
# ---------------------------------------------------------------------------


def _make_mock_user(user_id=1, username="admin", full_name="Admin User", is_active=True):
    """Create a mock User object."""
    user = MagicMock(spec=User)
    user.id = user_id
    user.username = username
    user.full_name = full_name
    user.is_active = is_active
    user.password_hash = "hashed"
    return user


ADMIN_USER = _make_mock_user(1, "admin", "Admin User")
VIEWER_USER = _make_mock_user(2, "viewer", "Viewer User")
OPERATOR_USER = _make_mock_user(3, "operator", "Operator User")
APPROVER_USER = _make_mock_user(4, "approver", "Approver User")


# ---------------------------------------------------------------------------
# Fixtures: apps with different auth levels
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


@pytest.fixture
def app_as_admin(override_get_db):
    """App with admin-level auth overrides."""
    with patch("subprocess.run"):
        from maestro.main import app
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
        app.dependency_overrides[can_view] = lambda: ADMIN_USER
        app.dependency_overrides[can_approve] = lambda: ADMIN_USER
        app.dependency_overrides[can_operate] = lambda: ADMIN_USER
        app.dependency_overrides[can_admin] = lambda: ADMIN_USER
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
def app_as_viewer(override_get_db):
    """App with viewer-level auth overrides (can_view only)."""
    from fastapi import HTTPException

    def _deny():
        raise HTTPException(status_code=403, detail="Forbidden")

    with patch("subprocess.run"):
        from maestro.main import app
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: VIEWER_USER
        app.dependency_overrides[can_view] = lambda: VIEWER_USER
        app.dependency_overrides[can_approve] = _deny
        app.dependency_overrides[can_operate] = _deny
        app.dependency_overrides[can_admin] = _deny
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
def app_as_operator(override_get_db):
    """App with operator-level auth overrides (can_view + can_operate + can_approve)."""
    from fastapi import HTTPException

    def _deny():
        raise HTTPException(status_code=403, detail="Forbidden")

    with patch("subprocess.run"):
        from maestro.main import app
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: OPERATOR_USER
        app.dependency_overrides[can_view] = lambda: OPERATOR_USER
        app.dependency_overrides[can_approve] = lambda: OPERATOR_USER
        app.dependency_overrides[can_operate] = lambda: OPERATOR_USER
        app.dependency_overrides[can_admin] = _deny
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
def app_as_approver(override_get_db):
    """App with approver-level auth overrides (can_view + can_approve)."""
    from fastapi import HTTPException

    def _deny():
        raise HTTPException(status_code=403, detail="Forbidden")

    with patch("subprocess.run"):
        from maestro.main import app
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: APPROVER_USER
        app.dependency_overrides[can_view] = lambda: APPROVER_USER
        app.dependency_overrides[can_approve] = lambda: APPROVER_USER
        app.dependency_overrides[can_operate] = _deny
        app.dependency_overrides[can_admin] = _deny
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
def app_unauthenticated(override_get_db):
    """App without auth overrides -- triggers NotAuthenticatedException."""
    from maestro.auth.dependencies import NotAuthenticatedException

    def _not_authenticated():
        raise NotAuthenticatedException()

    with patch("subprocess.run"):
        from maestro.main import app
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = _not_authenticated
        app.dependency_overrides[can_view] = _not_authenticated
        app.dependency_overrides[can_approve] = _not_authenticated
        app.dependency_overrides[can_operate] = _not_authenticated
        app.dependency_overrides[can_admin] = _not_authenticated
        yield app
        app.dependency_overrides.clear()


@pytest.fixture
async def client_admin(app_as_admin):
    """AsyncClient with admin privileges."""
    transport = ASGITransport(app=app_as_admin)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client_viewer(app_as_viewer):
    """AsyncClient with viewer-only privileges."""
    transport = ASGITransport(app=app_as_viewer)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client_operator(app_as_operator):
    """AsyncClient with operator privileges."""
    transport = ASGITransport(app=app_as_operator)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client_approver(app_as_approver):
    """AsyncClient with approver privileges."""
    transport = ASGITransport(app=app_as_approver)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client_unauthenticated(app_unauthenticated):
    """AsyncClient with no authentication."""
    transport = ASGITransport(app=app_unauthenticated)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ===========================================================================
# A) Login/Logout flow
# ===========================================================================


class TestLoginLogoutFlow:
    """Test the login and logout endpoints."""

    async def test_get_login_page_returns_200(self, client_unauthenticated: AsyncClient):
        """GET /ui/login returns the login page."""
        response = await client_unauthenticated.get("/ui/login")
        assert response.status_code == 200
        assert "login" in response.text.lower()

    async def test_post_login_valid_credentials_redirects(self, app_as_admin):
        """POST /ui/login with valid credentials sets cookie and redirects."""
        mock_user = _make_mock_user(1, "admin", "Admin")

        with patch("maestro.api.routes.auth.AuthService") as MockAuthService:
            mock_service = AsyncMock()
            mock_service.authenticate = AsyncMock(return_value=mock_user)
            mock_service.create_session_token = MagicMock(return_value="fake-jwt-token")
            MockAuthService.return_value = mock_service

            # Override the Depends() for AuthService
            from maestro.services.auth import AuthService
            app_as_admin.dependency_overrides[AuthService] = lambda: mock_service

            transport = ASGITransport(app=app_as_admin)
            async with AsyncClient(
                transport=transport, base_url="http://test", follow_redirects=False
            ) as client:
                response = await client.post(
                    "/ui/login",
                    data={"username": "admin", "password": "chang3m3"},
                )
                assert response.status_code == 302
                assert response.headers.get("location") == "/ui/"
                assert "maestro_session" in response.headers.get("set-cookie", "")

    async def test_post_login_invalid_credentials_returns_401(self, app_as_admin):
        """POST /ui/login with invalid credentials returns error."""
        mock_service = AsyncMock()
        mock_service.authenticate = AsyncMock(return_value=None)

        from maestro.services.auth import AuthService
        app_as_admin.dependency_overrides[AuthService] = lambda: mock_service

        transport = ASGITransport(app=app_as_admin)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/ui/login",
                data={"username": "admin", "password": "wrong"},
            )
            assert response.status_code == 401

    async def test_post_logout_clears_cookie_and_redirects(self, client_admin: AsyncClient):
        """POST /ui/logout clears cookie and redirects to login."""
        response = await client_admin.post("/ui/logout", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers.get("location") == "/ui/login"
        set_cookie = response.headers.get("set-cookie", "")
        assert "maestro_session" in set_cookie

    async def test_unauthenticated_access_to_ui_redirects_to_login(
        self, client_unauthenticated: AsyncClient
    ):
        """Accessing /ui/ without auth redirects to /ui/login."""
        response = await client_unauthenticated.get(
            "/ui/", follow_redirects=False, headers={"Accept": "text/html"}
        )
        assert response.status_code == 302
        assert "/ui/login" in response.headers.get("location", "")

    async def test_unauthenticated_api_request_returns_401_json(
        self, client_unauthenticated: AsyncClient
    ):
        """API requests without auth return 401 JSON instead of redirect."""
        response = await client_unauthenticated.get(
            "/ui/", follow_redirects=False, headers={"Accept": "application/json"}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Not authenticated"}


# ===========================================================================
# B) Authorization enforcement
# ===========================================================================


class TestAuthorizationEnforcement:
    """Test that group-based access control works correctly."""

    async def test_admin_can_access_users_page(self, client_admin: AsyncClient):
        """Administrators can access /ui/users (200)."""
        with patch("maestro.api.routes.auth.GroupRepository"):
            mock_repo = AsyncMock()
            mock_repo.get_all_groups = AsyncMock(return_value=[])

            from maestro.main import app
            from maestro.repositories.auth import GroupRepository
            app.dependency_overrides[GroupRepository] = lambda: mock_repo

            response = await client_admin.get("/ui/users")
            assert response.status_code == 200

            # Cleanup
            app.dependency_overrides.pop(GroupRepository, None)

    async def test_non_admin_gets_403_on_users_page(self, client_viewer: AsyncClient):
        """Non-admin users get 403 when accessing /ui/users."""
        response = await client_viewer.get("/ui/users")
        assert response.status_code == 403

    async def test_viewer_cannot_post_to_execute_endpoint(self, client_viewer: AsyncClient):
        """Viewers cannot POST to action endpoints (e.g., /ui/execute/{name} returns 403)."""
        response = await client_viewer.post("/ui/execute/test-release")
        assert response.status_code == 403

    async def test_viewer_cannot_post_to_retry_step(self, client_viewer: AsyncClient):
        """Viewers cannot retry steps."""
        response = await client_viewer.post("/ui/retry-step/1")
        assert response.status_code == 403

    async def test_viewer_cannot_approve_execution(self, client_viewer: AsyncClient):
        """Viewers cannot approve executions."""
        response = await client_viewer.post(
            "/ui/execution/1/approve",
            json={"status": "Sucesso"},
        )
        assert response.status_code == 403

    async def test_operator_can_access_execute_endpoint(self, client_operator: AsyncClient):
        """Operators can access release action endpoints."""
        with patch("maestro.services.orchestrator.OrchestratorService"):
            mock_service = AsyncMock()
            mock_service.execute_release = AsyncMock(return_value=1)

            from maestro.main import app
            from maestro.services.orchestrator import OrchestratorService
            app.dependency_overrides[OrchestratorService] = lambda: mock_service

            response = await client_operator.post("/ui/execute/test-release")
            assert response.status_code == 200

            app.dependency_overrides.pop(OrchestratorService, None)

    async def test_operator_gets_403_on_settings(self, client_operator: AsyncClient):
        """Operators get 403 on settings page (admin only)."""
        response = await client_operator.get("/ui/settings")
        assert response.status_code == 403

    async def test_operator_gets_403_on_users(self, client_operator: AsyncClient):
        """Operators get 403 on user management page (admin only)."""
        response = await client_operator.get("/ui/users")
        assert response.status_code == 403

    async def test_approver_cannot_execute_release(self, client_approver: AsyncClient):
        """Approvers cannot execute releases (requires can_operate)."""
        response = await client_approver.post("/ui/execute/test-release")
        assert response.status_code == 403

    async def test_approver_can_approve_step(self, client_approver: AsyncClient):
        """Approvers can approve individual steps."""
        with patch("maestro.services.orchestrator.OrchestratorService"):
            mock_service = AsyncMock()
            mock_step = MagicMock()
            mock_step.release_execution_id = 1
            mock_step.id = 1
            mock_step.stage_id = "stage-1"
            mock_step.step_id = "step-1"
            mock_step.message = "Approved"
            mock_service.approve_step = AsyncMock(return_value=mock_step)

            from maestro.main import app
            from maestro.repositories.execution import ExecutionRepository
            from maestro.services.orchestrator import OrchestratorService

            mock_exec_repo = AsyncMock()
            mock_exec_repo.add_action_log = AsyncMock()
            app.dependency_overrides[OrchestratorService] = lambda: mock_service
            app.dependency_overrides[ExecutionRepository] = lambda: mock_exec_repo

            response = await client_approver.post("/ui/step/1/approve")
            assert response.status_code == 200

            app.dependency_overrides.pop(OrchestratorService, None)
            app.dependency_overrides.pop(ExecutionRepository, None)

    async def test_unauthenticated_requests_redirect_to_login(
        self, client_unauthenticated: AsyncClient
    ):
        """Unauthenticated requests to protected UI routes get redirected (302)."""
        routes_to_check = [
            "/ui/",
            "/ui/releases",
            "/ui/settings",
            "/ui/users",
            "/ui/change-password",
        ]
        for route in routes_to_check:
            response = await client_unauthenticated.get(
                route, follow_redirects=False, headers={"Accept": "text/html"}
            )
            assert response.status_code == 302, f"Expected 302 for {route}, got {response.status_code}"
            assert "/ui/login" in response.headers.get("location", ""), (
                f"Expected redirect to /ui/login for {route}"
            )

    async def test_health_endpoint_works_without_auth(self, client_unauthenticated: AsyncClient):
        """/health endpoint works without auth."""
        response = await client_unauthenticated.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    async def test_callback_endpoints_work_without_auth(self, client_unauthenticated: AsyncClient):
        """/callback/* endpoints work without auth (they use their own validation)."""
        # POST /callback/release with invalid payload should return 422 (validation)
        # not 302 (redirect to login), proving auth is not enforced
        response = await client_unauthenticated.post(
            "/callback/release",
            json={},
        )
        # 422 = Unprocessable Entity (pydantic validation), not 302 (auth redirect)
        assert response.status_code == 422


# ===========================================================================
# C) User management routes
# ===========================================================================


class TestUserManagementRoutes:
    """Test user management endpoints (admin only)."""

    async def test_create_user_admin_only(self, client_admin: AsyncClient):
        """POST /ui/users creates user (admin only)."""
        mock_auth_service = AsyncMock()
        mock_auth_service.create_user = AsyncMock(return_value=_make_mock_user(5, "newuser"))

        mock_user_repo = AsyncMock()
        mock_user_repo.get_user_by_username = AsyncMock(return_value=None)
        mock_user_repo.get_all_users = AsyncMock(return_value=[ADMIN_USER])
        mock_user_repo.get_user_groups = AsyncMock(return_value=[])

        mock_group_repo = AsyncMock()
        mock_group_repo.get_all_groups = AsyncMock(return_value=[])

        from maestro.main import app
        from maestro.repositories.auth import GroupRepository, UserRepository
        from maestro.services.auth import AuthService

        app.dependency_overrides[AuthService] = lambda: mock_auth_service
        app.dependency_overrides[UserRepository] = lambda: mock_user_repo
        app.dependency_overrides[GroupRepository] = lambda: mock_group_repo

        response = await client_admin.post(
            "/ui/users",
            data={"username": "newuser", "password": "pass123", "full_name": "New User"},
        )
        assert response.status_code == 200
        mock_auth_service.create_user.assert_called_once()

        app.dependency_overrides.pop(AuthService, None)
        app.dependency_overrides.pop(UserRepository, None)
        app.dependency_overrides.pop(GroupRepository, None)

    async def test_create_user_non_admin_gets_403(self, client_viewer: AsyncClient):
        """Non-admin users cannot create users."""
        response = await client_viewer.post(
            "/ui/users",
            data={"username": "newuser", "password": "pass123"},
        )
        assert response.status_code == 403

    async def test_update_user_groups_admin_only(self, client_admin: AsyncClient):
        """POST /ui/users/{id}/groups updates groups (admin only)."""
        mock_user_repo = AsyncMock()
        mock_user_repo.get_user_by_id = AsyncMock(return_value=ADMIN_USER)
        mock_user_repo.set_user_groups = AsyncMock()
        mock_user_repo.get_all_users = AsyncMock(return_value=[ADMIN_USER])
        mock_user_repo.get_user_groups = AsyncMock(return_value=[])

        mock_group_repo = AsyncMock()
        mock_group_repo.get_all_groups = AsyncMock(return_value=[])

        from maestro.main import app
        from maestro.repositories.auth import GroupRepository, UserRepository

        app.dependency_overrides[UserRepository] = lambda: mock_user_repo
        app.dependency_overrides[GroupRepository] = lambda: mock_group_repo

        response = await client_admin.post(
            "/ui/users/1/groups",
            data={"group_ids": ["1", "2"]},
        )
        assert response.status_code == 200
        mock_user_repo.set_user_groups.assert_called_once()

        app.dependency_overrides.pop(UserRepository, None)
        app.dependency_overrides.pop(GroupRepository, None)

    async def test_update_user_groups_non_admin_gets_403(self, client_viewer: AsyncClient):
        """Non-admin users cannot update user groups."""
        response = await client_viewer.post(
            "/ui/users/1/groups",
            data={"group_ids": ["1"]},
        )
        assert response.status_code == 403

    async def test_toggle_user_active_admin_only(self, client_admin: AsyncClient):
        """POST /ui/users/{id}/toggle-active toggles status (admin only)."""
        mock_user = _make_mock_user(2, "testuser")
        mock_user.is_active = True

        mock_user_repo = AsyncMock()
        mock_user_repo.get_user_by_id = AsyncMock(return_value=mock_user)
        mock_user_repo.update_user = AsyncMock()
        mock_user_repo.get_all_users = AsyncMock(return_value=[mock_user])
        mock_user_repo.get_user_groups = AsyncMock(return_value=[])

        mock_group_repo = AsyncMock()
        mock_group_repo.get_all_groups = AsyncMock(return_value=[])

        from maestro.main import app
        from maestro.repositories.auth import GroupRepository, UserRepository

        app.dependency_overrides[UserRepository] = lambda: mock_user_repo
        app.dependency_overrides[GroupRepository] = lambda: mock_group_repo

        response = await client_admin.post("/ui/users/2/toggle-active")
        assert response.status_code == 200
        mock_user_repo.update_user.assert_called_once()

        app.dependency_overrides.pop(UserRepository, None)
        app.dependency_overrides.pop(GroupRepository, None)

    async def test_toggle_user_active_non_admin_gets_403(self, client_viewer: AsyncClient):
        """Non-admin users cannot toggle user active status."""
        response = await client_viewer.post("/ui/users/2/toggle-active")
        assert response.status_code == 403

    async def test_get_change_password_page_authenticated(self, client_admin: AsyncClient):
        """GET /ui/change-password returns form (any authenticated user)."""
        response = await client_admin.get("/ui/change-password")
        assert response.status_code == 200

    async def test_get_change_password_page_viewer(self, client_viewer: AsyncClient):
        """Viewers can also access the change password page (any authenticated user)."""
        response = await client_viewer.get("/ui/change-password")
        assert response.status_code == 200

    async def test_post_change_password_success(self, client_admin: AsyncClient):
        """POST /ui/change-password changes password."""
        mock_auth_service = AsyncMock()
        mock_auth_service.authenticate = AsyncMock(return_value=ADMIN_USER)
        mock_auth_service.update_password = AsyncMock()

        from maestro.main import app
        from maestro.services.auth import AuthService

        app.dependency_overrides[AuthService] = lambda: mock_auth_service

        response = await client_admin.post(
            "/ui/change-password",
            data={
                "current_password": "oldpass",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert response.status_code == 200
        mock_auth_service.update_password.assert_called_once()

        app.dependency_overrides.pop(AuthService, None)

    async def test_post_change_password_mismatch(self, client_admin: AsyncClient):
        """POST /ui/change-password with mismatched passwords returns error."""
        mock_auth_service = AsyncMock()

        from maestro.main import app
        from maestro.services.auth import AuthService

        app.dependency_overrides[AuthService] = lambda: mock_auth_service

        response = await client_admin.post(
            "/ui/change-password",
            data={
                "current_password": "oldpass",
                "new_password": "newpass123",
                "confirm_password": "differentpass",
            },
        )
        assert response.status_code == 200
        # Should contain error message about passwords not matching
        assert "nao conferem" in response.text.lower() or "conferem" in response.text

        app.dependency_overrides.pop(AuthService, None)

    async def test_post_change_password_wrong_current(self, client_admin: AsyncClient):
        """POST /ui/change-password with wrong current password returns error."""
        mock_auth_service = AsyncMock()
        mock_auth_service.authenticate = AsyncMock(return_value=None)

        from maestro.main import app
        from maestro.services.auth import AuthService

        app.dependency_overrides[AuthService] = lambda: mock_auth_service

        response = await client_admin.post(
            "/ui/change-password",
            data={
                "current_password": "wrongpass",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert response.status_code == 200
        # Should contain error about incorrect current password
        assert "incorreta" in response.text.lower() or "atual" in response.text.lower()

        app.dependency_overrides.pop(AuthService, None)

    async def test_post_change_password_too_short(self, client_admin: AsyncClient):
        """POST /ui/change-password with short new password returns error."""
        mock_auth_service = AsyncMock()

        from maestro.main import app
        from maestro.services.auth import AuthService

        app.dependency_overrides[AuthService] = lambda: mock_auth_service

        response = await client_admin.post(
            "/ui/change-password",
            data={
                "current_password": "oldpass",
                "new_password": "ab",
                "confirm_password": "ab",
            },
        )
        assert response.status_code == 200
        # Should contain error about minimum length
        assert "4 caracteres" in response.text or "pelo menos" in response.text.lower()

        app.dependency_overrides.pop(AuthService, None)

    async def test_change_password_unauthenticated_redirects(
        self, client_unauthenticated: AsyncClient
    ):
        """Unauthenticated access to change-password redirects to login."""
        response = await client_unauthenticated.get(
            "/ui/change-password", follow_redirects=False, headers={"Accept": "text/html"}
        )
        assert response.status_code == 302
        assert "/ui/login" in response.headers.get("location", "")
