"""Headless commands and a private JSON event protocol used by the desktop."""

import argparse
import json
import sys
import uuid
from pathlib import Path

from .engine import inspect_urls, run_queue
from .models import Candidate, Options
from .runtime import Cancelled, Cancellation, configure_tool_path, diagnostics, emit_stdout, public_data, redact
from .storage import Store


def task(request):
    # Windowed frozen executables may have stdout/stderr set to None. The private
    # parent-owned event file keeps the protocol usable on Windows and macOS.
    if request.get("event_path") and sys.stdout is None:
        sys.stdout = open(request["event_path"], "a", buffering=1, encoding="utf-8")
        sys.stderr = sys.stdout
    cancel = Cancellation(request.get("cancel_path"))
    try:
        if request["action"] in ("import_bundles", "export_collection", "correct_transcript", "export_excerpts"):
            from .recovery import import_bundles, export_collection
            from .media_tools import completed, save_transcript, create_clip

            store = Store(request.get("db"))
            try:
                action = request["action"]
                if action == "import_bundles":
                    results = import_bundles(store, request["root"], cancel, emit_stdout)
                    failed = sum(not r["ok"] for r in results)
                    emit_stdout(
                        "result",
                        status="partial" if failed else "completed",
                        count=len(results) - failed,
                        failed=failed,
                    )
                elif action == "export_collection":
                    result = export_collection(store, request["ids"], request["destination"], cancel, emit_stdout)
                    emit_stdout("result", status="completed", message="Collection saved: " + result)
                elif action == "correct_transcript":
                    job = completed(store, request["job_id"])
                    active = store.transcript(job["id"])
                    if not active or active["folder"] != request["revision"]:
                        raise ValueError("Transcript changed; reopen the editor.")
                    save_transcript(
                        store,
                        job,
                        request["segments"],
                        active["model"],
                        active["language"],
                        active["media_sha256"],
                        cancel,
                        machine_generated=False,
                    )
                    emit_stdout("result", status="completed", message="Reviewed transcript saved as a new revision.")
                else:
                    for item in request["excerpts"]:
                        cancel.check()
                        result = create_clip(
                            store,
                            request["job_id"],
                            item["start"],
                            item["end"],
                            request["destination"],
                            cancel,
                            emit_stdout,
                            name=item["name"],
                        )
                        emit_stdout("log", message=item["name"] + ": " + result["output"])
                    emit_stdout("result", status="completed", count=len(request["excerpts"]))
                return 0
            finally:
                store.close()
        if request["action"] in ("clip", "transcribe", "relink"):
            from .media_tools import create_clip, transcribe, relink

            store = Store(request.get("db"))
            try:
                if request["action"] == "clip":
                    result = create_clip(
                        store,
                        request["job_id"],
                        float(request["start"]),
                        float(request["end"]),
                        request["destination"],
                        cancel,
                        emit_stdout,
                    )
                    emit_stdout(
                        "result", status="completed", count=1, message="Clip saved: " + result["output"], **result
                    )
                elif request["action"] == "transcribe":
                    if request.get("backend") == "metal":
                        from .media_tools import transcribe_cpp

                        result = transcribe_cpp(
                            store, request["job_id"], request.get("model_path", ""), cancel, emit_stdout
                        )
                    else:
                        result = transcribe(
                            store,
                            request["job_id"],
                            request.get("model", "tiny"),
                            request.get("allow_download", False),
                            cancel,
                            emit_stdout,
                        )
                    emit_stdout(
                        "result",
                        status="completed",
                        count=1,
                        message=f"Transcript saved: {result['segments']} segments. Review automatic text before publishing.",
                        **result,
                    )
                else:
                    results = relink(store, request["ids"], request["root"], cancel, emit_stdout)
                    failed = sum(not r["ok"] for r in results)
                    emit_stdout(
                        "result",
                        status="partial" if failed else "completed",
                        completed=len(results) - failed,
                        failed=failed,
                    )
                    return int(bool(failed))
                return 0
            finally:
                store.close()
        if request["action"] == "doctor":
            emit_stdout("diagnostics", report=diagnostics())
            emit_stdout("result", status="completed")
            return 0
        if request["action"] == "verify":
            from .library import verify

            failed = 0
            for job in request["jobs"]:
                result = verify(job, cancel)
                failed += not result["ok"]
                emit_stdout("verification", **result)
            emit_stdout(
                "result",
                status="failed" if failed else "completed",
                failed=failed,
                completed=len(request["jobs"]) - failed,
            )
            return int(bool(failed))
        if request["action"] == "download":
            from .downloader import Downloader

            path, info = Downloader(Options(**request["options"]), cancel, emit_stdout)._ytdlp_inline(
                Candidate(**request["candidate"]), Path(request["work"])
            )
            public = {key: info.get(key) for key in ("title", "uploader", "extractor_key", "id", "chapters")}
            emit_stdout("transfer_complete", path=str(path), info=public)
            return 0
        if request["action"] == "inspect":
            inspect_urls(request["urls"], Options(**request["options"]), cancel, emit_stdout)
            return 0
        if request["action"] != "run":
            raise ValueError("Unknown worker action")
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
    configure_tool_path()
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
    for command in (inspect, add):
        command.add_argument("--cookie-file", default="")
        command.add_argument("--cookie-browser", default="")
        command.add_argument("--max-pages", type=int, default=50)
    add.add_argument("--audio-format", default="mp3", choices=["mp3", "m4a", "flac", "wav", "opus"])
    add.add_argument("--audio-bitrate", type=int, default=192)
    add.add_argument("--accurate-range", action="store_true")
    add.add_argument("--segment-start", type=float)
    add.add_argument("--segment-end", type=float)
    add.add_argument("--editing-compatible", action="store_true")
    add.add_argument("--automatic-subtitles", action="store_true")
    add.add_argument("--thumbnail", action="store_true")
    add.add_argument("--no-metadata", dest="embed_metadata", action="store_false")
    add.add_argument("--rate-limit", type=int, default=0, help="Bytes per second; zero is unlimited")
    add.add_argument("--max-bytes", type=int, default=Options().max_bytes)
    add.add_argument("--min-free-bytes", type=int, default=Options().min_free_bytes)
    add.add_argument("--retries", type=int, default=3)
    add.add_argument("--cooldown", type=float, default=5)
    add.add_argument("--project", default="")
    add.add_argument("--tags", default="")
    add.add_argument("--rights-notes", default=Options().rights_notes)
    listing = sub.add_parser("list", help="List queue and history (redacted)")
    listing.add_argument("--removed", action="store_true", help="Include removed records")
    for name in ("retry", "remove", "restore", "verify"):
        command = sub.add_parser(name)
        command.add_argument("ids", nargs="+")
    edit = sub.add_parser("edit", help="Update idle job settings with a JSON object; retains ID/history")
    edit.add_argument("id")
    edit.add_argument("settings", help="Path to JSON object of Options fields to change")
    organize = sub.add_parser("organize", help="Set priority and/or scheduled Unix timestamp")
    organize.add_argument("ids", nargs="+")
    organize.add_argument("--priority", type=int)
    organize.add_argument("--not-before", type=float)
    for name in ("export", "backup"):
        command = sub.add_parser(name)
        command.add_argument("path")
    run = sub.add_parser("run", help="Run eligible queued jobs; Ctrl-C stops the current run")
    run.add_argument("--ids", nargs="+", help="Run only selected job IDs")
    run.add_argument("--cookie-file", default="")
    run.add_argument("--cookie-browser", default="")
    cleanup = sub.add_parser(
        "clean-partials", help="Inventory selected jobs' staging; --delete removes only their partial files"
    )
    cleanup.add_argument("ids", nargs="+")
    cleanup.add_argument("--delete", action="store_true")
    restore_db = sub.add_parser("restore-backup", help="Restore backup to a new database, never overwriting a queue")
    restore_db.add_argument("source")
    restore_db.add_argument("target")
    clip = sub.add_parser("clip", help="Export a marked range from saved media into a new library bundle")
    clip.add_argument("job_id")
    clip.add_argument("start", type=float)
    clip.add_argument("end", type=float)
    clip.add_argument("destination")
    transcript = sub.add_parser("transcribe", help="Transcribe saved media locally on CPU")
    transcript.add_argument("job_id")
    transcript.add_argument("--model", choices=["tiny", "base", "small"], default="tiny")
    transcript.add_argument("--allow-download", action="store_true", help="Allow first-use speech model download")
    relink = sub.add_parser("relink", help="Verify and reconnect selected bundles under a new root")
    relink.add_argument("root")
    relink.add_argument("ids", nargs="+")
    search = sub.add_parser("search-transcripts", help="Find literal text in indexed transcript segments")
    search.add_argument("query")
    internal = sub.add_parser("_task", help=argparse.SUPPRESS)
    internal.add_argument("request")
    args = parser.parse_args(argv)
    if args.command == "_task":
        request_path = Path(args.request)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request_path.unlink()
        return task(request)
    if args.command in ("clip", "transcribe", "relink"):
        return task({**vars(args), "action": args.command})
    if args.command == "doctor":
        print(json.dumps(diagnostics(), indent=2))
        return 0
    if args.command == "restore-backup":
        from .maintenance import restore_backup

        try:
            print(restore_backup(args.source, args.target))
            return 0
        except Exception as exc:
            print(redact(exc), file=sys.stderr)
            return 1
    store = Store(args.db)
    try:
        if args.command == "search-transcripts":
            print(json.dumps(public_data(store.search_transcripts(args.query)), indent=2, ensure_ascii=False))
            return 0
        if args.command == "clean-partials":
            from .maintenance import staging

            print(json.dumps(staging(store, args.ids, delete=args.delete), indent=2))
            return 0
        if args.command == "list":
            print(json.dumps(public_data(store.rows(include_removed=args.removed)), indent=2))
            return 0
        if args.command in ("retry", "remove", "restore"):
            getattr(store, args.command)(args.ids)
            return 0
        if args.command == "organize":
            store.organize(args.ids, args.priority, args.not_before)
            return 0
        if args.command == "edit":
            job = next((r for r in store.rows() if r["id"] == args.id), None)
            if job is None:
                raise ValueError("Job not found.")
            changes = json.loads(Path(args.settings).read_text(encoding="utf-8"))
            store.edit(args.id, Options(**{**job["options"], **changes}))
            return 0
        if args.command == "backup":
            print(store.backup(args.path))
            return 0
        if args.command == "export":
            from .library import export_library

            print(export_library(store.rows(), args.path))
            return 0
        if args.command == "verify":
            from .library import verify

            jobs = [r for r in store.rows() if r["id"] in args.ids]
            if len(jobs) != len(set(args.ids)) or any(r["status"] != "completed" for r in jobs):
                raise ValueError("Select existing completed jobs to verify.")
            results = [verify(r, Cancellation()) for r in jobs]
            print(json.dumps(results, indent=2))
            return int(any(not r["ok"] for r in results))
        cancel = Cancellation()
        if args.command == "run":
            owner = uuid.uuid4().hex
            try:
                status = run_queue(
                    store.path,
                    cancel,
                    emit_stdout,
                    owner=owner,
                    ids=args.ids,
                    auth={"cookie_file": args.cookie_file, "cookie_browser": args.cookie_browser},
                )
                return 1 if status in ("failed", "partial") else 0
            except KeyboardInterrupt:
                cancel.event.set()
                store.interrupt_owner(owner)
                return 130
        options = Options()
        for key in Options.__dataclass_fields__:
            if hasattr(args, key):
                setattr(options, key, getattr(args, key))
        failed = []

        def event(kind, **data):
            if kind == "discovery_error":
                failed.append(data)
            emit_stdout(kind, **public_data(data))

        items = inspect_urls(args.urls, options, cancel, event)
        if args.command == "add":
            for candidate in items:
                job_id, added = store.add(candidate, options)
                emit_stdout("queued", job_id=job_id, added=added)
        return int(bool(failed))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(redact(exc), file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
