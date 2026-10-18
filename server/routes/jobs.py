"""Following a long admin job: its state, or its progress lines live (Server-Sent Events)."""
import asyncio
import time

from fastapi import APIRouter, Depends

from server import jobs
from server.auth import require_admin
from server.replies import KEEP_ALIVE, event, not_found, stream

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_admin)])
POLL_SECONDS = 0.2
KEEP_ALIVE_SECONDS = 15


def job_or_404(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if job is None:
        raise not_found("This job")
    return job


@router.get("/jobs/{job_id}")
def read_job(job_id: str) -> dict:
    return job_or_404(job_id).to_json()


async def follow(job: jobs.Job):
    """line {"text"} for every progress line (the earlier ones first), then done {"status", "error"?}."""
    sent, quiet_since = 0, time.monotonic()
    while True:
        finished = job.status != "running"  # read before the lines, so none written meanwhile is missed
        lines = job.lines[sent:]
        for text in lines:
            yield event("line", {"text": text})
        sent += len(lines)
        if finished:
            yield event("done", {"status": job.status, **({"error": job.error, "details": job.details} if job.error else {})})
            return
        if lines:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since > KEEP_ALIVE_SECONDS:
            yield KEEP_ALIVE
            quiet_since = time.monotonic()
        await asyncio.sleep(POLL_SECONDS)


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str):
    return stream(follow(job_or_404(job_id)))
