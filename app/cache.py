"""Where reading results are cached, and how they are forgotten.

Demo shipments share one cache (synthetic documents, so the demos stay instant). Uploaded documents are
cached per workspace, so one customer's upload can never be served to, or timed by, another. Entries
are removed with their shipment and never outlive the retention period.
"""

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "cache"


def folder(workspace_id: str | None, demo: bool) -> Path:
    return ROOT if demo or not workspace_id else ROOT / "ws" / workspace_id


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:24]


def fields_key(doc_type: str, text: str) -> str:
    return hashlib.sha256(f"{doc_type}\n{text}".encode()).hexdigest()[:24]


def forget(cache_dir: Path, path: Path, cache_key: str | None = None) -> None:
    """Delete the cached reading of one uploaded file (and its extracted fields)."""
    if cache_dir == ROOT:   # the shared demo cache is kept
        return
    try:
        key = cache_key or file_hash(path)
    except OSError:
        return
    entry = cache_dir / f"{key}.json"
    try:
        doc = json.loads(entry.read_text())
        if doc.get("doc_type"):
            (cache_dir / f"fields_{fields_key(doc['doc_type'], doc['text'])}.json").unlink(missing_ok=True)
    except (OSError, ValueError, KeyError):
        pass
    entry.unlink(missing_ok=True)


def sweep(max_age: float, now: float | None = None) -> int:
    """Delete per-workspace cache entries older than max_age seconds. Returns how many."""
    now, removed = now or time.time(), 0
    for p in (ROOT / "ws").glob("*/*.json"):
        try:
            if p.stat().st_mtime < now - max_age:
                p.unlink()
                removed += 1
        except OSError:
            pass
    for d in (ROOT / "ws").glob("*"):
        try:
            d.rmdir()   # only succeeds once empty
        except OSError:
            pass
    return removed
