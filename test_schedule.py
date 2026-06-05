import asyncio
from datetime import datetime, timezone, timedelta
from maestro.database.session import AsyncSessionLocal
from maestro.repositories.schedule import ScheduleRepository
from maestro.database.models import ScheduledRelease

async def main():
    async with AsyncSessionLocal() as session:
        repo = ScheduleRepository(session)
        # cancel all existing
        schedules = await repo.get_all_schedules()
        for s in schedules:
            if s.status == 'pending':
                s.status = 'cancelled'
        
        # create a new schedule 2 seconds from now
        sched_time = datetime.now(timezone.utc) + timedelta(seconds=2)
        sched = ScheduledRelease(
            orchestrator_descriptor_id=1,
            name="release-teste",
            scheduled_at=sched_time,
            status="pending"
        )
        session.add(sched)
        await session.commit()
        await session.refresh(sched)
        print(f"Created schedule {sched.id} for {sched.scheduled_at}")

        await asyncio.sleep(35) # wait for the checker to pick it up

        await session.refresh(sched)
        print(f"After wait: Schedule {sched.id} status={sched.status}, error={sched.error_message}")

asyncio.run(main())
