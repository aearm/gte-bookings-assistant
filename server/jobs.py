"""Long admin jobs (building the data layer, reading a cube, Claude drafting a cube's business words,
suggested charts): each runs in a thread of its own and writes progress lines that the page follows
(GET /api/jobs/{id}, or live with /api/jobs/{id}/events). The last LIMIT jobs are remembered."""
import threading
import uuid
from collections import OrderedDict
from datetime import datetime

from errors import details, friendly

LIMIT = 100


class Job:
    def __init__(self, kind: str):
        self.id, self.kind = uuid.uuid4().hex[:12], kind
        self.status, self.lines, self.error, self.details = "running", [], "", ""
        self.result = None
        self.started, self.finished = datetime.now().isoformat(timespec="seconds"), ""

    def say(self, text) -> None:
        """A progress line (the on_progress / on_step callback of the domain functions)."""
        self.lines.append(str(text))

    def to_json(self) -> dict:
        out = {"id": self.id, "kind": self.kind, "status": self.status, "lines": list(self.lines),
               "started": self.started, "finished": self.finished}
        if self.error:
            out.update(error=self.error, details=self.details)
        return out


_jobs: "OrderedDict[str, Job]" = OrderedDict()
_lock = threading.Lock()


def start(kind: str, work, single: bool = False) -> Job:
    """Run work(job) in the background. single = only one job of this kind at a time: if one is running,
    that one is returned instead of starting another."""
    with _lock:
        if single:
            running = next((j for j in _jobs.values() if j.kind == kind and j.status == "running"), None)
            if running:
                return running
        job = Job(kind)
        _jobs[job.id] = job
        while len(_jobs) > LIMIT:
            _jobs.popitem(last=False)

    def run():
        try:
            job.result = work(job)
            job.status = "done"
        except Exception as exc:
            job.error, job.details = friendly(exc), details(exc)
            job.say(f"✗ {job.error}")
            job.status = "failed"
        finally:
            job.finished = datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=run, name=f"job-{kind}-{job.id}", daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def clear() -> None:
    with _lock:
        _jobs.clear()
