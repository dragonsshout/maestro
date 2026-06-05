import asyncio
from maestro.database.session import AsyncSessionLocal
from maestro.repositories.schedule import ScheduleRepository
from maestro.database.models import ScheduledRelease
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ScheduledRelease))
        schedules = list(result.scalars().all())
        for s in schedules:
            print(f"ID: {s.id}, name: {s.name}, status: {s.status}, error: {s.error_message}, scheduled_at: {s.scheduled_at}")

asyncio.run(main())
