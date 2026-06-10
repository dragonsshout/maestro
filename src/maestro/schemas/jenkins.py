from typing import List, Optional

from pydantic import BaseModel


class JenkinsExecutableSchema(BaseModel):
    number: int


class JenkinsQueueItemSchema(BaseModel):
    executable: Optional[JenkinsExecutableSchema] = None


class JenkinsInputParameterSchema(BaseModel):
    name: str
    value: Optional[str] = None


class JenkinsPendingInputSchema(BaseModel):
    id: str
    inputs: List[JenkinsInputParameterSchema] = []
