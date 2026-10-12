"""SQLite storage: round trips, reviews, deletion and the upgrade from the old one-blob table. Run: pytest -q"""

import json
import sqlite3

import pytest

from app import store
from app.report import build
from tests.fixtures import errors_docs


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "tally.db")
    store.init()


def files(*names):
    return [{"filename": n, "path": f"/tmp/{n}", "state": "queued"} for n in names]


def test_create_and_get_round_trip():
    store.create("s1", files("a.pdf", "b.xlsx"), created=1000.0)
    s = store.get("s1")
    assert s["state"] == "processing"
    assert [f["filename"] for f in s["files"]] == ["a.pdf", "b.xlsx"]
    assert s["expires_at"] == 1000.0 + 7 * 86400
    assert s["report"] is None and s["reviews"] == {} and s["audit"] == []
    assert store.get("missing") is None


def test_file_updates_keep_extra_details():
    store.create("s1", files("a.pdf"))
    store.update_file("s1", 0, state="reading", started=5.0)
    store.update_file("s1", 0, state="done", doc_type="packing_list", seconds=3.2)
    f = store.get("s1")["files"][0]
    assert f["state"] == "done" and f["started"] == 5.0
    assert f["doc_type"] == "packing_list" and f["seconds"] == 3.2


def test_bundle_split_replaces_file_list():
    store.create("s1", files("bundle.pdf"))
    store.set_files("s1", [{"filename": "bundle_p1.pdf", "path": "/tmp/p1", "state": "queued",
                            "bundle": "bundle.pdf", "pages": [1], "cache_key": "abc_p1"}])
    f = store.get("s1")["files"]
    assert len(f) == 1 and f[0]["bundle"] == "bundle.pdf" and f[0]["pages"] == [1]


def test_finish_and_reviews_update_the_final_verdict():
    rep = build(errors_docs())
    store.create("s1", files("a.pdf"))
    store.finish("s1", rep, "INV-1 · Buyer")
    s = store.get("s1")
    assert s["state"] == "done" and s["label"] == "INV-1 · Buyer" and s["final"]["verdict"] == "blocked"

    errors = [c["id"] for c in rep["checks"] if c["status"] == "error"]
    for cid in errors:
        final = store.add_review("s1", {"check_id": cid, "decision": "overridden", "note": "ok", "reviewer": "A",
                                        "at": "2026-10-12T10:00:00"})
    assert final["open_errors"] == 0
    s = store.get("s1")
    assert set(s["reviews"]) == set(errors) and len(s["audit"]) == len(errors)

    # Changing a decision replaces the review but keeps both entries in the audit trail
    store.add_review("s1", {"check_id": errors[0], "decision": "confirmed", "note": "", "reviewer": "B", "at": "x"})
    s = store.get("s1")
    assert s["reviews"][errors[0]]["decision"] == "confirmed" and len(s["audit"]) == len(errors) + 1
    assert s["final"]["verdict"] == "blocked"
    assert store.dashboard(store.finished())["recent"][0]["reviewed"] == len(errors)


def test_delete_removes_files_reviews_and_audit():
    store.create("s1", files("a.pdf"))
    store.finish("s1", build(errors_docs()), "x")
    cid = next(c["id"] for c in store.get("s1")["report"]["checks"] if c["status"] == "error")
    store.add_review("s1", {"check_id": cid, "decision": "confirmed", "note": "", "reviewer": "A", "at": "x"})
    store.delete("s1")
    assert store.get("s1") is None
    with sqlite3.connect(store.DB) as c:
        assert [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("files", "reviews", "audit")] == [0, 0, 0]


def test_unfinished_checks_are_marked_interrupted():
    store.create("s1", files("a.pdf"))
    store.create("s2", files("b.pdf"))
    store.finish("s2", build(errors_docs()), "x")
    store.mark_interrupted()
    assert store.get("s1")["state"] == "interrupted" and store.get("s2")["state"] == "done"


def test_upgrade_from_single_blob_table(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "old.db")
    rep = build(errors_docs())
    cid = next(c["id"] for c in rep["checks"] if c["status"] == "error")
    review = {"check_id": cid, "decision": "overridden", "note": "fine", "reviewer": "A", "at": "x"}
    old = {"id": "old1", "created": 50.0, "state": "done", "label": "L", "report": rep,
           "files": files("a.pdf"), "reviews": {cid: review}, "audit": [review]}
    with sqlite3.connect(store.DB) as c:
        c.execute("""CREATE TABLE shipments (id TEXT PRIMARY KEY, created REAL, label TEXT, state TEXT,
                     verdict TEXT, errors INTEGER, warnings INTEGER, data TEXT)""")
        c.execute("INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?)",
                  ("old1", 50.0, "L", "done", "blocked", 1, 0, json.dumps(old)))
        c.execute("INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?)",
                  ("old2", 60.0, "", "processing", None, 0, 0,
                   json.dumps({"id": "old2", "created": 60.0, "state": "processing", "files": files("b.pdf")})))
    store.init()
    store.init()   # a second start is a no-op
    s = store.get("old1")
    assert s["label"] == "L" and s["reviews"][cid]["note"] == "fine" and len(s["audit"]) == 1
    assert s["final"]["overridden_errors"] == 1
    assert store.get("old2")["state"] == "interrupted"
