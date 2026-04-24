"""
Endpoints de scraping asynchrone via RQ.

POST   /v1/scrapes                  → enqueue job, retourne job_id
GET    /v1/scrapes/{job_id}         → statut du job
GET    /v1/scrapes/{job_id}/result  → résultat ou 404 si non prêt
"""

import hashlib
import json
import uuid

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.job import JobStatus as RQStatus

from api.config import get_settings
from api.deps import get_redis, limiter, require_api_key
from api.schemas import (
    JobResultResponse,
    JobStatus,
    JobStatusResponse,
    ScrapeQueued,
    ScrapeRequest,
)

router = APIRouter(prefix="/v1", tags=["scrapes"])
settings = get_settings()

_QUEUE_NAME = "scrapes"

_RQ_STATUS_MAP: dict[RQStatus, JobStatus] = {
    RQStatus.QUEUED: JobStatus.queued,
    RQStatus.STARTED: JobStatus.running,
    RQStatus.FINISHED: JobStatus.done,
    RQStatus.FAILED: JobStatus.failed,
    RQStatus.STOPPED: JobStatus.failed,
    RQStatus.CANCELED: JobStatus.failed,
    RQStatus.DEFERRED: JobStatus.queued,
    RQStatus.SCHEDULED: JobStatus.queued,
}


def _cache_key(url: str, limit: int) -> str:
    digest = hashlib.sha256(f"{url}:{limit}".encode()).hexdigest()
    return f"cache:v1:{digest}"


def _map_rq_status(rq_status: RQStatus) -> JobStatus:
    return _RQ_STATUS_MAP.get(rq_status, JobStatus.failed)


def _fetch_job(job_id: str, conn: redis_lib.Redis) -> Job:
    try:
        return Job.fetch(job_id, connection=conn)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="Job not found")


# ── POST /v1/scrapes ──────────────────────────────────────────────────
@router.post(
    "/scrapes",
    response_model=ScrapeQueued,
    status_code=202,
    summary="Lancer un scrape",
    description="Enqueue un job de scraping. Retourne immédiatement un `job_id` à poller.",
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def create_scrape(
    request: Request,
    body: ScrapeRequest,
    redis=Depends(get_redis),
    _: str = Depends(require_api_key),
) -> ScrapeQueued:
    url_str = str(body.url)
    cache_key = _cache_key(url_str, body.limit)

    # Cache hit : créer un job synthétique immédiatement résolu.
    cached = redis.get(cache_key)
    if cached:
        job_id = f"cached-{uuid.uuid4().hex}"
        redis.setex(f"job:result:{job_id}", settings.job_result_ttl, cached)
        redis.setex(f"job:status:{job_id}", settings.job_result_ttl, JobStatus.done.value)
        return ScrapeQueued(job_id=job_id, status=JobStatus.done)

    from worker.tasks import run_scrape_job  # import tardif pour éviter les cycles

    q = Queue(_QUEUE_NAME, connection=redis)
    job = q.enqueue(
        run_scrape_job,
        url_str,
        body.limit,
        job_timeout=settings.job_timeout,
        result_ttl=settings.job_result_ttl,
        failure_ttl=settings.job_result_ttl,
    )
    return ScrapeQueued(job_id=job.id, status=JobStatus.queued)


# ── GET /v1/scrapes/{job_id} ──────────────────────────────────────────
@router.get(
    "/scrapes/{job_id}",
    response_model=JobStatusResponse,
    summary="Statut d'un job",
)
async def get_scrape_status(
    job_id: str,
    request: Request,
    redis=Depends(get_redis),
    _: str = Depends(require_api_key),
) -> JobStatusResponse:
    # Job synthétique (cache hit)
    synthetic = redis.get(f"job:status:{job_id}")
    if synthetic:
        return JobStatusResponse(job_id=job_id, status=JobStatus(synthetic))

    job = _fetch_job(job_id, redis)
    return JobStatusResponse(job_id=job_id, status=_map_rq_status(job.get_status()))


# ── GET /v1/scrapes/{job_id}/result ───────────────────────────────────
@router.get(
    "/scrapes/{job_id}/result",
    response_model=JobResultResponse,
    summary="Résultat d'un job",
    description="Retourne le résultat si `status=done`, sinon retourne le statut courant sans résultat.",
)
async def get_scrape_result(
    job_id: str,
    request: Request,
    redis=Depends(get_redis),
    _: str = Depends(require_api_key),
) -> JobResultResponse:
    # Job synthétique (cache hit)
    cached_result = redis.get(f"job:result:{job_id}")
    if cached_result:
        return JobResultResponse(
            job_id=job_id,
            status=JobStatus.done,
            result=json.loads(cached_result),
        )

    job = _fetch_job(job_id, redis)
    rq_status = job.get_status()
    api_status = _map_rq_status(rq_status)

    if api_status != JobStatus.done:
        error = str(job.exc_info).strip() if api_status == JobStatus.failed and job.exc_info else None
        return JobResultResponse(job_id=job_id, status=api_status, error=error)

    result_data: dict = job.result

    # Mettre en cache le résultat pour les requêtes identiques futures.
    if result_data and len(job.args) >= 2:
        url_str, limit = job.args[0], job.args[1]
        cache_key = _cache_key(url_str, limit)
        redis.setex(cache_key, settings.cache_ttl, json.dumps(result_data, ensure_ascii=False))

    return JobResultResponse(job_id=job_id, status=JobStatus.done, result=result_data)
