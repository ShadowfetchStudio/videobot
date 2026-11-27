"""Local library operations. Originals are immutable; derived outputs are new bundles."""

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
import uuid

from .library import bundle_files, playable, verify
from .runtime import media_probe, run_checked

MODELS = ("tiny", "base", "small")


def completed(store, job_id):
    job = next((r for r in store.rows() if r["id"] == job_id and r["status"] == "completed"), None)
    if not job:
        raise ValueError("Select an existing completed library item.")
    return job


def checked_media(job, cancel):
    result = verify(job, cancel)
    if not result["ok"]:
        raise ValueError("Source verification failed: " + "; ".join(result["errors"]))
    path = playable(job)
    if not path:
        raise ValueError("Media is missing. Relink its bundle first.")
    return path


def file_record(path, cancel):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            cancel.check()
            digest.update(block)
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def relink(store, ids, root, cancel, emit):
    """Bounded search without following directory links; duplicates require a narrower root."""
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Choose a bundle folder or its new parent folder.")
    jobs = {j["id"]: j for j in store.rows() if j["id"] in ids and j["status"] == "completed"}
    if not jobs or set(ids) != set(jobs):
        raise ValueError("Relink requires completed, visible library items.")
    matches = {key: [] for key in jobs}
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        cancel.check()
        count += 1
        if count > 20000:
            raise ValueError("Search exceeded 20,000 folders. Choose a narrower parent folder.")
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink() and not d.startswith(".")]
        if len(Path(directory).relative_to(root).parts) >= 8:
            if dirs:
                raise ValueError("Search exceeded eight folder levels. Choose a narrower parent folder.")
            dirs[:] = []
        if "manifest.json" not in files:
            continue
        manifest_path = Path(directory) / "manifest.json"
        if manifest_path.is_symlink() or manifest_path.stat().st_size > 10 * 1024**2:
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            job_id = manifest.get("job_id")
            if job_id in jobs:
                matches[job_id].append(str(Path(directory).resolve()))
        except (OSError, ValueError, AttributeError):
            continue
    results = []
    for job_id, job in jobs.items():
        cancel.check()
        paths = matches[job_id]
        if len(paths) != 1:
            results.append(
                {
                    "job_id": job_id,
                    "ok": False,
                    "error": "No matching bundle" if not paths else "Multiple matching bundles; choose one folder",
                }
            )
            continue
        candidate = {**job, "output": paths[0]}
        try:
            emit("phase", phase="Verifying moved media")
            _, manifest = bundle_files(candidate)
            if manifest.get("options") != job["options"]:
                raise ValueError("Bundle output settings do not match this library revision.")
            result = verify(candidate, cancel)
            if not result["ok"]:
                raise ValueError("; ".join(result["errors"]))
            active = store.transcript(job_id)
            if active:
                sidecars = Path(paths[0]) / active["folder"]
                if (
                    sidecars.parent != Path(paths[0])
                    or sidecars.is_symlink()
                    or not all(
                        (sidecars / name).is_file() for name in ("transcript.json", "transcript.txt", "transcript.vtt")
                    )
                ):
                    raise ValueError(
                        "Active transcript files are missing. Copy the complete bundle, including transcript folders, then relink again."
                    )
                data = json.loads((sidecars / "transcript.json").read_text())
                if data.get("segments") != active["segments"] or data.get("media_sha256") != active["media_sha256"]:
                    raise ValueError("Active transcript revision does not match the library index.")
            cancel.check()
            with store.db:
                changed = store.db.execute(
                    "UPDATE jobs SET output=?,updated=? WHERE id=? AND output=? AND status='completed' AND removed=0",
                    (paths[0], time.time(), job_id, job["output"]),
                ).rowcount
                if not changed:
                    raise ValueError("Library item changed during verification. Retry relinking.")
            results.append({"job_id": job_id, "ok": True, "output": paths[0]})
        except (OSError, ValueError, KeyError) as exc:
            results.append({"job_id": job_id, "ok": False, "error": str(exc)})
    for result in results:
        emit("relink", **result)
    return results


