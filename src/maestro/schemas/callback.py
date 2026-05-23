from typing import Optional
from pydantic import BaseModel
from typing import Literal

class ReleaseCallbackSchema(BaseModel):
    release_process_id: str
    stage_id: str
    step_id: str
    message: Optional[str] = None
    status: Literal["success", "error", "failure"]
