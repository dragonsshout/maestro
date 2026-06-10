from typing import Optional

from pydantic import BaseModel


class PullRequestSchema(BaseModel):
    number: int
    state: str
    title: str


class PullRequestDetailSchema(PullRequestSchema):
    mergeable_state: Optional[str] = None
    mergeable: Optional[bool] = None