def create_clip(store, job_id, start, end, destination, cancel, emit, name=None):
    if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end:
        raise ValueError("Clip markers must be finite, with Out after In.")
    job = completed(store, job_id)
    emit("phase", phase="Verifying clip source")
    source = checked_media(job, cancel)
    audio_only = job["options"].get("audio_only", False)
    probe = media_probe(source, cancel, audio_only=audio_only)
    duration = float(probe["format"].get("duration", 0))
    if not duration or end > duration + 0.05:
        raise ValueError("Clip markers extend beyond the saved media duration.")
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    new_id = uuid.uuid4().hex
    work = destination / (".videobot-clip-" + new_id)
    final = destination / ("VideoBot-" + new_id)
    work.mkdir()
    output = work / ("clip.m4a" if audio_only else "clip.mp4")
    try:

        def guard():
            if shutil.disk_usage(destination).free < job["options"].get("min_free_bytes", 512 * 1024**2):
                raise OSError("Clip stopped to preserve the free-space reserve.")
            if output.exists() and output.stat().st_size > job["options"].get("max_bytes", 10 * 1024**3):
                raise OSError("Clip exceeded the configured output size limit.")

        emit("phase", phase="Encoding marked clip")
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-protocol_whitelist",
            "file,pipe,crypto",
            "-i",
            str(source),
            "-ss",
            str(start),
            "-t",
            str(end - start),
        ]
        if audio_only:
            command += ["-vn", "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
        else:
            command += [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                "-c:a",
                "aac",
            ]
        run_checked(command + ["-movflags", "+faststart", str(output)], cancel, timeout=86400, guard=guard)
        guard()
        media_probe(output, cancel, audio_only=audio_only)
        _, original = bundle_files(job)
        record = file_record(output, cancel)
        source_record = next(f for f in original["files"] if f["name"] == source.name)
        options = {
            **job["options"],
            "destination": str(destination),
            "segment_start": start,
            "segment_end": end,
            "accurate_range": True,
            "container": "native" if audio_only else "mp4",
            "audio_format": "m4a" if audio_only else job["options"].get("audio_format", "mp3"),
        }
        candidate = {
            **job["candidate"],
            "title": (str(name)[:200] if name else job["candidate"]["title"] + f" — clip {start:g}–{end:g}s"),
        }
        manifest = {
            **original,
            "job_id": new_id,
            "title": candidate["title"],
            "options": options,
            "files": [record],
            "duration": end - start,
            "chapters": [],
            "derived_from": {"job_id": job_id, "sha256": source_record["sha256"], "start": start, "end": end},
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        cancel.check()
        work.rename(final)
        with store.db:
            store.db.execute(
                "INSERT INTO jobs(id,identity,candidate,options,status,created,updated,output) VALUES(?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    "clip:" + new_id,
                    json.dumps(candidate),
                    json.dumps(options),
                    "completed",
                    time.time(),
                    time.time(),
                    str(final),
                ),
            )
        return {"job_id": new_id, "output": str(final)}
    except Exception as exc:
        if final.exists():
            raise RuntimeError(
                f"Clip retained at {final}. Use Recovery → Import verified bundles to register it. {exc}"
            ) from exc
        raise
    finally:
        if work.exists():
            shutil.rmtree(work)


def timestamp(seconds):
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{ms:03}"


def save_transcript(store, job, segments, model, language, media_sha256, cancel, machine_generated=True):
    """Publish new sidecars together, then atomically replace the searchable DB index."""
    normalized = []
    for item in segments:
        start, end = float(item["start"]), float(item["end"])
        if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start <= end:
            raise ValueError("Invalid transcript timestamps.")
        normalized.append({"start": start, "end": end, "text": str(item["text"]).strip()})
    root = Path(job["output"])
    token = uuid.uuid4().hex
    temporary = root / (".transcript-" + token)
    target = root / ("transcript-" + token)
    temporary.mkdir()
    data = {
        "schema": 1,
        "job_id": job["id"],
        "model": model,
        "language": language,
        "media_sha256": media_sha256,
        "machine_generated": machine_generated,
        "segments": normalized,
    }
    try:
        (temporary / "transcript.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (temporary / "transcript.txt").write_text("\n".join(s["text"] for s in normalized) + "\n", encoding="utf-8")
        vtt = (
            "WEBVTT\n\n"
            + "\n\n".join(
                f"{timestamp(s['start'])} --> {timestamp(s['end'])}\n{s['text'].replace('-->', '→')}"
                for s in normalized
            )
            + "\n"
        )
        (temporary / "transcript.vtt").write_text(vtt, encoding="utf-8")
        cancel.check()
        temporary.rename(target)
        with store.db:
            store.db.execute("BEGIN IMMEDIATE")
            live = store.db.execute("SELECT output,status,removed FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if not live or live["output"] != job["output"] or live["status"] != "completed" or live["removed"]:
                raise ValueError("Library item changed during transcription; sidecars retained, index not changed.")
            store.db.execute("DELETE FROM transcripts WHERE job_id=?", (job["id"],))
            store.db.execute(
                "INSERT INTO transcripts VALUES(?,?,?,?,?,?)",
                (job["id"], json.dumps(data), target.name, model, language, time.time()),
            )
            store.db.execute("DELETE FROM transcript_segments WHERE job_id=?", (job["id"],))
            store.db.executemany(
                "INSERT INTO transcript_segments VALUES(?,?,?,?,?)",
                [(job["id"], n, s["start"], s["end"], s["text"]) for n, s in enumerate(normalized)],
            )
        pointer = root / (".active-transcript-" + token)
        pointer.write_text(json.dumps({"folder": target.name}))
        pointer.replace(root / "active-transcript.json")
        return str(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def transcribe(store, job_id, model, allow_download, cancel, emit):
    if model not in MODELS:
        raise ValueError("Choose tiny, base or small.")
    job = completed(store, job_id)
    emit("phase", phase="Verifying transcription source")
    source = checked_media(job, cancel)
    media_probe(source, cancel, audio_only=True)
    from faster_whisper import WhisperModel

    cache = store.path.parent / "speech-models"
    if allow_download:
        required = {"tiny": 100, "base": 200, "small": 600}[model] * 1024**2
        if shutil.disk_usage(store.path.parent).free < required + 512 * 1024**2:
            raise OSError("Not enough free space for the speech model and a 512 MiB reserve.")
    emit("phase", phase="Loading local speech model" + (" (first use downloads model)" if allow_download else ""))
    cancel.check()
    engine = WhisperModel(
        model,
        device="cpu",
        compute_type="int8",
        cpu_threads=min(4, os.cpu_count() or 1),
        download_root=str(cache),
        local_files_only=not allow_download,
    )
    segments, info = engine.transcribe(str(source), beam_size=5, vad_filter=True)
    rows = []
    for segment in segments:
        cancel.check()
        rows.append({"start": segment.start, "end": segment.end, "text": segment.text})
        emit("progress", phase="Transcribing locally", percent=min(99, segment.end / max(info.duration, 1) * 100))
    cancel.check()
    _, manifest = bundle_files(job)
    digest = next(f["sha256"] for f in manifest["files"] if f["name"] == source.name)
    path = save_transcript(store, job, rows, model, info.language, digest, cancel)
    return {"job_id": job_id, "output": path, "segments": len(rows), "language": info.language}


def transcribe_cpp(store, job_id, model_path, cancel, emit):
    """Optional Apple Metal backend via the official whisper.cpp CLI; no model upload."""
    import tempfile

    executable = shutil.which("whisper-cli")
    if not executable:
        raise ValueError(
            "Install whisper.cpp (brew install whisper-cpp), then restart VideoBot or choose its tools folder."
        )
    model = Path(model_path).expanduser()
    if not model.is_file() or model.suffix != ".bin":
        raise ValueError("Choose a local whisper.cpp GGML .bin model.")
    job = completed(store, job_id)
    source = checked_media(job, cancel)
    probe = media_probe(source, cancel, audio_only=True)
    duration = float(probe["format"].get("duration", 0))
    if shutil.disk_usage(store.path.parent).free < duration * 32000 + 512 * 1024**2:
        raise OSError("Insufficient space for decoded speech and a 512 MiB reserve.")
    with tempfile.TemporaryDirectory(prefix=".speech-", dir=store.path.parent) as temp:
        wav = Path(temp) / "audio.wav"
        output = Path(temp) / "recognized"
        emit("phase", phase="Preparing audio for Apple Metal transcription")
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            cancel,
            timeout=86400,
        )
        emit("phase", phase="Transcribing locally with whisper.cpp (Metal requested)")
        run_checked(
            [executable, "-m", str(model.resolve()), "-f", str(wav), "-oj", "-of", str(output), "-l", "auto", "-np"],
            cancel,
            timeout=86400,
        )
        data = json.loads(output.with_suffix(".json").read_text())
        rows = [
            {"start": s["offsets"]["from"] / 1000, "end": s["offsets"]["to"] / 1000, "text": s["text"]}
            for s in data["transcription"]
        ]
        _, manifest = bundle_files(job)
        digest = next(f["sha256"] for f in manifest["files"] if f["name"] == source.name)
        language = data.get("result", {}).get("language", "unknown")
        path = save_transcript(store, job, rows, "whisper.cpp:" + model.name, language, digest, cancel)
        return {"job_id": job_id, "output": path, "segments": len(rows), "language": language}
