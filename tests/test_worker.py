"""The worker's job runner, timeouts, cancellation, retention and estimates, with a fake reader. Run: pytest -q"""

import time
from pathlib import Path

from app import accounts, cache, config, jobs, progress, retention, store, worker
from tests.fixtures import errors_docs


class FakeReader:
    """Replies like the reader process. `script` maps a filename to 'ok', 'error', 'doc_timeout', 'job_timeout',
    'cancelled' or 'crashed'."""

    def __init__(self, script=None):
        self.script = script or {}
        self.docs = {d.filename: d for d in errors_docs()}
        self.calls = []

    def run(self, cmd, job_id, job_deadline):
        self.calls.append(cmd)
        if cmd["op"] == "split":
            return "ok", {"ok": True, "parts": None}
        outcome = self.script.get(cmd["filename"], "ok")
        if outcome == "ok":
            doc = self.docs[cmd["filename"]]
            return "ok", {"ok": True, "doc": doc.model_dump_json()}
        if outcome == "error":
            return "ok", {"ok": False, "error": "unreadable"}
        return outcome, None


def make_job(tmp_path, user_email="asha@example.com", demo=False):
    user = accounts.user_by_email(user_email) or accounts.create_user(user_email, "Asha", "correct horse 1")
    ws = accounts.current_workspace(user)
    sid = f"s{int(time.time() * 1e6)}"
    (retention.UPLOADS / sid).mkdir(parents=True)
    files = []
    for d in errors_docs():
        p = retention.UPLOADS / sid / d.filename
        p.write_bytes(b"%PDF fake " + d.filename.encode())
        files.append({"filename": d.filename, "path": str(p), "state": "queued", "page_count": 1})
    store.create(sid, files, workspace_id=ws, created_by=user["id"], demo=demo)
    jobs.enqueue(sid, user, 60, counted=not demo)
    return sid, user, jobs.claim_next()


def test_clean_run_builds_the_report(isolated):
    sid, user, job = make_job(isolated)
    reader = FakeReader()
    worker.run_job(job, reader)
    s = store.get(sid)
    assert s["state"] == "done" and s["report"]["verdict"] == "blocked"
    assert all(f["state"] == "done" for f in s["files"])
    assert jobs.for_shipment(sid)["state"] == "done"
    assert all(c["cache_dir"] == str(cache.ROOT / "ws" / s["workspace_id"]) for c in reader.calls)


def test_one_slow_document_does_not_stop_the_rest(isolated):
    sid, _, job = make_job(isolated)
    slow = errors_docs()[2].filename
    worker.run_job(job, FakeReader({slow: "doc_timeout", errors_docs()[3].filename: "crashed"}))
    s = store.get(sid)
    states = {f["filename"]: f["state"] for f in s["files"]}
    assert states[slow] == "error" and list(states.values()).count("done") == 4
    assert "longer than 5 minutes" in next(f["error"] for f in s["files"] if f["filename"] == slow)
    assert any(c["id"] == f"intake:read_failed:{slow}" for c in s["report"]["checks"])
    assert jobs.for_shipment(sid)["state"] == "done"


def test_shipment_timeout_keeps_partial_results_and_refunds(isolated):
    sid, user, job = make_job(isolated)
    third = errors_docs()[2].filename
    worker.run_job(job, FakeReader({third: "job_timeout"}))
    s = store.get(sid)
    assert [f["state"] for f in s["files"]] == ["done", "done", "skipped", "skipped", "skipped", "skipped"]
    assert s["state"] == "done" and s["report"] is not None
    j = jobs.for_shipment(sid)
    assert j["state"] == "timed_out" and "30 minutes" in j["reason"]
    assert jobs.quota(user)["used"] == 0


def test_cancel_while_running(isolated):
    sid, user, job = make_job(isolated)
    worker.run_job(job, FakeReader({errors_docs()[1].filename: "cancelled"}))
    assert store.get(sid)["state"] == "cancelled" and store.get(sid)["report"] is None
    assert jobs.for_shipment(sid)["state"] == "cancelled"
    assert jobs.quota(user)["used"] == 1   # it did use the machine


