"""
Schémas Pydantic pour les requêtes et réponses de l'API.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class ScrapeRequest(BaseModel):
    url: HttpUrl
    limit: int = Field(default=10, ge=1, le=100, description="Nombre de posts à récupérer")


class ScrapeQueued(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.queued


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str]
