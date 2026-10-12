"""Progress and time estimates, learned from how long each stage takes on this machine.

Every document goes through two timed stages: conversion (Docling, per page; OCR pages are much slower)
and extraction (one Granite call per document; while it streams, the characters produced so far show
how far along it is). Running averages are kept in the `timings` table and updated after each document.
"""

import math
import time
from pathlib import Path

from .formats import IMAGE_TYPES, OFFICE_TYPES
from .store import _db

DEFAULTS = {
    "page:text": 3.0, "page:ocr": 12.0, "page:office": 3.0,   # conversion seconds per page
    "split:page": 1.5,                                         # bundle splitting seconds per page
    "extract": 60.0,                                           # seconds per extraction (any document type)
    "chars": 700.0,                                            # characters the model writes per document
}
ALPHA = 0.2   # weight of the newest measurement in the running average
FINISHED = ("done", "error", "skipped")


def record(key: str, value: float) -> None:
    if value <= 0:
        return
    with _db(immediate=True) as c:
        row = c.execute("SELECT value, n FROM timings WHERE key = ?", (key,)).fetchone()
        new = value if not row else row["value"] * (1 - ALPHA) + value * ALPHA
        c.execute("INSERT OR REPLACE INTO timings VALUES (?,?,?)", (key, new, (row["n"] if row else 0) + 1))


def load() -> dict:
    with _db() as c:
        return DEFAULTS | {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM timings")}


def kind(filename: str, meta: dict) -> str:
    """How a file is converted: 'ocr' (images, scans), 'office' (Excel, Word, CSV) or 'text' (digital PDF)."""
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_TYPES:
        return "ocr"
    if suffix in OFFICE_TYPES:
        return "office"
    return meta.get("kind", "text")


def documents_in(f: dict) -> int:
    """Documents a file probably holds before it is split: a long PDF is usually a bundle."""
    pages = f.get("page_count") or 1
    if f.get("bundle") or f.get("split_checked") or pages <= 2:
        return 1
    return math.ceil(pages / 2)


def expected(f: dict, t: dict) -> tuple[float, float]:
    """(conversion seconds, extraction seconds) for one file."""
    pages = f.get("page_count") or 1
    conv = pages * t[f"page:{kind(f['filename'], f)}"]
    ext = t.get(f"extract:{f.get('doc_type')}", t["extract"]) * documents_in(f)
    return conv, ext


def file_estimate(f: dict, t: dict, now: float | None = None) -> tuple[int, float]:
    """(percent done, seconds left) for one file."""
    now = now or time.time()
    if f["state"] in FINISHED:
        return 100, 0.0
    conv, ext = expected(f, t)
    total = conv + ext
    split = (f.get("page_count") or 1) * t["split:page"] if f.get("page_count", 1) > 1 and not f.get("bundle") else 0
    if f["state"] == "queued":
        return 0, total + (0 if f.get("split_checked") else split)
    elapsed = now - (f.get("stage_started") or f.get("started") or now)
    if f["state"] == "splitting":
        return 0, max(split - elapsed, 1) + total
    if f.get("stage") == "extracting":
        expect_chars = t.get(f"chars:{f.get('doc_type')}", t["chars"])
        frac = f["chars"] / expect_chars if f.get("chars") else elapsed / ext
        frac = min(frac, 0.97)
        return int(100 * (conv + frac * ext) / total), max(ext * (1 - frac), 1.0)
    frac = min(elapsed / conv, 0.95) if conv else 0.95
    return int(100 * frac * conv / total), max(conv - elapsed, conv * 0.05) + ext


def remaining(files: list[dict], t: dict, now: float | None = None) -> float:
    return sum(file_estimate(f, t, now)[1] for f in files)


def upload_estimate(files: list[dict], t: dict | None = None) -> float:
    """Expected seconds for a new check, from file types and page counts."""
    return remaining([f | {"state": "queued"} for f in files], t or load())
