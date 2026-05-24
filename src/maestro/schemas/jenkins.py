from typing import Optional
from pydantic import BaseModel

class JenkinsExecutableSchema(BaseModel):
    number: int

class JenkinsQueueItemSchema(BaseModel):
    executable: Optional[JenkinsExecutableSchema] = None
