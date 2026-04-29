"""
Endpoints de santé de l'API et des sources de données.

GET  /health                     → état API + Redis (rapide)
POST /v1/health/check?limit=N    → lance un health check complet en arrière-plan
GET  /v1/health/check/{job_id}   → statut du job de health check
"""

from fastapi import APIRouter, Depends, Query, Request
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.job import JobStatus as RQStatus

from api.config import get_settings
from api.deps import get_redis, require_api_key
from api.schemas import HealthResponse, JobStatus, JobStatusResponse, ScrapeQueued

router = APIRouter(tags=["ops"])
settings = get_settings()

_QUEUE_NAME = "scrapes"

_RQ_STATUS_MAP = {
    RQStatus.QUEUED: JobStatus.queued,
    RQStatus.STARTED: JobStatus.running,
    RQStatus.FINISHED: JobStatus.done,
    RQStatus.FAILED: JobStatus.failed,
    RQStatus.STOPPED: JobStatus.failed,
    RQStatus.CANCELED: JobStatus.failed,
    RQStatus.DEFERRED: JobStatus.queued,
    RQStatus.SCHEDULED: JobStatus.queued,
}


# ── GET /health ───────────────────────────────────────────────────────
@router.get("/health", response_model=HealthResponse, summary="Health check API + Redis")
async def health(request: Request, redis=Depends(get_redis)) -> HealthResponse:
    checks: dict[str, str] = {"api": "ok"}
    try:
        redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthResponse(status=status, checks=checks)


# ── POST /v1/health/check ─────────────────────────────────────────────
@router.post(
    "/v1/health/check",
    response_model=ScrapeQueued,
    status_code=202,
    summary="Lancer un health check complet des sources de scraping",
    description=(
        "Équivalent de `python main.py --health <limit>`. "
        "Lance health + benchmark sur toutes les plateformes en arrière-plan. "
        "Peut prendre 30 à 120 secondes. Récupérer le résultat via `/v1/health/check/{job_id}/result`."
    ),
)
async def trigger_health_check(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50, description="Posts scrappés par plateforme pour le benchmark"),
    redis=Depends(get_redis),
    _: str = Depends(require_api_key),
) -> ScrapeQueued:
    from worker.tasks import run_health_check_job

    q = Queue(_QUEUE_NAME, connection=redis)
    job = q.enqueue(
        run_health_check_job,
        limit,
        job_timeout=300,
        result_ttl=settings.job_result_ttl,
        failure_ttl=settings.job_result_ttl,
    )
    return ScrapeQueued(job_id=job.id, status=JobStatus.queued)


# ── GET /v1/health/check/{job_id} ─────────────────────────────────────
@router.get(
    "/v1/health/check/{job_id}",
    summary="Statut d'un job de health check",
)
async def get_health_check_status(
    job_id: str,
    request: Request,
    redis=Depends(get_redis),
    _: str = Depends(require_api_key),
):
    try:
        job = Job.fetch(job_id, connection=redis)
    except NoSuchJobError:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")

    rq_status = job.get_status()
    api_status = _RQ_STATUS_MAP.get(rq_status, JobStatus.failed)

    if api_status == JobStatus.done:
        return {"job_id": job_id, "status": api_status, "result": job.result}

    error = str(job.exc_info).strip() if api_status == JobStatus.failed and job.exc_info else None
    return {"job_id": job_id, "status": api_status, "result": None, "error": error}
