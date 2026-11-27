"""Explicit maintenance, scoped to known jobs and never to completed media."""

import os
import re
import shutil
import sqlite3
from pathlib import Path

from .storage import Store


def staging(store, ids, delete=False):
    result = []
    # Hold the writer lock through deletion so a runner cannot claim an idle job.
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        for job in store.rows(include_removed=True):
            if job["id"] not in ids:
                continue
            if job["status"] == "running":
                raise ValueError("Stop the running job before cleaning its partial files.")
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", job["id"]):
                raise ValueError("Invalid job identifier.")
            root = Path(job["options"]["destination"])
            parent = root / ".videobot-staging"
            folder = parent / job["id"]
            if parent.is_symlink() or folder.is_symlink():
                raise ValueError("Refusing to clean a symlinked staging folder.")
            if not folder.exists():
                continue
            total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and not p.is_symlink())
            result.append({"id": job["id"], "path": str(folder), "bytes": total})
            if delete:
                shutil.rmtree(folder)
    return result


def restore_backup(source, target):
    """Restore to a NEW database; never overwrite a running application's queue."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file() or source == target or target.exists():
        raise ValueError("Choose an existing backup and a new destination database.")
    incoming = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    try:
        if incoming.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed.")
        names = {r[0] for r in incoming.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"jobs", "settings"} <= names:
            raise ValueError("This is not a VideoBot backup.")
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        output = sqlite3.connect(target)
        try:
            incoming.backup(output)
        finally:
            output.close()
    finally:
        incoming.close()
    restored = Store(target)
    try:
        with restored.db:
            restored.db.execute(
                "UPDATE jobs SET status='cancelled',pid=0,owner='',error='Restored backup: retry to resume.' WHERE status='running'"
            )
    finally:
        restored.close()
    return str(target)
