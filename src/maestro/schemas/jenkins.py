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


class JenkinsBuildInfoSchema(BaseModel):
    """Informações relevantes de um build do Jenkins."""
    number: int
    result: Optional[str] = None  # SUCCESS, FAILURE, ABORTED, null (still running)
    building: bool = True
