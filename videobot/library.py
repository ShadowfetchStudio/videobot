"""Read-only library integrity/export helpers. Never infer a user file is disposable."""

import csv
import hashlib
import json
from pathlib import Path

from .runtime import public_data

MEDIA = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".wmv",
    ".flv",
    ".ts",
    ".mpeg",
    ".mp3",
    ".m4a",
    ".flac",
    ".wav",
    ".opus",
    ".ogg",
    ".aac",
    ".aiff",
    ".aif",
}


def bundle_files(job):
    root = Path(job["output"])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("job_id") != job["id"]:
        raise ValueError("Manifest does not belong to this job.")
    files = manifest.get("files", [])
    if not files:
        raise ValueError("Manifest has no files.")
    for item in files:
        name = item["name"]
        if Path(name).name != name or not name or (root / name).is_symlink():
            raise ValueError("Unsafe manifest file path.")
    return root, manifest


def playable(job):
    root, manifest = bundle_files(job)
    return next(
        (
            root / f["name"]
            for f in manifest["files"]
            if Path(f["name"]).suffix.lower() in MEDIA and (root / f["name"]).is_file()
        ),
        None,
    )


def verify(job, cancel):
    root, manifest = bundle_files(job)
    errors = []
    for item in manifest["files"]:
        path = root / item["name"]
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    cancel.check()
                    digest.update(block)
            if digest.hexdigest() != item["sha256"] or path.stat().st_size != item["bytes"]:
                errors.append(item["name"] + ": changed")
        except OSError:
            errors.append(item["name"] + ": missing or unreadable")
    return {"job_id": job["id"], "ok": not errors, "errors": errors}


def export_library(rows, path):
    entries = []
    for job in rows:
        if job["status"] == "completed" and job["output"]:
            try:
                _, manifest = bundle_files(job)
                entries.append(public_data(manifest))
            except (OSError, ValueError, KeyError):
                entries.append(
                    {"job_id": job["id"], "title": job["candidate"]["title"], "error": "Manifest missing or invalid"}
                )
    path = Path(path)
    if path.suffix.lower() == ".csv":
        keys = ["job_id", "title", "creator", "source_url", "retrieved_at", "rights_notes", "duration", "error"]

        # Spreadsheet programs interpret leading operators as formulas, even quoted CSV.
        def cell(value):
            text = str(value or "")
            return (
                "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")) else text
            )

        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            writer.writerows({k: cell(row.get(k)) for k in keys} for row in entries)
    else:
        path.write_text(
            json.dumps({"schema": 1, "items": entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return len(entries)
