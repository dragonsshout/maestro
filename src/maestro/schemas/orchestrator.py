from typing import List, Literal, Optional
from pydantic import BaseModel
from maestro.schemas.enums import ExecutionStatus
from datetime import datetime

class JobSchema(BaseModel):
    type: str
    path: str

class StepSchema(BaseModel):
    id: str
    repository: str
    release: str
    critical: Optional[bool] = False
    requires_approval: Optional[bool] = False
    job: JobSchema

class StageSchema(BaseModel):
    id: str
    steps: List[StepSchema]

class StrategySchema(BaseModel):
    type: Literal["all-or-nothing", "fire-and-forget"]

class ReleaseSpecSchema(BaseModel):
    strategy: Optional[StrategySchema] = None
    stages: List[StageSchema]

class MetadataSchema(BaseModel):
    name: str
    author: str
    description: Optional[str] = None

class ReleaseConfigSchema(BaseModel):
    apiVersion: str
    kind: Literal["Release"]
    metadata: MetadataSchema
    spec: ReleaseSpecSchema

class ExecuteReleaseRequest(BaseModel):
    name: str

class ApproveReleaseRequest(BaseModel):
    status: str = "Sucesso"

class StageStatusResponse(BaseModel):
    stage_id: str
    status: ExecutionStatus

class ReleaseStatusResponse(BaseModel):
    id: int
    name: str
    status: ExecutionStatus
    message: Optional[str] = None
    created_at: datetime
    stages: List[StageStatusResponse]

    class Config:
        from_attributes = True

class ReleaseStepResponse(BaseModel):
    id: int
    stage_id: str
    step_id: str
    status: ExecutionStatus
    message: Optional[str] = None
    job_execution_correlation_id: Optional[int] = None
    job_input_id: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True

class ReleaseDetailsResponse(ReleaseStatusResponse):
    steps: List[ReleaseStepResponse]
