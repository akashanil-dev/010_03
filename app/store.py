"""Shipment storage in SQLite: the single source of truth for the web app (and, later, the worker).

WAL mode lets readers carry on while one writer commits. Each schema change is a numbered
migration, so an existing database upgrades itself on start-up. SQLite is enough while
everything runs on one machine; swap this module for Postgres if workers ever run on several.
"""

import json
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from . import report as R
from .schemas import OWNERS

DB = Path(__file__).resolve().parent.parent / "data" / "tally.db"
RETENTION_DAYS = 7
FILE_COLUMNS = ("filename", "path", "state", "started")   # everything else about a file lives in `meta`


@contextmanager
def _db(immediate: bool = False):
    """One connection per call, committed on success and always closed."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=15, isolation_level=None)   # autocommit; transactions are explicit
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        c.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield c
        c.execute("COMMIT")
    except BaseException:
        if c.in_transaction:
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


# ---------- schema ----------

def _v1(c: sqlite3.Connection) -> None:
    """Shipments, files, reviews and audit in their own tables (was: one JSON blob per shipment)."""
    old = {r["name"] for r in c.execute("PRAGMA table_info(shipments)")}
    if "data" in old:
        c.execute("ALTER TABLE shipments RENAME TO shipments_v0")
    c.execute("""CREATE TABLE shipments (
        id TEXT PRIMARY KEY, workspace_id TEXT, created_by TEXT,
        created REAL NOT NULL, expires_at REAL, state TEXT NOT NULL, label TEXT,
        verdict TEXT, errors INTEGER NOT NULL DEFAULT 0, warnings INTEGER NOT NULL DEFAULT 0,
        report TEXT, final TEXT)""")
    c.execute("CREATE INDEX shipments_by_workspace ON shipments (workspace_id, created)")
    c.execute("""CREATE TABLE files (
        shipment_id TEXT NOT NULL REFERENCES shipments (id) ON DELETE CASCADE, idx INTEGER NOT NULL,
        filename TEXT NOT NULL, path TEXT NOT NULL, state TEXT NOT NULL, started REAL,
        meta TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (shipment_id, idx))""")
    c.execute("""CREATE TABLE reviews (
        shipment_id TEXT NOT NULL REFERENCES shipments (id) ON DELETE CASCADE, check_id TEXT NOT NULL,
        decision TEXT NOT NULL, note TEXT NOT NULL, reviewer TEXT NOT NULL, at TEXT NOT NULL,
        PRIMARY KEY (shipment_id, check_id))""")
    c.execute("""CREATE TABLE audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shipment_id TEXT NOT NULL REFERENCES shipments (id) ON DELETE CASCADE, check_id TEXT NOT NULL,
        decision TEXT NOT NULL, note TEXT NOT NULL, reviewer TEXT NOT NULL, at TEXT NOT NULL)""")
    c.execute("CREATE INDEX audit_by_shipment ON audit (shipment_id)")
    if "data" in old:
        for (data,) in c.execute("SELECT data FROM shipments_v0").fetchall():
            _import_v0(c, json.loads(data))
        c.execute("DROP TABLE shipments_v0")


def _import_v0(c: sqlite3.Connection, s: dict) -> None:
    rep = s.get("report")
    final = s.get("final") or (R.final_verdict(rep, s.get("reviews", {})) if rep else None)
    state = s["state"] if s["state"] == "done" else "interrupted"
    _insert_shipment(c, s["id"], s["created"], s.get("files", []), state)
    if rep:
        _write_result(c, s["id"], rep, s.get("label") or s["id"], final)
    for e in s.get("reviews", {}).values():
        c.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?)", (s["id"], *_review_row(e)))
    for e in s.get("audit", []):
        c.execute("INSERT INTO audit (shipment_id, check_id, decision, note, reviewer, at) VALUES (?,?,?,?,?,?)",
                  (s["id"], *_review_row(e)))


MIGRATIONS = [_v1]


def init() -> None:
    """Create or upgrade the database. Safe to call on every start."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=15, isolation_level=None)
    try:
        c.execute("PRAGMA journal_mode = WAL")
    finally:
        c.close()
    with _db(immediate=True) as c:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        for n, step in enumerate(MIGRATIONS[version:], version + 1):
            step(c)
            c.execute(f"PRAGMA user_version = {n}")


# ---------- rows <-> dicts ----------

def _review_row(e: dict) -> tuple:
    return e["check_id"], e["decision"], e.get("note", ""), e.get("reviewer", ""), e.get("at", "")


def _file_dict(row: sqlite3.Row) -> dict:
    out = {k: row[k] for k in FILE_COLUMNS if row[k] is not None}
    return out | json.loads(row["meta"])


def _insert_files(c: sqlite3.Connection, sid: str, files: list[dict]) -> None:
    for idx, f in enumerate(files):
        meta = {k: v for k, v in f.items() if k not in FILE_COLUMNS}
        c.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)",
                  (sid, idx, f["filename"], f["path"], f.get("state", "queued"), f.get("started"), json.dumps(meta)))


def _insert_shipment(c: sqlite3.Connection, sid: str, created: float, files: list[dict], state: str) -> None:
    c.execute("INSERT INTO shipments (id, created, expires_at, state) VALUES (?,?,?,?)",
              (sid, created, created + RETENTION_DAYS * 86400, state))
    _insert_files(c, sid, files)


