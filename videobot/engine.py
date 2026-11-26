"""Shared orchestration: the CLI and desktop execute the same durable jobs."""

import uuid

from .discovery import Discovery
from .downloader import Downloader
from .models import Candidate, Options
from .runtime import Cancelled, redact
from .storage import Store


def inspect_urls(urls, options, cancel, emit):
    items = Discovery(options, cancel, emit).inspect(urls)
    emit("result", status="completed", count=len(items))
    return items


def run_queue(db_path, cancel, emit, owner=None, ids=None, auth=None):
    owner = owner or uuid.uuid4().hex
    store = Store(db_path)
    totals = {"completed": 0, "failed": 0, "cancelled": 0}
    try:
        store.recover()
        while not cancel.cancelled():
            job = store.claim(owner, ids)
            if not job:
                break
            options = Options(**job["options"])
            if auth:
                options.cookie_file = auth.get("cookie_file", "")
                options.cookie_browser = auth.get("cookie_browser", "")
            candidate = Candidate(**job["candidate"])
            emit("job", job_id=job["id"], status="running", title=candidate.title)

            def event(kind, **data):
                data.setdefault("job_id", job["id"])
                emit(kind, **data)

            try:
                output = Downloader(options, cancel, event).download(job["id"], candidate)
                store.finish(job["id"], owner, "completed", output=output)
                totals["completed"] += 1
                emit("job", job_id=job["id"], status="completed", output=output)
                emit("phase", phase="cooldown", seconds=options.cooldown)
                try:
                    cancel.wait(options.cooldown)
                except Cancelled:
                    break
            except Cancelled:
                store.finish(job["id"], owner, "cancelled", error="Stopped; retry to resume supported downloads.")
                totals["cancelled"] += 1
                break
            except Exception as exc:
                if cancel.cancelled():
                    store.finish(job["id"], owner, "cancelled", error="Stopped.")
                    totals["cancelled"] += 1
                    break
                message = redact(exc)
                store.finish(job["id"], owner, "failed", error=message)
                totals["failed"] += 1
                emit("job", job_id=job["id"], status="failed", error=message)
                try:
                    cancel.wait(min(5, options.cooldown))
                except Cancelled:
                    break
        status = (
            "cancelled"
            if cancel.cancelled()
            else "partial"
            if totals["failed"] and totals["completed"]
            else "failed"
            if totals["failed"]
            else "completed"
        )
        emit("result", status=status, **totals)
        return status
    finally:
        store.close()
