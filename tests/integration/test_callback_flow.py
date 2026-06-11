"""
Integration tests for Callback routes.

Tests the callback flow with a real database:
- Receive Jenkins callback → update step status in DB
- Receive event callback → persist log event in DB
- Error scenarios (step not found, missing input_id)

All tests persist data in a real PostgreSQL and mock only external HTTP calls.
"""
import pytest

from maestro.database.models import OrchestratorDescriptor, ReleaseExecution, ReleaseStepExecution
from maestro.schemas.enums import ExecutionStatus
from tests.integration.conftest import SAMPLE_RELEASE_YAML

pytestmark = pytest.mark.integration


@pytest.fixture
async def execution_with_step(db_engine):
    """
    Creates a descriptor, execution, and step in the DB for callback testing.
    Returns (execution, step) tuple.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        # Create descriptor
        descriptor = OrchestratorDescriptor(name="callback-test", yaml=SAMPLE_RELEASE_YAML)
        session.add(descriptor)
        await session.flush()

        # Create execution
        execution = ReleaseExecution(
            name="callback-test",
            status=ExecutionStatus.IN_PROGRESS,
            orchestrator_descriptor_id=descriptor.id,
        )
        session.add(execution)
        await session.flush()

        # Create step execution with a correlation ID
        step = ReleaseStepExecution(
            release_execution_id=execution.id,
            stage_id="stage-1",
            step_id="step-1",
            status=ExecutionStatus.IN_PROGRESS,
            job_execution_correlation_id=500,
        )
        session.add(step)
        await session.commit()
        await session.refresh(step)
        await session.refresh(execution)

    return execution, step


# ===========================================================================
# Release Callback
# ===========================================================================

class TestReleaseCallback:
    async def test_callback_success_updates_step(self, client, execution_with_step, db_engine):
        """Callback with status=success updates step in DB."""
        execution, step = execution_with_step

        payload = {
            "job_execution_correlation_id": 500,
            "status": "success",
            "message": "Build completed successfully",
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["job_execution_correlation_id"] == 500
        assert data["status"] == "success"

        # Verify DB was updated
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.future import select

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(ReleaseStepExecution).where(ReleaseStepExecution.id == step.id)
            )
            updated_step = result.scalars().first()
            assert updated_step.status == ExecutionStatus.SUCCESS
            assert updated_step.message == "Build completed successfully"

    async def test_callback_failure_updates_step(self, client, execution_with_step, db_engine):
        """Callback with status=failure updates step in DB."""
        execution, step = execution_with_step

        payload = {
            "job_execution_correlation_id": 500,
            "status": "failure",
            "message": "Build failed: tests not passing",
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 200

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.future import select

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(ReleaseStepExecution).where(ReleaseStepExecution.id == step.id)
            )
            updated_step = result.scalars().first()
            assert updated_step.status == ExecutionStatus.FAILURE

    async def test_callback_waiting_approval_with_input_id(self, client, execution_with_step, db_engine):
        """Callback with status=waiting_approval stores input_id."""
        execution, step = execution_with_step

        payload = {
            "job_execution_correlation_id": 500,
            "status": "waiting_approval",
            "input_id": "approval-input-xyz",
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 200

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.future import select

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(ReleaseStepExecution).where(ReleaseStepExecution.id == step.id)
            )
            updated_step = result.scalars().first()
            assert updated_step.status == ExecutionStatus.WAITING_APPROVAL
            assert updated_step.job_input_id == "approval-input-xyz"

    async def test_callback_waiting_approval_without_input_id_fails(self, client, execution_with_step):
        """Callback with status=waiting_approval but no input_id returns 400."""
        payload = {
            "job_execution_correlation_id": 500,
            "status": "waiting_approval",
            # No input_id
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 400
        assert "input_id" in response.json()["detail"].lower()

    async def test_callback_step_not_found(self, client):
        """Callback with unknown correlation_id returns 404."""
        payload = {
            "job_execution_correlation_id": 99999,
            "status": "success",
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 404

    async def test_callback_invalid_status(self, client):
        """Callback with invalid status returns 422."""
        payload = {
            "job_execution_correlation_id": 500,
            "status": "invalid_status_xyz",
        }
        response = await client.post("/callback/release", json=payload)
        assert response.status_code == 422

    async def test_callback_missing_fields(self, client):
        """Callback without required fields returns 422."""
        response = await client.post("/callback/release", json={})
        assert response.status_code == 422


# ===========================================================================
# Event Callback
# ===========================================================================

class TestEventCallback:
    async def test_event_callback_success(self, client, execution_with_step, db_engine):
        """Event callback persists a StepEvent in DB."""
        execution, step = execution_with_step

        payload = {
            "job_execution_correlation_id": 500,
            "message": "Build #500 started on agent linux-01",
        }
        response = await client.post("/callback/event", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "Evento registrado" in data["message"]

        # Verify event was persisted in DB
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.future import select

        from maestro.database.models import StepEvent

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(StepEvent).where(StepEvent.job_execution_correlation_id == 500)
            )
            events = result.scalars().all()
            assert len(events) >= 1
            assert events[0].message == "Build #500 started on agent linux-01"

    async def test_event_callback_multiple_events(self, client, execution_with_step, db_engine):
        """Multiple events for the same step are stored in order."""
        execution, step = execution_with_step

        messages = [
            "Starting build...",
            "Running unit tests...",
            "Tests passed (42/42)",
            "Deploying to staging...",
        ]

        for msg in messages:
            response = await client.post(
                "/callback/event",
                json={"job_execution_correlation_id": 500, "message": msg},
            )
            assert response.status_code == 200

        # Verify all events persisted
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.future import select

        from maestro.database.models import StepEvent

        sf = async_sessionmaker(bind=db_engine, expire_on_commit=False)
        async with sf() as session:
            result = await session.execute(
                select(StepEvent)
                .where(StepEvent.job_execution_correlation_id == 500)
                .order_by(StepEvent.created_at.asc())
            )
            events = result.scalars().all()
            assert len(events) == 4
            assert events[0].message == "Starting build..."
            assert events[3].message == "Deploying to staging..."

    async def test_event_callback_step_not_found(self, client):
        """Event for unknown correlation_id returns 404."""
        payload = {
            "job_execution_correlation_id": 88888,
            "message": "This should fail",
        }
        response = await client.post("/callback/event", json=payload)
        assert response.status_code == 404

    async def test_event_callback_missing_message(self, client):
        """Event without message returns 422."""
        payload = {"job_execution_correlation_id": 500}
        response = await client.post("/callback/event", json=payload)
        assert response.status_code == 422
