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


def output_identity(candidate, options):
    source = (
        f"{candidate.extractor}:{candidate.media_id}" if candidate.extractor and candidate.media_id else candidate.url
    )
    keys = (
        "destination",
        "quality",
        "container",
        "audio_only",
        "audio_format",
        "audio_bitrate",
        "subtitles",
        "automatic_subtitles",
        "thumbnail",
        "embed_metadata",
        "editing_compatible",
        "segment_start",
        "segment_end",
        "accurate_range",
        "project",
    )
    return hashlib.sha256(
        json.dumps([source, {k: options.public_dict()[k] for k in keys}], sort_keys=True).encode()
    ).hexdigest()


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "queue.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Restrict the database before SQLite creates WAL/SHM from its mode.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        if os.name != "nt":
            self.path.chmod(0o600)
            for suffix in ("-wal", "-shm"):
                auxiliary = Path(str(self.path) + suffix)
                if auxiliary.exists():
                    auxiliary.chmod(0o600)
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
        CREATE TABLE IF NOT EXISTS transcripts (
            job_id TEXT PRIMARY KEY, data TEXT NOT NULL, folder TEXT NOT NULL,
            model TEXT NOT NULL, language TEXT NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transcript_segments (
            job_id TEXT NOT NULL, ordinal INTEGER NOT NULL, start REAL NOT NULL,
            end REAL NOT NULL, text TEXT NOT NULL, PRIMARY KEY(job_id,ordinal)
        );
        """)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}
            if "process_created" not in columns:
                self.db.execute("ALTER TABLE jobs ADD COLUMN process_created REAL DEFAULT 0")
            for name, declaration in {
                "priority": "INTEGER DEFAULT 0",
                "not_before": "REAL DEFAULT 0",
                "removed": "INTEGER DEFAULT 0",
                "revision": "INTEGER DEFAULT 0",
            }.items():
                if name not in columns:
                    self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def close(self):
        self.db.close()

    def add(self, candidate: Candidate, options: Options):
        options.validate()
        candidate.url = normalize_url(candidate.url)
        identity = output_identity(candidate, options)
        identities = [identity]
        # Recognize 2.0 identities without scanning or rewriting the entire library.
        defaults = Options()
        added_keys = ("audio_format", "audio_bitrate", "accurate_range", "project")
        if all(getattr(options, k) == getattr(defaults, k) for k in added_keys):
            source = (
                f"{candidate.extractor}:{candidate.media_id}"
                if candidate.extractor and candidate.media_id
                else candidate.url
            )
            old_keys = (
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
            identities.append(
                hashlib.sha256(
                    json.dumps([source, {k: options.public_dict()[k] for k in old_keys}], sort_keys=True).encode()
                ).hexdigest()
            )
        found = self.db.execute(
            "SELECT id,removed FROM jobs WHERE identity IN (" + ",".join("?" for _ in identities) + ")", identities
        ).fetchone()
        if found:
            if found["removed"]:
                self.restore([found["id"]])
            return found["id"], False
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

    def rows(self, include_removed=False):
        where = "" if include_removed else " WHERE removed=0"
        return [
            self._decode(r) for r in self.db.execute("SELECT * FROM jobs" + where + " ORDER BY priority DESC, created")
        ]

    def edit(self, job_id, options):
        """Explicitly update an idle job; invalidate partials only when output policy changes."""
        options.validate()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM jobs WHERE id=? AND removed=0", (job_id,)).fetchone()
            if not row or row["status"] not in ("queued", "failed", "cancelled"):
                raise ValueError("Only queued, failed or cancelled jobs can be edited.")
            job = self._decode(row)
            candidate = Candidate(**job["candidate"])
            identity = output_identity(candidate, options)
            changed = identity != output_identity(candidate, Options(**job["options"]))
            try:
                self.db.execute(
                    "UPDATE jobs SET options=?,identity=?,revision=revision+?,updated=? WHERE id=?",
                    (json.dumps(options.public_dict()), identity, int(changed), time.time(), job_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Another job already uses this source and output policy.") from exc

    def organize(self, ids, priority=None, not_before=None):
        if priority is not None and not -100 <= priority <= 100:
            raise ValueError("Priority must be between -100 and 100.")
        if not_before is not None and not 0 <= not_before < 32503680000:
            raise ValueError("Invalid scheduled time.")
        with self.db:
            for job_id in ids:
                if priority is not None:
                    self.db.execute(
                        "UPDATE jobs SET priority=?,updated=? WHERE id=? AND status!='running'",
                        (priority, time.time(), job_id),
                    )
                if not_before is not None:
                    self.db.execute(
                        "UPDATE jobs SET not_before=?,updated=? WHERE id=? AND status IN ('queued','failed','cancelled')",
                        (not_before, time.time(), job_id),
                    )

    def backup(self, target):
        target = Path(target).expanduser().resolve()
        if target == self.path.resolve() or target.exists():
            raise ValueError("Choose a new backup filename.")
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        destination = sqlite3.connect(target)
        try:
            self.db.backup(destination)
        finally:
            destination.close()
        return str(target)

    @staticmethod
    def _decode(row):
        row = dict(row)
        row["candidate"] = json.loads(row["candidate"])
        row["options"] = json.loads(row["options"])
        return row

    def claim(self, owner, ids=None):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            sql = "SELECT * FROM jobs WHERE status='queued' AND removed=0 AND not_before<=?"
            args = [time.time()]
            if ids is not None:
                if not ids:
                    return None
                sql += " AND id IN (" + ",".join("?" for _ in ids) + ")"
                args.extend(ids)
            row = self.db.execute(sql + " ORDER BY priority DESC, created LIMIT 1", args).fetchone()
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
        for row in self.db.execute("SELECT id,owner,pid,process_created FROM jobs WHERE status='running'").fetchall():
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
                    result = self.db.execute(
                        "UPDATE jobs SET status='cancelled',pid=0,error='Interrupted by shutdown; retry to resume.',updated=? "
                        "WHERE id=? AND status='running' AND owner=? AND pid=? AND process_created=?",
                        (time.time(), row["id"], row["owner"], row["pid"], row["process_created"]),
                    )
                count += result.rowcount
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
                self.db.execute(
                    "UPDATE jobs SET removed=1,updated=? WHERE id=? AND status!='running'", (time.time(), job_id)
                )

    def restore(self, ids):
        with self.db:
            for job_id in ids:
                self.db.execute("UPDATE jobs SET removed=0,updated=? WHERE id=?", (time.time(), job_id))

    def setting(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def transcript(self, job_id):
        row = self.db.execute("SELECT data,folder FROM transcripts WHERE job_id=?", (job_id,)).fetchone()
        return {**json.loads(row[0]), "folder": row[1]} if row else None

    def search_transcripts(self, query, job_id=None, limit=200):
        if not query.strip():
            return []
        self.db.create_function("casefold", 1, str.casefold)
        sql = "SELECT s.*,j.candidate,j.output FROM transcript_segments s JOIN jobs j ON j.id=s.job_id WHERE j.removed=0 AND j.status='completed' AND instr(casefold(s.text),?)>0"
        args = [query.strip().casefold()]
        if job_id:
            sql += " AND s.job_id=?"
            args.append(job_id)
        sql += " ORDER BY j.created,s.ordinal LIMIT ?"
        args.append(max(1, min(1000, limit)))
        return [
            {**{k: r[k] for k in r.keys() if k != "candidate"}, "title": json.loads(r["candidate"])["title"]}
            for r in self.db.execute(sql, args)
        ]
