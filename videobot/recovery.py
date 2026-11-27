"""Verified bundle import and portable collections. Existing records/files are never overwritten."""

import json
import sqlite3
import re
import shutil
import time
import math
from pathlib import Path

from .library import verify
from .models import Candidate, Options
from .storage import output_identity


def import_bundles(store, root, cancel, emit):
    root = Path(root).expanduser().resolve(strict=True)
    results = []
    import os

    for count, (directory, dirs, files) in enumerate(os.walk(root, followlinks=False)):
        cancel.check()
        if count >= 20000:
            raise ValueError("Import exceeds 20,000 folders. Choose a narrower root.")
        dirs[:] = [d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink()]
        if len(Path(directory).relative_to(root).parts) >= 8:
            dirs[:] = []
        if "manifest.json" not in files:
            continue
        folder = Path(directory)
        registered = False
        jid = None
        try:
            path = folder / "manifest.json"
            if path.is_symlink() or path.stat().st_size > 10 * 1024**2:
                raise ValueError("Unsafe or oversized manifest")
            manifest = json.loads(path.read_text())
            jid = manifest["job_id"]
            if not isinstance(jid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", jid):
                raise ValueError("Invalid job ID")
            options = Options(**manifest["options"])
            options.validate()
            candidate = Candidate(
                manifest.get("source_url") or "https://example.invalid/import/" + jid,
                title=manifest.get("title", "Imported media"),
            )
            job = {"id": jid, "output": str(folder), "options": options.public_dict()}
            checked = verify(job, cancel)
            if not checked["ok"]:
                raise ValueError("; ".join(checked["errors"]))
            excerpts = None
            notes = folder / "research-notes.json"
            if notes.exists():
                if notes.is_symlink() or notes.stat().st_size >= 1024**2:
                    raise ValueError("Unsafe or oversized research notes")
                data = json.loads(notes.read_text())
                excerpts = data.get("excerpts", [])
                if not isinstance(excerpts, list) or len(excerpts) > 1000:
                    raise ValueError("Invalid imported excerpts")
                for excerpt in excerpts:
                    if not isinstance(excerpt, dict) or not isinstance(excerpt.get("name"), str):
                        raise ValueError("Invalid imported excerpt")
                    start, end = float(excerpt["start"]), float(excerpt["end"])
                    if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end:
                        raise ValueError("Invalid imported excerpt")
                    excerpt.update(start=start, end=end)
            transcript = None
            pointer = folder / "active-transcript.json"
            if pointer.exists():
                if pointer.is_symlink() or pointer.stat().st_size > 4096:
                    raise ValueError("Unsafe transcript pointer")
                active = json.loads(pointer.read_text())
                name = active["folder"]
                if not isinstance(name, str) or Path(name).name != name:
                    raise ValueError("Invalid active transcript folder")
                sidecar = folder / name
                if sidecar.is_symlink():
                    raise ValueError("Invalid active transcript folder")
                data_path = sidecar / "transcript.json"
                if data_path.is_symlink() or data_path.stat().st_size > 32 * 1024**2:
                    raise ValueError("Unsafe or oversized transcript")
                transcript = json.loads(data_path.read_text())
                if transcript["job_id"] != jid or transcript["media_sha256"] not in {
                    item["sha256"] for item in manifest["files"]
                }:
                    raise ValueError("Transcript does not match this media bundle")
            with store.db:
                exists = store.db.execute("SELECT id FROM jobs WHERE id=?", (jid,)).fetchone()
                if exists:
                    results.append(
                        {"job_id": jid, "ok": True, "message": "Already registered; use Relink to change its path"}
                    )
                    continue
                now = time.time()
                identity = "clip:" + jid if manifest.get("derived_from") else output_identity(candidate, options)
                store.db.execute(
                    "INSERT INTO jobs(id,identity,candidate,options,status,created,updated,output) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        jid,
                        identity,
                        json.dumps(candidate.to_dict()),
                        json.dumps(options.public_dict()),
                        "completed",
                        now,
                        now,
                        str(folder),
                    ),
                )
            registered = True
            # Import the explicit active revision only, never guess among historical copies.
            if transcript is not None:
                from .media_tools import save_transcript

                save_transcript(
                    store,
                    job,
                    transcript["segments"],
                    transcript["model"],
                    transcript["language"],
                    transcript["media_sha256"],
                    cancel,
                    machine_generated=transcript.get("machine_generated", True),
                )
            if excerpts is not None:
                store.set_setting("excerpts:" + jid, excerpts)
            registered = False
            results.append({"job_id": jid, "ok": True, "message": "Verified bundle imported"})
        except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.IntegrityError) as exc:
            results.append({"output": str(folder), "ok": False, "message": str(exc)})
        finally:
            if registered:
                with store.db:
                    store.db.execute("DELETE FROM transcript_segments WHERE job_id=?", (jid,))
                    store.db.execute("DELETE FROM transcripts WHERE job_id=?", (jid,))
                    store.db.execute("DELETE FROM jobs WHERE id=?", (jid,))
    for result in results:
        emit("log", message=result.get("job_id", result.get("output", "")) + ": " + result["message"])
    return results


def export_collection(store, ids, destination, cancel, emit):
    destination = Path(destination).expanduser()
    if destination.exists():
        raise ValueError("Choose a NEW collection folder; existing files are preserved.")
    jobs = [j for j in store.rows() if j["id"] in ids and j["status"] == "completed"]
    if not jobs or len(jobs) != len(set(ids)):
        raise ValueError("Select completed library items.")
    for job in jobs:
        if destination.resolve().is_relative_to(Path(job["output"]).resolve()):
            raise ValueError("Collection must be outside the source bundles.")
        result = verify(job, cancel)
        if not result["ok"]:
            raise ValueError("; ".join(result["errors"]))
    destination.mkdir(parents=True)
    copied = []

    def copy_file(source, target):
        cancel.check()
        if Path(source).is_symlink():
            raise ValueError("Symlinked collection files are not supported.")
        with open(source, "rb") as src, open(target, "xb") as dst:
            while block := src.read(1024**2):
                cancel.check()
                dst.write(block)
        shutil.copystat(source, target)

    for job in jobs:
        cancel.check()
        emit("phase", phase="Copying verified collection")
        source = Path(job["output"])
        if any(p.is_symlink() for p in source.rglob("*")):
            raise ValueError("Symlinked collection files are not supported.")
        shutil.copytree(source, destination / job["id"], copy_function=copy_file)
        copied_job = dict(job, output=str(destination / job["id"]))
        checked = verify(copied_job, cancel)
        if not checked["ok"]:
            raise ValueError("Copied bundle failed verification: " + "; ".join(checked["errors"]))
        (destination / job["id"] / "research-notes.json").write_text(
            json.dumps({"excerpts": store.setting("excerpts:" + job["id"], [])}, indent=2)
        )
        copied.append(job["id"])
    (destination / "collection.json").write_text(json.dumps({"schema": 1, "jobs": copied, "complete": True}, indent=2))
    return str(destination)
