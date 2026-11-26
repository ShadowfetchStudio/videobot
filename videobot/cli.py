"""Headless commands and a private JSON event protocol used by the desktop."""

import argparse
import json
import sys
import uuid
from pathlib import Path

from .engine import inspect_urls, run_queue
from .models import Options
from .runtime import Cancelled, Cancellation, diagnostics, emit_stdout, redact
from .storage import Store


def task(request):
    # Windowed frozen executables may have stdout/stderr set to None. The private
    # parent-owned event file keeps the protocol usable on Windows and macOS.
    if request.get("event_path") and sys.stdout is None:
        sys.stdout = open(request["event_path"], "a", buffering=1, encoding="utf-8")
        sys.stderr = sys.stdout
    cancel = Cancellation(request.get("cancel_path"))
    try:
        if request["action"] == "inspect":
            inspect_urls(request["urls"], Options(**request["options"]), cancel, emit_stdout)
            return 0
        status = run_queue(
            request.get("db"), cancel, emit_stdout, request.get("owner"), request.get("ids"), request.get("auth")
        )
        return 1 if status in ("failed", "partial") else 0
    except Cancelled:
        emit_stdout("result", status="cancelled")
        return 0
    except Exception as exc:
        emit_stdout("error", message=redact(exc))
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="VideoBot durable media queue")
    parser.add_argument("--db", help="Queue SQLite path (default: platform application-data directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check dependencies and tools")
    inspect = sub.add_parser("inspect", help="Discover selectable media without downloading")
    inspect.add_argument("urls", nargs="+")
    inspect.add_argument("--max-items", type=int, default=2000)
    add = sub.add_parser("add", help="Inspect URLs and queue their discovered media")
    add.add_argument("urls", nargs="+")
    add.add_argument("--destination", default=Options().destination)
    add.add_argument("--quality", default="best")
    add.add_argument("--container", default="native", choices=["native", "mp4", "webm"])
    add.add_argument("--audio-only", action="store_true")
    add.add_argument("--subtitles", default="")
    add.add_argument("--max-items", type=int, default=2000)
    sub.add_parser("list", help="List queue and history")
    retry = sub.add_parser("retry", help="Requeue failed/cancelled jobs")
    retry.add_argument("ids", nargs="+")
    run = sub.add_parser("run", help="Run queued jobs; Ctrl-C stops the current run")
    run.add_argument("--cookie-file", default="")
    run.add_argument("--cookie-browser", default="")
    internal = sub.add_parser("_task", help=argparse.SUPPRESS)
    internal.add_argument("request")
    args = parser.parse_args(argv)
    if args.command == "_task":
        request_path = Path(args.request)
        request = json.loads(request_path.read_text())
        request_path.unlink()
        return task(request)
    if args.command == "doctor":
        print(json.dumps(diagnostics(), indent=2))
        return 0
    store = Store(args.db)
    try:
        if args.command == "list":
            # Do not export private query parameters from stored source URLs.
            rows = store.rows()
            for row in rows:
                row["candidate"]["url"] = redact(row["candidate"]["url"])
                row["candidate"]["referer"] = redact(row["candidate"]["referer"])
            print(json.dumps(rows, indent=2))
            return 0
        if args.command == "retry":
            store.retry(args.ids)
            return 0
        cancel = Cancellation()
        if args.command == "run":
            owner = uuid.uuid4().hex
            try:
                status = run_queue(
                    store.path,
                    cancel,
                    emit_stdout,
                    owner=owner,
                    auth={"cookie_file": args.cookie_file, "cookie_browser": args.cookie_browser},
                )
                return 1 if status in ("failed", "partial") else 0
            except KeyboardInterrupt:
                cancel.event.set()
                store.interrupt_owner(owner)
                return 130
        options = Options()
        for key in ("destination", "quality", "container", "audio_only", "subtitles", "max_items"):
            if hasattr(args, key):
                setattr(options, key, getattr(args, key))
        items = inspect_urls(args.urls, options, cancel, emit_stdout)
        if args.command == "add":
            for candidate in items:
                job_id, added = store.add(candidate, options)
                emit_stdout("queued", job_id=job_id, added=added)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(redact(exc), file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
