"""Download into job-owned staging; validate before publishing a complete bundle."""

import hashlib
import json
import os
import re
import shutil
import time
import subprocess
import sys
import tempfile
from dataclasses import asdict
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
import yt_dlp
from yt_dlp.utils import download_range_func

from .models import Candidate, Options
from .runtime import Logger, media_probe, redact, run_checked, terminate_process_tree


def format_selector(options):
    if options.audio_only:
        return "bestaudio/best"
    direction = "worst" if options.quality == "worst" else "best"
    ceiling = f"[height<={options.quality}]" if options.quality.isdigit() else ""
    if options.container == "webm":
        return f"{direction}video{ceiling}[ext=webm]+{direction}audio[ext=webm]/{direction}{ceiling}[ext=webm]"
    if options.container == "mp4" or options.editing_compatible:
        # Preference within a hard height limit; ffmpeg handles compatible remux.
        return f"{direction}video{ceiling}[ext=mp4]+{direction}audio[ext=m4a]/{direction}{ceiling}[ext=mp4]/{direction}video{ceiling}+{direction}audio/{direction}{ceiling}"
    return f"{direction}video{ceiling}+{direction}audio/{direction}{ceiling}"


def common_options(options, emit, cancel):
    def hook(_):
        cancel.check()

    result = {
        "quiet": True,
        "no_warnings": False,
        "logger": Logger(emit),
        "socket_timeout": 15,
        "retries": options.retries,
        "fragment_retries": options.retries,
        "extractor_retries": options.retries,
        "progress_hooks": [hook],
        "noplaylist": True,
        "ratelimit": options.rate_limit or None,
        "ignoreerrors": False,
        "js_runtimes": {},
    }
    for runtime in ("deno", "node"):
        if shutil.which(runtime):
            result["js_runtimes"][runtime] = {"path": shutil.which(runtime)}
            break
    if options.cookie_file:
        result["cookiefile"] = str(Path(options.cookie_file).expanduser())
    elif options.cookie_browser:
        result["cookiesfrombrowser"] = (options.cookie_browser,)
    return result


