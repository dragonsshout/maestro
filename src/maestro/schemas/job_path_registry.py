from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class JobPathRegistryResponse(BaseModel):
    """Schema de resposta para um registro do job_path_registry."""

    model_config = {"from_attributes": True}

    id: int
    repository: str
    environment: str
    domain: Optional[str] = None
    type: str = "jenkins"
    path: str
    created_at: datetime
    updated_at: datetime


class JobPathRegistryDiscoveryResponse(BaseModel):
    """Schema de resposta do discovery de jobs no Jenkins."""

    total_discovered: int
    total_upserted: int
    message: str
