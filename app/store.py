"""Persistent shipment history in SQLite (replaceable with Postgres in production)."""

import json
import sqlite3
import threading
from collections import Counter
from pathlib import Path

from .schemas import OWNERS

DB = Path(__file__).resolve().parent.parent / "data" / "tally.db"
_lock = threading.Lock()


def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS shipments (
        id TEXT PRIMARY KEY, created REAL, label TEXT, state TEXT, verdict TEXT,
        errors INTEGER, warnings INTEGER, data TEXT)""")
    return c


def save(s: dict) -> None:
    r = s.get("report") or {}
    counts = r.get("counts", {})
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO shipments VALUES (?,?,?,?,?,?,?,?)",
                  (s["id"], s["created"], s.get("label", ""), s["state"], r.get("verdict"),
                   counts.get("errors", 0), counts.get("warnings", 0), json.dumps(s)))


def load_all() -> dict[str, dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT data FROM shipments").fetchall()
    out = {}
    for (data,) in rows:
        s = json.loads(data)
        if s["state"] != "done":           # interrupted by a restart
            s["state"] = "interrupted"
        out[s["id"]] = s
    return out


def delete(sid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM shipments WHERE id = ?", (sid,))


def blamed_documents(check: dict) -> list[str]:
    """Document types a flag points at (the likely outliers)."""
    types = [v["doc_type"] for v in check.get("values", []) if v.get("outlier")]
    return sorted(set(types))


def dashboard(shipments: list[dict]) -> dict:
    done = [s for s in shipments if s.get("report")]
    verdicts = Counter(s["report"]["verdict"] for s in done)
    issue_types, by_doc = Counter(), Counter()
    flags_total = 0
    for s in done:
        for c in s["report"]["checks"]:
            if c["status"] not in ("error", "warning"):
                continue
            flags_total += 1
            issue_types[c["title"]] += 1
            for t in blamed_documents(c):
                by_doc[t] += 1
    recent = sorted(done, key=lambda s: s["created"], reverse=True)[:20]
    return {
        "shipments": len(done),
        "verdicts": {"ready": verdicts.get("ready", 0), "review": verdicts.get("review", 0),
                     "blocked": verdicts.get("blocked", 0)},
        "documents": sum(len(s["report"]["documents"]) for s in done),
        "flags": flags_total,
        "top_issues": issue_types.most_common(8),
        "by_document": [{"doc_type": t, "owner": OWNERS.get(t, t), "count": n} for t, n in by_doc.most_common()],
        "recent": [{"id": s["id"], "created": s["created"], "label": s.get("label") or s["id"],
                    "verdict": s["report"]["verdict"], "counts": s["report"]["counts"],
                    "documents": len(s["report"]["documents"]),
                    "reviewed": len(s.get("reviews", {}))} for s in recent],
    }