class Downloader:
    def __init__(self, options: Options, cancel, emit):
        self.options = options.validate()
        self.cancel = cancel
        self.emit = emit

    def budget(self, path, bytes_used=0):
        self.cancel.check()
        if bytes_used > self.options.max_bytes:
            raise ValueError("Download exceeded the configured size budget.")
        if shutil.disk_usage(path).free < self.options.min_free_bytes:
            raise OSError("Free space reached the configured reserve. Free space or change the destination.")

    def download(self, job_id, candidate: Candidate, revision=0):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", job_id):
            raise ValueError("Invalid job identifier.")
        for tool in ("ffmpeg", "ffprobe"):
            if not shutil.which(tool):
                raise RuntimeError(f"{tool} is missing. Install FFmpeg and run Diagnostics.")
        root = Path(self.options.destination)
        root.mkdir(parents=True, exist_ok=True)
        stage = root / ".videobot-staging" / job_id
        work = stage / (f"work-{revision}" if revision else "work")
        work.mkdir(parents=True, exist_ok=True)
        self.budget(root)
        final = root / ("VideoBot-" + job_id + (f"-r{revision}" if revision else ""))
        # A previous process may have finalized before its queue commit. Recover only our exact manifest.
        if final.exists():
            manifest_path = final / "manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("job_id") == job_id and self._verify_bundle(final, manifest):
                    return str(final)
            raise FileExistsError("Output folder already exists and was not verified. Existing files were preserved.")
        self.emit("phase", phase="downloading", job_id=job_id)
        info = {}
        self._direct_source = candidate.direct
        if candidate.direct:
            media = self._direct(candidate, work)
        else:
            media, info = self._ytdlp(candidate, work)
        self.cancel.check()
        self.emit("phase", phase="validating", job_id=job_id)
        probe = media_probe(media, self.cancel, audio_only=self.options.audio_only)
        # Direct inputs also obey hard ceilings; never silently exceed selected height.
        height = max((s.get("height", 0) for s in probe["streams"]), default=0)
        if not self.options.audio_only and self.options.quality.isdigit() and height > int(self.options.quality):
            raise ValueError(f"Video is {height}p, above the {self.options.quality}p ceiling. Choose another quality.")
        media = self._transform(media, work)
        if candidate.direct and self.options.embed_metadata and candidate.title:
            tagged = work / ("tagged" + media.suffix)
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(media),
                    "-map",
                    "0",
                    "-c",
                    "copy",
                    "-metadata",
                    "title=" + candidate.title,
                    str(tagged),
                ],
                self.cancel,
                timeout=3600,
                guard=lambda: self.budget(work, sum(p.stat().st_size for p in work.rglob("*") if p.is_file())),
            )
            media = tagged
        if candidate.direct and (self.options.subtitles or self.options.thumbnail):
            self.emit(
                "log",
                level="warning",
                message="Direct media has no subtitle/thumbnail catalog; those sidecars are unavailable.",
            )
        probe = media_probe(media, self.cancel, audio_only=self.options.audio_only)
        self.budget(root, sum(p.stat().st_size for p in work.iterdir() if p.is_file()))
        ready = stage / "ready"
        if ready.exists():
            # This directory belongs exclusively to this job, never to a pre-existing user file.
            shutil.rmtree(ready)
        ready.mkdir()
        title = info.get("title") or candidate.title or "media"
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:100] or "media"
        if safe_title.split(".")[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10)),
        }:
            safe_title = "media-" + safe_title
        published_name = safe_title + media.suffix
        # Hard links avoid doubling large validated files on the same filesystem.
        try:
            os.link(media, ready / published_name)
        except OSError:
            # Some network/exFAT destinations do not support hard links.
            with media.open("rb") as source, (ready / published_name).open("xb") as target:
                while block := source.read(1024 * 1024):
                    self.budget(root)
                    target.write(block)
        sidecar_extensions = {".vtt", ".srt", ".ass", ".lrc", ".jpg", ".jpeg", ".png", ".webp"}
        for path in work.iterdir():
            if path.is_file() and path.suffix.lower() in sidecar_extensions:
                shutil.copy2(path, ready / path.name)
        files = []
        for path in ready.iterdir():
            files.append({"name": path.name, "bytes": path.stat().st_size, "sha256": self._hash(path)})
        source_url = redact(candidate.url)
        extractor = info.get("extractor_key") or candidate.extractor
        media_id = info.get("id") or candidate.media_id
        if str(extractor).lower() == "youtube" and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(media_id)):
            source_url = "https://www.youtube.com/watch?v=" + str(media_id)
        manifest = {
            "schema": 1,
            "job_id": job_id,
            "title": info.get("title") or candidate.title,
            "creator": info.get("uploader") or candidate.creator,
            "source_url": source_url,
            "source_query_redacted": bool(urlsplit(candidate.url).query) and source_url != candidate.url,
            "extractor": info.get("extractor_key") or candidate.extractor,
            "media_id": info.get("id") or candidate.media_id,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "rights_notes": self.options.rights_notes,
            "options": self.options.public_dict(),
            "files": files,
            "duration": probe.get("format", {}).get("duration"),
            "chapters": info.get("chapters") or [],
        }
        (ready / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.cancel.check()
        if final.exists():
            raise FileExistsError("Output appeared during finalization; it was preserved.")
        # Same filesystem: only verified finished media becomes visible in the final folder.
        os.rename(ready, final)
        shutil.rmtree(stage, ignore_errors=True)
        self.emit("progress", job_id=job_id, percent=100, phase="completed")
        return str(final)

    def _hash(self, path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                self.cancel.check()
                digest.update(block)
        return digest.hexdigest()

    def _verify_bundle(self, root, manifest):
        files = manifest.get("files", [])
        if not files:
            return False
        for item in files:
            path = root / item["name"]
            if path.parent != root or not path.is_file() or self._hash(path) != item["sha256"]:
                return False
        return True

    def _ytdlp(self, candidate, work):
        # Supervise extraction, fragment downloads and FFmpeg postprocessing alike.
        # This also makes headless CLI jobs cancellable and continuously enforces
        # disk budgets while third-party code is blocked inside a subprocess.
        with tempfile.TemporaryDirectory(prefix="videobot-transfer-") as temporary:
            root = Path(temporary)
            request = root / "request.json"
            events = root / "events.jsonl"
            data = {
                "action": "download",
                "candidate": candidate.to_dict(),
                "options": asdict(self.options),
                "work": str(work),
                "event_path": str(events),
            }
            if self.cancel.path:
                data["cancel_path"] = str(self.cancel.path)
            request.write_text(json.dumps(data), encoding="utf-8")
            request.chmod(0o600)
            command = [sys.executable, "-m", "videobot.cli", "_task", str(request)]
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--worker-task", str(request)]
            kwargs = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            with (
                events.open("w", encoding="utf-8") as output,
                events.open("r", encoding="utf-8", errors="replace") as incoming,
            ):
                process = subprocess.Popen(command, stdout=output, stderr=output, **kwargs)
                result = None
                error = None
                buffer = ""
                try:
                    while True:
                        self.cancel.check()
                        self.budget(work, sum(p.stat().st_size for p in work.rglob("*") if p.is_file()))
                        chunk = incoming.read()
                        buffer += chunk
                        lines = buffer.split("\n")
                        buffer = lines.pop()
                        for line in lines:
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                if line.strip():
                                    self.emit("log", message=redact(line))
                                continue
                            if not isinstance(event, dict):
                                continue
                            kind = event.pop("type", "log")
                            if kind == "transfer_complete":
                                result = event
                            elif kind == "error":
                                error = event.get("message", "Transfer failed")
                            else:
                                self.emit(kind, **event)
                        if process.poll() is not None and not chunk:
                            break
                        self.cancel.wait(0.05)
                    if process.returncode or not result:
                        raise RuntimeError(
                            error or f"Transfer process exited without an output (status {process.returncode})."
                        )
                    media = Path(result["path"]).resolve()
                    if not media.is_relative_to(work.resolve()) or not media.is_file():
                        raise ValueError("Transfer returned an invalid output path.")
                    return media, result["info"]
                finally:
                    if process.poll() is None:
                        terminate_process_tree(process)

    def _ytdlp_inline(self, candidate, work):
        paths = []
        opts = common_options(self.options, self.emit, self.cancel)
        last = [0.0]

        def progress(data):
            self.cancel.check()
            total_disk = sum(p.stat().st_size for p in work.rglob("*") if p.is_file())
            self.budget(work, total_disk)
            now = time.monotonic()
            if now - last[0] < 0.15 and data.get("status") != "finished":
                return
            last[0] = now
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            done = data.get("downloaded_bytes", 0)
            self.emit(
                "progress",
                percent=min(99, round(done * 100 / total, 1)) if total else None,
                downloaded_bytes=done,
                total_bytes=total,
                speed=data.get("speed"),
                eta=data.get("eta"),
                phase="downloading",
            )

        opts.update(
            {
                "format": format_selector(self.options),
                "outtmpl": str(work / "media.%(ext)s"),
                "overwrites": False,
                "continuedl": True,
                "max_filesize": self.options.max_bytes,
                "progress_hooks": [progress],
                "post_hooks": [paths.append],
                "postprocessor_hooks": [lambda _: self.cancel.check()],
                "writethumbnail": self.options.thumbnail,
                "writesubtitles": bool(self.options.subtitles),
                "writeautomaticsub": self.options.automatic_subtitles,
                "subtitleslangs": [x.strip() for x in self.options.subtitles.split(",") if x.strip()],
                "postprocessors": [],
                "http_headers": {"Referer": candidate.referer} if candidate.referer else {},
            }
        )
        if self.options.container != "native":
            opts["merge_output_format"] = self.options.container
        if self.options.embed_metadata:
            opts["postprocessors"].append({"key": "FFmpegMetadata"})
        if self.options.audio_only and not (self.options.accurate_range and self.options.segment_start is not None):
            opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.options.audio_format,
                    "preferredquality": str(self.options.audio_bitrate),
                }
            )
        if self.options.segment_start is not None and not self.options.accurate_range:
            opts["download_ranges"] = download_range_func(
                None, [(self.options.segment_start, self.options.segment_end)]
            )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(candidate.url, download=True)
        self.cancel.check()
        if not info or info.get("_type") in ("playlist", "multi_video"):
            raise ValueError("This item is a collection. Inspect it and queue individual videos first.")
        # Post hooks report exact final paths after all moves/conversions; no glob inference.
        valid = [Path(p).resolve() for p in paths if Path(p).is_file()]
        if len(valid) != 1 or not valid[0].is_relative_to(work.resolve()):
            raise ValueError("Downloader did not report one verified output path.")
        return valid[0], info

    def _direct(self, candidate, work):
        # Direct requests share only explicitly chosen credentials, scoped by the cookie jar.
        partial = work / "direct.part"
        final = work / "media.bin"
        session = requests.Session()
        if self.options.cookie_file or self.options.cookie_browser:
            from yt_dlp.cookies import load_cookies

            browser = (self.options.cookie_browser,) if self.options.cookie_browser else None
            jar = load_cookies(self.options.cookie_file or None, browser, None)
            session.cookies.update(jar)
        headers = {"User-Agent": "VideoBot/2.0", "Accept-Encoding": "identity"}
        if candidate.referer:
            # Reopen the containing page in this job to obtain fresh scoped session
            # cookies; discovery and downloading may happen in different processes.
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    context = browser.new_context()
                    if session.cookies:
                        context.add_cookies(
                            [
                                {
                                    "name": c.name,
                                    "value": c.value,
                                    "domain": c.domain,
                                    "path": c.path or "/",
                                    "secure": c.secure,
                                }
                                for c in session.cookies
                            ]
                        )
                    page = context.new_page()
                    page.goto(candidate.referer, wait_until="domcontentloaded", timeout=15000)
                    self.cancel.check()
                    headers["User-Agent"] = page.evaluate("navigator.userAgent")
                    for cookie in context.cookies():
                        session.cookies.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie["domain"],
                            path=cookie["path"],
                            secure=cookie["secure"],
                        )
                finally:
                    browser.close()
        if candidate.referer:
            headers["Referer"] = candidate.referer
        try:
            for attempt in range(self.options.retries + 1):
                self.cancel.check()
                try:
                    # Restart raw transfers: appending without a strong validator can corrupt a changed resource.
                    with session.get(candidate.url, headers=headers, stream=True, timeout=(10, 15)) as response:
                        if response.status_code in (429, 500, 502, 503, 504) and attempt < self.options.retries:
                            delay = response.headers.get("Retry-After", "")
                            seconds = min(30, 2**attempt)
                            if delay:
                                try:
                                    seconds = (
                                        max(1, float(delay))
                                        if delay.isdigit()
                                        else max(1, parsedate_to_datetime(delay).timestamp() - time.time())
                                    )
                                except (ValueError, TypeError):
                                    pass
                            if seconds > 60:
                                raise ValueError(f"Server requests a {seconds:.0f}s retry delay; retry this job later.")
                            self.cancel.wait(seconds)
                            continue
                        response.raise_for_status()
                        length = int(response.headers.get("Content-Length") or 0)
                        if length > self.options.max_bytes:
                            raise ValueError("The source exceeds the configured size budget.")
                        received = 0
                        started = time.monotonic()
                        last = 0
                        with partial.open("wb") as out:
                            for block in response.iter_content(128 * 1024):
                                self.budget(work, received + len(block))
                                out.write(block)
                                received += len(block)
                                if self.options.rate_limit:
                                    pause = received / self.options.rate_limit - (time.monotonic() - started)
                                    if pause > 0:
                                        self.cancel.wait(pause)
                                now = time.monotonic()
                                if now - last > 0.15:
                                    speed = received / max(0.01, now - started)
                                    last = now
                                    self.emit(
                                        "progress",
                                        percent=min(99, received * 100 / length) if length else None,
                                        downloaded_bytes=received,
                                        total_bytes=length or None,
                                        speed=speed,
                                        eta=(length - received) / speed if length and speed else None,
                                        phase="downloading",
                                    )
                        if length and received != length:
                            raise requests.ConnectionError("Incomplete response body.")
                    probe = media_probe(partial, self.cancel, audio_only=self.options.audio_only)
                    formats = probe.get("format", {}).get("format_name", "")
                    ext = (
                        "mov"
                        if probe.get("format", {}).get("tags", {}).get("major_brand", "").strip() == "qt"
                        else "m4a"
                        if "mp4" in formats and not any(s.get("codec_type") == "video" for s in probe["streams"])
                        else "mp4"
                        if "mp4" in formats
                        else "webm"
                        if "webm" in formats and urlsplit(candidate.url).path.lower().endswith(".webm")
                        else "mkv"
                        if "matroska" in formats
                        else "mov"
                        if "mov" in formats
                        else "media"
                    )
                    if ext == "media":
                        aliases = {
                            "wav": "wav",
                            "mp3": "mp3",
                            "flac": "flac",
                            "ogg": "ogg",
                            "avi": "avi",
                            "mpeg": "mpeg",
                            "mpegts": "ts",
                            "flv": "flv",
                            "asf": "wmv",
                            "aac": "aac",
                        }
                        ext = next((aliases[name] for name in formats.split(",") if name in aliases), "mkv")
                    final = work / ("media." + ext)
                    os.replace(partial, final)  # job-owned staging only
                    return final
                except (requests.RequestException, OSError) as exc:
                    if attempt >= self.options.retries:
                        raise
                    self.emit("log", message=f"Retrying direct transfer: {redact(exc)}")
                    self.cancel.wait(min(30, 2**attempt))
            raise RuntimeError("Direct download exhausted its retry budget.")
        finally:
            session.close()

    def _transform(self, media, work):
        def guard():
            self.budget(work, sum(p.stat().st_size for p in work.rglob("*") if p.is_file()))

        # yt-dlp already applies ranges; direct transfers need the same contract.
        if (self._direct_source or self.options.accurate_range) and self.options.segment_start is not None:
            precise = self.options.accurate_range
            target = work / ("segment.mp4" if precise and not self.options.audio_only else "segment" + media.suffix)
            codec = (
                ["-vn", "-c:a", "pcm_s16le"]
                if self.options.audio_only
                else [
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                ]
            )
            if precise and self.options.audio_only:
                target = work / "segment.wav"
            command = [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                str(self.options.segment_start),
                "-i",
                str(media),
                "-t",
                str(self.options.segment_end - self.options.segment_start),
            ]
            command += codec if precise else ["-map", "0", "-c", "copy"]
            run_checked(command + [str(target)], self.cancel, timeout=7200, guard=guard)
            media = target
        if self.options.audio_only and (media.suffix != "." + self.options.audio_format or self._direct_source):
            target = work / ("audio." + self.options.audio_format)
            codecs = {"mp3": "libmp3lame", "m4a": "aac", "flac": "flac", "wav": "pcm_s16le", "opus": "libopus"}
            command = [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(media),
                "-vn",
                "-c:a",
                codecs[self.options.audio_format],
            ]
            if self.options.audio_format in ("mp3", "m4a", "opus"):
                command += ["-b:a", f"{self.options.audio_bitrate}k"]
            run_checked(command + [str(target)], self.cancel, timeout=3600, guard=guard)
            return target
        if self.options.editing_compatible:
            target = work / "editing.mp4"
            command = [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(media),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(target),
            ]
            self.emit("phase", phase="transcoding")
            run_checked(command, self.cancel, timeout=7200, guard=guard)
            return target
        if (
            self.options.container != "native"
            and not self.options.audio_only
            and media.suffix != "." + self.options.container
        ):
            target = work / ("output." + self.options.container)
            run_checked(
                ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(media), "-map", "0", "-c", "copy", str(target)],
                self.cancel,
                timeout=3600,
                guard=guard,
            )
            return target
        return media
