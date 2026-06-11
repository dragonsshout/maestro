"""Tests for authentication and authorization feature."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from maestro.database.models import Base, Group, User, UserGroupAssociation
from maestro.repositories.auth import GroupRepository, UserRepository
from maestro.services.auth import AuthService, pwd_context


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database session for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def seeded_session(db_session: AsyncSession):
    """Create session with seed data (groups + admin user)."""
    groups = [
        Group(id=1, name="Administrators", description="Full control, can do everything"),
        Group(id=2, name="Viewers", description="View only"),
        Group(id=3, name="Approver", description="Viewers + can Approve/Deny releases"),
        Group(id=4, name="Operators", description="Full control on releases page"),
        Group(id=5, name="Developers", description="Viewers for now"),
    ]
    for g in groups:
        db_session.add(g)
    await db_session.flush()

    admin_hash = pwd_context.hash("chang3m3")
    admin_user = User(id=1, username="admin", password_hash=admin_hash, full_name="Administrator")
    db_session.add(admin_user)
    await db_session.flush()

    assoc = UserGroupAssociation(user_id=1, group_id=1)
    db_session.add(assoc)
    await db_session.commit()

    return db_session


class TestUserRepository:
    async def test_get_user_by_username(self, seeded_session):
        repo = UserRepository(db=seeded_session)
        user = await repo.get_user_by_username("admin")
        assert user is not None
        assert user.username == "admin"

    async def test_get_user_by_username_not_found(self, seeded_session):
        repo = UserRepository(db=seeded_session)
        user = await repo.get_user_by_username("nonexistent")
        assert user is None

    async def test_get_user_by_id(self, seeded_session):
        repo = UserRepository(db=seeded_session)
        user = await repo.get_user_by_id(1)
        assert user is not None
        assert user.username == "admin"

    async def test_create_user(self, seeded_session):
        repo = UserRepository(db=seeded_session)
        user = await repo.create_user("newuser", pwd_context.hash("pass123"), "New User")
        assert user.id is not None
        assert user.username == "newuser"
        assert user.full_name == "New User"

    async def test_get_all_users(self, seeded_session):
        repo = UserRepository(db=seeded_session)
        users = await repo.get_all_users()
        assert len(users) >= 1
        assert any(u.username == "admin" for u in users)

    async def test_get_user_groups(self, seeded_session):
        repo = UserRepository(db=seeded_session)
        groups = await repo.get_user_groups(1)
        assert len(groups) == 1
        assert groups[0].name == "Administrators"

    async def test_set_user_groups(self, seeded_session):
        repo = UserRepository(db=seeded_session)
        await repo.set_user_groups(1, [2, 3])
        groups = await repo.get_user_groups(1)
        group_names = [g.name for g in groups]
        assert "Viewers" in group_names
        assert "Approver" in group_names
        assert "Administrators" not in group_names


class TestGroupRepository:
    async def test_get_all_groups(self, seeded_session):
        repo = GroupRepository(db=seeded_session)
        groups = await repo.get_all_groups()
        assert len(groups) == 5

    async def test_get_group_by_name(self, seeded_session):
        repo = GroupRepository(db=seeded_session)
        group = await repo.get_group_by_name("Administrators")
        assert group is not None
        assert group.id == 1

    async def test_get_group_by_name_not_found(self, seeded_session):
        repo = GroupRepository(db=seeded_session)
        group = await repo.get_group_by_name("nonexistent")
        assert group is None


class TestAuthService:
    async def test_authenticate_success(self, seeded_session):
        user_repo = UserRepository(db=seeded_session)
        group_repo = GroupRepository(db=seeded_session)
        service = AuthService(user_repo=user_repo, group_repo=group_repo)

        user = await service.authenticate("admin", "chang3m3")
        assert user is not None
        assert user.username == "admin"

    async def test_authenticate_wrong_password(self, seeded_session):
        user_repo = UserRepository(db=seeded_session)
        group_repo = GroupRepository(db=seeded_session)
        service = AuthService(user_repo=user_repo, group_repo=group_repo)

        user = await service.authenticate("admin", "wrongpassword")
        assert user is None

    async def test_authenticate_nonexistent_user(self, seeded_session):
        user_repo = UserRepository(db=seeded_session)
        group_repo = GroupRepository(db=seeded_session)
        service = AuthService(user_repo=user_repo, group_repo=group_repo)

        user = await service.authenticate("nobody", "anything")
        assert user is None

    async def test_create_user(self, seeded_session):
        user_repo = UserRepository(db=seeded_session)
        group_repo = GroupRepository(db=seeded_session)
        service = AuthService(user_repo=user_repo, group_repo=group_repo)

        user = await service.create_user("developer", "devpass", "Dev User", [5])
        assert user.username == "developer"

        groups = await user_repo.get_user_groups(user.id)
        assert len(groups) == 1
        assert groups[0].name == "Developers"

    async def test_update_password(self, seeded_session):
        user_repo = UserRepository(db=seeded_session)
        group_repo = GroupRepository(db=seeded_session)
        service = AuthService(user_repo=user_repo, group_repo=group_repo)

        await service.update_password(1, "newpassword123")
        user = await service.authenticate("admin", "newpassword123")
        assert user is not None

    async def test_session_token_roundtrip(self, seeded_session):
        user_repo = UserRepository(db=seeded_session)
        group_repo = GroupRepository(db=seeded_session)
        service = AuthService(user_repo=user_repo, group_repo=group_repo)

        user = await service.authenticate("admin", "chang3m3")
        assert user is not None

        token = service.create_session_token(user)
        assert token is not None

        payload = AuthService.decode_session_token(token)
        assert payload is not None
        assert payload["sub"] == str(user.id)
        assert payload["username"] == "admin"

    async def test_decode_invalid_token(self, seeded_session):
        payload = AuthService.decode_session_token("invalid.token.here")
        assert payload is None


class TestAuthDependencies:
    async def test_get_current_user_no_cookie_raises(self, seeded_session):
        """Request without cookie should raise NotAuthenticatedException."""
        from unittest.mock import MagicMock

        from maestro.auth.dependencies import NotAuthenticatedException, get_current_user

        request = MagicMock()
        request.cookies = {}
        request.headers = {"accept": "application/json"}

        with pytest.raises(NotAuthenticatedException):
            await get_current_user(request, seeded_session)

    async def test_get_current_user_no_cookie_ui_raises(self, seeded_session):
        """UI request without cookie should also raise NotAuthenticatedException."""
        from unittest.mock import MagicMock

        from maestro.auth.dependencies import NotAuthenticatedException, get_current_user

        request = MagicMock()
        request.cookies = {}
        request.headers = {"accept": "text/html"}

        with pytest.raises(NotAuthenticatedException):
            await get_current_user(request, seeded_session)

    async def test_get_current_user_valid_cookie(self, seeded_session):
        """Valid JWT cookie should return user."""
        from unittest.mock import MagicMock

        from maestro.auth.dependencies import get_current_user
        from maestro.services.auth import AuthService

        user_repo = UserRepository(db=seeded_session)
        group_repo = GroupRepository(db=seeded_session)
        service = AuthService(user_repo=user_repo, group_repo=group_repo)

        user = await service.authenticate("admin", "chang3m3")
        token = service.create_session_token(user)

        request = MagicMock()
        request.cookies = {"maestro_session": token}
        request.headers = {"accept": "application/json"}

        result = await get_current_user(request, seeded_session)
        assert result.username == "admin"
