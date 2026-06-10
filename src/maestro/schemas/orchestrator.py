from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel

from maestro.schemas.enums import ExecutionStatus


class JobSchema(BaseModel):
    type: str = "jenkins"
    path: Optional[str] = None


class StepSchema(BaseModel):
    id: str
    repository: str
    release: str
    critical: Optional[bool] = False
    requires_approval: Optional[bool] = False
    timeout_minutes: Optional[int] = None
    job: Optional[JobSchema] = None


class StageSchema(BaseModel):
    id: str
    steps: List[StepSchema]


class StrategySchema(BaseModel):
    type: Literal["all-or-nothing", "fire-and-forget"]


class ReleaseSpecSchema(BaseModel):
    strategy: Optional[StrategySchema] = None
    environment: Optional[str] = "PRD"
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
    model_config = {"from_attributes": True}

    id: int
    name: str
    status: ExecutionStatus
    message: Optional[str] = None
    created_at: datetime
    stages: List[StageStatusResponse]


class ReleaseStepResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    stage_id: str
    step_id: str
    status: ExecutionStatus
    message: Optional[str] = None
    job_execution_correlation_id: Optional[int] = None
    job_input_id: Optional[str] = None
    updated_at: datetime


class ReleaseDetailsResponse(ReleaseStatusResponse):
    steps: List[ReleaseStepResponse]


class DryRunStepResult(BaseModel):
    step_id: str
    stage_id: str
    repository: str
    branch: str
    branch_exists: bool
    pr_found: bool
    pr_number: Optional[int] = None
    pr_mergeable_state: Optional[str] = None
    pr_is_clean: bool
    jenkins_job_path: str
    jenkins_job_exists: bool


class DryRunStageResult(BaseModel):
    stage_id: str
    steps: List[DryRunStepResult]


class DryRunResponse(BaseModel):
    name: str
    valid: bool
    stages: List[DryRunStageResult]
