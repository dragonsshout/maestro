from typing import Optional

from pydantic import BaseModel

from maestro.schemas.enums import ExecutionStatus


class ReleaseCallbackSchema(BaseModel):
    job_execution_correlation_id: int
    message: Optional[str] = None
    status: ExecutionStatus
    input_id: Optional[str] = None


class StepEventSchema(BaseModel):
    job_execution_correlation_id: int
    message: str
