from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from maestro.schemas.enums import ScheduledReleaseStatus


class ScheduleReleaseRequest(BaseModel):
    name: str
    scheduled_at: datetime


class ScheduleReleaseResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    scheduled_at: datetime
    status: ScheduledReleaseStatus
    release_execution_id: Optional[int] = None
    created_at: datetime
    created_by: Optional[str] = None
    error_message: Optional[str] = None