def _write_result(c: sqlite3.Connection, sid: str, rep: dict, label: str, final: dict) -> None:
    counts = rep.get("counts", {})
    c.execute("""UPDATE shipments SET state = 'done', label = ?, report = ?, final = ?, verdict = ?,
                 errors = ?, warnings = ? WHERE id = ?""",
              (label, json.dumps(rep), json.dumps(final), (final or {}).get("verdict") or rep.get("verdict"),
               counts.get("errors", 0), counts.get("warnings", 0), sid))


# ---------- shipments ----------

def create(sid: str, files: list[dict], created: float | None = None) -> None:
    with _db() as c:
        _insert_shipment(c, sid, created or time.time(), files, "processing")


def get(sid: str) -> dict | None:
    """The whole shipment: files, report, reviews (by check id) and the audit trail."""
    with _db() as c:
        row = c.execute("SELECT * FROM shipments WHERE id = ?", (sid,)).fetchone()
        if not row:
            return None
        files = c.execute("SELECT * FROM files WHERE shipment_id = ? ORDER BY idx", (sid,)).fetchall()
        reviews = c.execute("SELECT * FROM reviews WHERE shipment_id = ?", (sid,)).fetchall()
        audit = c.execute("SELECT * FROM audit WHERE shipment_id = ? ORDER BY id", (sid,)).fetchall()
    entry = lambda r: {k: r[k] for k in ("check_id", "decision", "note", "reviewer", "at")}
    return {"id": row["id"], "created": row["created"], "expires_at": row["expires_at"], "state": row["state"],
            "label": row["label"], "files": [_file_dict(f) for f in files],
            "report": json.loads(row["report"]) if row["report"] else None,
            "final": json.loads(row["final"]) if row["final"] else None,
            "reviews": {r["check_id"]: entry(r) for r in reviews}, "audit": [entry(a) for a in audit]}


def set_files(sid: str, files: list[dict]) -> None:
    """Replace the file list (a merged PDF becomes one entry per document)."""
    with _db() as c:
        c.execute("DELETE FROM files WHERE shipment_id = ?", (sid,))
        _insert_files(c, sid, files)


def update_file(sid: str, idx: int, **changes) -> None:
    with _db(immediate=True) as c:
        row = c.execute("SELECT * FROM files WHERE shipment_id = ? AND idx = ?", (sid, idx)).fetchone()
        if not row:
            return
        cols = {k: v for k, v in changes.items() if k in FILE_COLUMNS}
        meta = json.loads(row["meta"]) | {k: v for k, v in changes.items() if k not in FILE_COLUMNS}
        sets = ", ".join(f"{k} = ?" for k in cols) + (", " if cols else "") + "meta = ?"
        c.execute(f"UPDATE files SET {sets} WHERE shipment_id = ? AND idx = ?",
                  (*cols.values(), json.dumps(meta), sid, idx))


def finish(sid: str, rep: dict, label: str) -> None:
    with _db() as c:
        _write_result(c, sid, rep, label, R.final_verdict(rep, {}))


def add_review(sid: str, entry: dict) -> dict:
    """Record a decision and recompute the final verdict in one transaction, so two reviewers never race."""
    with _db(immediate=True) as c:
        c.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?)", (sid, *_review_row(entry)))
        c.execute("INSERT INTO audit (shipment_id, check_id, decision, note, reviewer, at) VALUES (?,?,?,?,?,?)",
                  (sid, *_review_row(entry)))
        rep = json.loads(c.execute("SELECT report FROM shipments WHERE id = ?", (sid,)).fetchone()["report"])
        reviews = {r["check_id"]: dict(r) for r in c.execute("SELECT * FROM reviews WHERE shipment_id = ?", (sid,))}
        final = R.final_verdict(rep, reviews)
        c.execute("UPDATE shipments SET final = ?, verdict = ? WHERE id = ?", (json.dumps(final), final["verdict"], sid))
    return final


def mark_interrupted() -> None:
    """Checks that were running when the server stopped cannot resume (until the job queue exists)."""
    with _db() as c:
        c.execute("UPDATE shipments SET state = 'interrupted' WHERE state NOT IN ('done', 'interrupted')")


def delete(sid: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM shipments WHERE id = ?", (sid,))


def finished() -> list[dict]:
    """Checked shipments with what the dashboard needs, without loading every file and audit entry."""
    with _db() as c:
        rows = c.execute("""SELECT s.id, s.created, s.label, s.report, s.final,
                                   (SELECT COUNT(*) FROM reviews r WHERE r.shipment_id = s.id) AS reviewed
                            FROM shipments s WHERE s.report IS NOT NULL""").fetchall()
    return [{"id": r["id"], "created": r["created"], "label": r["label"], "report": json.loads(r["report"]),
             "final": json.loads(r["final"]) if r["final"] else None, "reviewed": r["reviewed"]} for r in rows]


# ---------- dashboard ----------

def blamed_documents(check: dict) -> list[str]:
    """Document types a flag points at (the likely outliers)."""
    types = [v["doc_type"] for v in check.get("values", []) if v.get("outlier")]
    return sorted(set(types))


def dashboard(shipments: list[dict]) -> dict:
    done = [s for s in shipments if s.get("report")]
    def verdict(s):   # after human review, when there has been one
        return (s.get("final") or {}).get("verdict") or s["report"]["verdict"]
    verdicts = Counter(verdict(s) for s in done)
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
                    "verdict": verdict(s), "counts": s["report"]["counts"],
                    "overridden": (s.get("final") or {}).get("overridden_errors", 0),
                    "documents": len(s["report"]["documents"]),
                    "reviewed": s.get("reviewed", 0)} for s in recent],
    }
