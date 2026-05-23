from typing import List, Literal, Optional
from pydantic import BaseModel

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
    name: str
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