def test_deleted_while_running(isolated):
    sid, _, job = make_job(isolated)
    retention.erase_shipment(sid)
    worker.run_job(job, FakeReader())   # nothing to do, no crash
    assert store.get(sid) is None


def test_bundles_are_split_once(isolated):
    sid, _, job = make_job(isolated)
    store.set_files(sid, [f | {"page_count": 6} for f in store.get(sid)["files"]])
    reader = FakeReader()
    worker.run_job(job, reader)
    assert sum(c["op"] == "split" for c in reader.calls) == 6
    assert all(f.get("split_checked") for f in store.get(sid)["files"])


# ---------- retention ----------

def test_sweep_erases_expired_shipments_and_their_cache(isolated):
    sid, _, job = make_job(isolated)
    worker.run_job(job, FakeReader())
    s = store.get(sid)
    folder = cache.folder(s["workspace_id"], False)
    folder.mkdir(parents=True)
    f = s["files"][0]
    key = cache.file_hash(Path(f["path"]))
    (folder / f"{key}.json").write_text('{"doc_type": "packing_list", "text": "abc"}')
    (folder / f"fields_{cache.fields_key('packing_list', 'abc')}.json").write_text("{}")

    retention.sweep(now=time.time())                      # not expired yet
    assert store.get(sid) is not None
    retention.sweep(now=time.time() + config.RETENTION_DAYS * 86400 + 60)
    assert store.get(sid) is None and not (retention.UPLOADS / sid).exists()
    assert list(folder.glob("*.json")) == []


def test_demo_cache_is_kept(isolated):
    sid, _, job = make_job(isolated, demo=True)
    cache.ROOT.mkdir(parents=True, exist_ok=True)
    f = store.get(sid)["files"][0]
    entry = cache.ROOT / f"{cache.file_hash(Path(f['path']))}.json"
    entry.write_text('{"doc_type": null, "text": ""}')
    retention.erase_shipment(sid)
    assert entry.exists()


def test_unverified_accounts_expire(isolated):
    accounts.create_user("old@example.com", "Old", "correct horse 1")
    retention.sweep(now=time.time() + config.RETENTION_DAYS * 86400 + 60)
    assert accounts.user_by_email("old@example.com") is None


# ---------- estimates ----------

def test_estimates_move_forward():
    t = progress.DEFAULTS
    f = {"filename": "a.pdf", "state": "reading", "page_count": 2, "stage": "converting", "kind": "ocr",
         "stage_started": time.time() - 10}
    pct1, left1 = progress.file_estimate(f, t)
    f2 = f | {"stage": "extracting", "stage_started": time.time() - 5, "chars": 350}
    pct2, left2 = progress.file_estimate(f2, t)
    assert 0 < pct1 < pct2 < 100 and left2 < left1
    assert progress.file_estimate(f | {"state": "done"}, t) == (100, 0.0)


def test_timings_learn_from_measurements():
    progress.record("page:text", 10.0)
    progress.record("page:text", 20.0)
    assert progress.load()["page:text"] == 10.0 * 0.8 + 20.0 * 0.2


def test_model_outage_gives_the_check_back(isolated):
    sid, user, job = make_job(isolated)

    class Down(FakeReader):
        def run(self, cmd, job_id, job_deadline):
            if cmd["op"] == "read":
                return "ok", {"ok": False, "system": True, "error": worker.MODEL_DOWN}
            return super().run(cmd, job_id, job_deadline)

    worker.run_job(job, Down())
    assert jobs.quota(user)["used"] == 0 and "our side" in jobs.for_shipment(sid)["reason"]
    assert store.get(sid)["files"][0]["error"] == worker.MODEL_DOWN


def test_connection_errors_count_as_our_fault():
    try:
        try:
            raise ConnectionRefusedError(111, "Connection refused")
        except OSError as inner:
            raise RuntimeError("model call failed") from inner
    except RuntimeError as exc:
        assert worker._model_unreachable(exc)
    assert not worker._model_unreachable(ValueError("bad PDF"))
