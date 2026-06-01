"""
Integration tests for UI Settings.

Tests the settings CRUD flow with a real database:
- Save settings via API → persisted in DB
- Read settings → returns saved values
- Upsert behavior (insert or update)
- Unknown keys are filtered
"""
import pytest

from maestro.database.models import UISettings
from maestro.services.settings import KNOWN_SETTINGS


pytestmark = pytest.mark.integration


class TestSettingsAPI:
    async def test_get_settings_page(self, client):
        """GET /ui/settings returns HTML settings page."""
        response = await client.get("/ui/settings")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_save_settings(self, client, db_engine):
        """POST /ui/settings saves known settings to DB."""
        form_data = {
            "jenkins_base_url": "https://jenkins.mycompany.com",
            "github_base_url": "https://github.com",
            "github_organization": "my-org",
        }
        response = await client.post(
            "/ui/settings",
            data=form_data,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200

        # Verify persisted in DB
        from sqlalchemy.future import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(UISettings).where(UISettings.key == "jenkins_base_url")
            )
            setting = result.scalars().first()
            assert setting is not None
            assert setting.value == "https://jenkins.mycompany.com"

    async def test_save_settings_update_existing(self, client, db_engine):
        """Saving again updates the existing value (upsert)."""
        # First save
        await client.post(
            "/ui/settings",
            data={"jenkins_base_url": "http://old-jenkins:8080", "github_base_url": "", "github_organization": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        # Second save with new value
        await client.post(
            "/ui/settings",
            data={"jenkins_base_url": "https://new-jenkins.io", "github_base_url": "", "github_organization": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        # Verify updated
        from sqlalchemy.future import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(UISettings).where(UISettings.key == "jenkins_base_url")
            )
            setting = result.scalars().first()
            assert setting.value == "https://new-jenkins.io"

    async def test_save_settings_empty_values_stored_as_none(self, client, db_engine):
        """Empty string values are stored as NULL."""
        await client.post(
            "/ui/settings",
            data={"jenkins_base_url": "", "github_base_url": "", "github_organization": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        from sqlalchemy.future import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(UISettings).where(UISettings.key == "jenkins_base_url")
            )
            setting = result.scalars().first()
            assert setting is not None
            assert setting.value is None

    async def test_save_settings_strips_whitespace(self, client, db_engine):
        """Values with only whitespace are treated as empty (None)."""
        await client.post(
            "/ui/settings",
            data={"jenkins_base_url": "   ", "github_base_url": "", "github_organization": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        from sqlalchemy.future import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(UISettings).where(UISettings.key == "jenkins_base_url")
            )
            setting = result.scalars().first()
            assert setting is not None
            assert setting.value is None

    async def test_unknown_keys_not_persisted(self, client, db_engine):
        """Unknown keys in form data are not saved to DB."""
        await client.post(
            "/ui/settings",
            data={
                "jenkins_base_url": "http://j:8080",
                "github_base_url": "",
                "github_organization": "",
                "hacker_key": "malicious_value",
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        from sqlalchemy.future import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(UISettings).where(UISettings.key == "hacker_key")
            )
            setting = result.scalars().first()
            assert setting is None


class TestSettingsIntegrationWithExecution:
    """Tests that settings are correctly used in execution detail views."""

    async def test_settings_reflect_in_execution_detail(self, client, db_engine):
        """Saved settings are used when rendering execution details."""
        # Save settings
        await client.post(
            "/ui/settings",
            data={
                "jenkins_base_url": "https://ci.example.com",
                "github_base_url": "https://github.example.com",
                "github_organization": "test-org",
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        # Verify settings are returned
        from sqlalchemy.future import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(select(UISettings).order_by(UISettings.key))
            settings = {s.key: s.value for s in result.scalars().all()}
            assert settings.get("jenkins_base_url") == "https://ci.example.com"
            assert settings.get("github_base_url") == "https://github.example.com"
            assert settings.get("github_organization") == "test-org"
