"""Durable job states. SQLite transactions prevent two runners claiming one job."""

import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid

import psutil
from pathlib import Path

from .models import Candidate, Options, normalize_url


def data_dir() -> Path:
    if os.environ.get("VIDEOBOT_HOME"):
        return Path(os.environ["VIDEOBOT_HOME"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VideoBot"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VideoBot"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "videobot"


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "queue.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL,
            candidate TEXT NOT NULL, options TEXT NOT NULL, status TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL, attempts INTEGER DEFAULT 0,
            error TEXT DEFAULT '', output TEXT DEFAULT '', owner TEXT DEFAULT '', pid INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}
        if "process_created" not in columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN process_created REAL DEFAULT 0")
            self.db.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def close(self):
        self.db.close()

    def add(self, candidate: Candidate, options: Options):
        options.validate()
        candidate.url = normalize_url(candidate.url)
        source = (
            f"{candidate.extractor}:{candidate.media_id}"
            if candidate.extractor and candidate.media_id
            else candidate.url
        )
        output_keys = (
            "destination",
            "quality",
            "container",
            "audio_only",
            "subtitles",
            "automatic_subtitles",
            "thumbnail",
            "embed_metadata",
            "editing_compatible",
            "segment_start",
            "segment_end",
        )
        output_options = {key: options.public_dict()[key] for key in output_keys}
        identity = hashlib.sha256(json.dumps([source, output_options], sort_keys=True).encode()).hexdigest()
        job_id = uuid.uuid4().hex
        now = time.time()
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO jobs(id,identity,candidate,options,status,created,updated) VALUES(?,?,?,?,?,?,?)",
                (
                    job_id,
                    identity,
                    json.dumps(candidate.to_dict()),
                    json.dumps(options.public_dict()),
                    "queued",
                    now,
                    now,
                ),
            )
        row = self.db.execute("SELECT id FROM jobs WHERE identity=?", (identity,)).fetchone()
        return row["id"], row["id"] == job_id

    def rows(self):
        return [self._decode(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY created")]

    @staticmethod
    def _decode(row):
        row = dict(row)
        row["candidate"] = json.loads(row["candidate"])
        row["options"] = json.loads(row["options"])
        return row

    def claim(self, owner, ids=None):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            sql = "SELECT * FROM jobs WHERE status='queued'"
            args = []
            if ids is not None:
                if not ids:
                    return None
                sql += " AND id IN (" + ",".join("?" for _ in ids) + ")"
                args.extend(ids)
            row = self.db.execute(sql + " ORDER BY created LIMIT 1", args).fetchone()
            if row is None:
                return None
            self.db.execute(
                "UPDATE jobs SET status='running',owner=?,pid=?,process_created=?,attempts=attempts+1,updated=?,error='' WHERE id=?",
                (owner, os.getpid(), psutil.Process().create_time(), time.time(), row["id"]),
            )
        return self._decode(self.db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def finish(self, job_id, owner, status, error="", output=""):
        if status not in ("completed", "failed", "cancelled", "skipped"):
            raise ValueError("Invalid terminal status")
        with self.db:
            self.db.execute(
                "UPDATE jobs SET status=?,error=?,output=?,updated=?,pid=0 WHERE id=? AND owner=? AND status='running'",
                (status, error, output, time.time(), job_id, owner),
            )

    def interrupt_owner(self, owner):
        with self.db:
            self.db.execute(
                "UPDATE jobs SET status='cancelled',error='Stopped; retry to resume retained partials.',pid=0,updated=? WHERE owner=? AND status='running'",
                (time.time(), owner),
            )

    def recover(self):
        """Only recover jobs whose owning OS process demonstrably no longer exists."""
        count = 0
        for row in self.db.execute("SELECT id,pid,process_created FROM jobs WHERE status='running'").fetchall():
            try:
                if not row["pid"]:
                    raise ProcessLookupError()
                process = psutil.Process(row["pid"])
                if row["process_created"] and abs(process.create_time() - row["process_created"]) > 0.01:
                    raise ProcessLookupError()
                if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                    raise ProcessLookupError()
            except (ProcessLookupError, psutil.NoSuchProcess):
                with self.db:
                    self.db.execute(
                        "UPDATE jobs SET status='cancelled',pid=0,error='Interrupted by shutdown; retry to resume.',updated=? WHERE id=? AND status='running'",
                        (time.time(), row["id"]),
                    )
                count += 1
            except (PermissionError, psutil.AccessDenied):
                pass
        return count

    def retry(self, ids):
        with self.db:
            for job_id in ids:
                self.db.execute(
                    "UPDATE jobs SET status='queued',error='',updated=? WHERE id=? AND status IN ('failed','cancelled')",
                    (time.time(), job_id),
                )

    def remove(self, ids):
        # Removes records only. Never removes downloaded user files.
        with self.db:
            for job_id in ids:
                self.db.execute("DELETE FROM jobs WHERE id=? AND status!='running'", (job_id,))

    def setting(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))
