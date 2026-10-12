"""The worker: runs queued checks one at a time, with a watchdog. Start it next to the web app:

    python -m app.worker

This process (the supervisor) loads no models. It takes the next job from the queue and hands each step
(split a merged PDF, read one document) to a reader process that holds Docling and talks to the model.
If a step runs past its deadline, or the person cancels, the supervisor kills the reader and starts a
fresh one, so a stuck document can never hold up everyone else's checks. Once an hour it also runs the
retention sweep.
"""

import logging
import multiprocessing as mp
import signal
import sys
import time
from pathlib import Path

from . import cache, config, jobs, notify, report, retention, store
from .schemas import ParsedDocument

log = logging.getLogger("tallytime.worker")
POLL = 1.0
SWEEP_EVERY = 3600
HEARTBEAT = Path(__file__).resolve().parent.parent / "data" / "worker.heartbeat"
READY_TIMEOUT = 600   # first start may download the Docling models


def heartbeat() -> None:
    """Tell the web app's health check that the worker is alive."""
    try:
        HEARTBEAT.touch()
    except OSError:
        pass


# ---------- reader process ----------

def _reader_main(conn) -> None:
    """Load Docling once, then run one step at a time for the supervisor."""
    from . import parsing, splitting

    parsing.warm_up()
    conn.send({"ready": True})
    while True:
        try:
            cmd = conn.recv()
        except EOFError:
            return
        try:
            if cmd["op"] == "split":
                conn.send({"ok": True, "parts": splitting.split_bundle(Path(cmd["path"]), Path(cmd["path"]).parent)})
            else:
                conn.send({"ok": True, "doc": _read(cmd)})
        except Exception as exc:
            if _model_unreachable(exc):
                conn.send({"ok": False, "system": True, "error": MODEL_DOWN})
            else:
                conn.send({"ok": False, "error": str(exc) or exc.__class__.__name__})


MODEL_DOWN = "The AI model was not available on our side, so this document was not read. Please try again later."


def _model_unreachable(exc: BaseException) -> bool:
    """A connection failure to the model server (our fault, so the check is given back)."""
    while exc:
        if isinstance(exc, ConnectionError) or type(exc).__name__ in ("ConnectError", "ConnectTimeout"):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _read(cmd: dict) -> str:
    """Read one document, reporting each stage to the database and learning how long stages take."""
    from . import pipeline, progress

    sid, idx = cmd["sid"], cmd["idx"]
    seen: dict = {}

    def on_stage(stage: str, **info) -> None:
        if stage not in seen:
            seen[stage] = time.time()
            info["stage_started"] = seen[stage]
        seen.update({f"{stage}:{k}": v for k, v in info.items()})
        store.update_file(sid, idx, stage=stage, **info)

    doc = pipeline.process_file(Path(cmd["path"]), cmd["filename"], cmd.get("cache_key"), Path(cmd["cache_dir"]),
                                on_stage)
    end = time.time()
    if "converting" in seen:
        pages = max(cmd.get("page_count") or 1, 1)
        progress.record(f"page:{seen['converting:kind']}", (seen.get("extracting", end) - seen["converting"]) / pages)
    if "extracting" in seen and doc.doc_type:
        seconds, chars = end - seen["extracting"], seen.get("extracting:chars")
        for key in ("extract", f"extract:{doc.doc_type}"):
            progress.record(key, seconds)
        if chars:
            for key in ("chars", f"chars:{doc.doc_type}"):
                progress.record(key, chars)
    return doc.model_dump_json()


class Reader:
    """The reader process, replaced whenever it has to be stopped."""

    def __init__(self):
        self.ctx = mp.get_context("spawn")   # a clean process: no threads or locks inherited
        self.proc = None
        self.conn = None

    def start(self) -> None:
        parent, child = self.ctx.Pipe()
        self.proc = self.ctx.Process(target=_reader_main, args=(child,), daemon=True, name="tallytime-reader")
        self.proc.start()
        child.close()
        self.conn = parent
        if not parent.poll(READY_TIMEOUT) or not parent.recv().get("ready"):
            self.stop()
            raise RuntimeError("The reader process did not start")

    def stop(self) -> None:
        if self.proc and self.proc.is_alive():
            self.proc.kill()
            self.proc.join(10)
        self.proc = None

    def run(self, cmd: dict, job_id: int, job_deadline: float) -> tuple[str, dict | None]:
        """Run one step. Returns (status, reply): status is ok, crashed, cancelled, deleted, doc_timeout
        or job_timeout."""
        if not self.proc or not self.proc.is_alive():
            self.start()
        doc_deadline = time.time() + config.DOC_TIMEOUT
        try:
            self.conn.send(cmd)
            while True:
                heartbeat()
                if self.conn.poll(POLL):
                    return "ok", self.conn.recv()
                if not self.proc.is_alive():
                    raise EOFError
                stop = jobs.stop_reason(job_id)
                now = time.time()
                if not stop and now > job_deadline:
                    stop = "job_timeout"
                elif not stop and now > doc_deadline:
                    stop = "doc_timeout"
                if stop:
                    self.stop()
                    return stop, None
        except (EOFError, OSError):
            self.stop()
            return "crashed", None


# ---------- one job ----------

def _needs_split(f: dict) -> bool:
    return (Path(f["path"]).suffix.lower() == ".pdf" and (f.get("page_count") or 2) >= 2
            and not f.get("bundle") and not f.get("split_checked"))


def _skipped(stop: str) -> str:
    if stop == "job_timeout":
        return f"Not read: the check was stopped after {config.SHIPMENT_TIMEOUT // 60} minutes."
    return "Not read: the check was cancelled."


def run_job(job: dict, reader: Reader) -> None:
    sid, job_id = job["shipment_id"], job["id"]
    s = store.get(sid)
    if not s:
        return
    job_deadline = job["started_at"] + config.SHIPMENT_TIMEOUT
    cache_dir = str(cache.folder(s["workspace_id"], s["demo"]))
    files, stop = s["files"], None

    # 1. Split merged PDFs into one file per document
    if any(_needs_split(f) for f in files):
        expanded = []
        for idx, f in enumerate(files):
            if stop or not _needs_split(f):
                expanded.append(f)
                continue
            store.update_file(sid, idx, state="splitting", started=time.time())
            status, reply = reader.run({"op": "split", "path": f["path"]}, job_id, job_deadline)
            if status in ("cancelled", "deleted", "job_timeout"):
                stop = status
            parts = reply.get("parts") if status == "ok" and reply.get("ok") else None
            if parts:
                h = cache.file_hash(Path(f["path"]))
                expanded += [{"filename": p["filename"], "path": p["path"], "state": "queued", "bundle": f["filename"],
                              "pages": p["pages"], "page_count": len(p["pages"]),
                              "cache_key": f"{h}_p{'-'.join(map(str, p['pages']))}"} for p in parts]
            else:
                expanded.append({k: v for k, v in f.items() if k != "started"} | {"state": "queued", "split_checked": True})
        store.set_files(sid, expanded)
        files = expanded

    # 2. Read each document
    docs, failed, our_fault = [], [], False
    for idx, f in enumerate(files):
        if stop:
            store.update_file(sid, idx, state="skipped", error=_skipped(stop))
            failed.append((f["filename"], _skipped(stop)))
            continue
        now = time.time()
        store.update_file(sid, idx, state="reading", started=now, stage="starting", stage_started=now, chars=0)
        status, reply = reader.run({"op": "read", "sid": sid, "idx": idx, "path": f["path"], "filename": f["filename"],
                                    "cache_key": f.get("cache_key"), "cache_dir": cache_dir,
                                    "page_count": f.get("page_count")}, job_id, job_deadline)
        if status == "ok" and reply["ok"]:
            doc = ParsedDocument.model_validate_json(reply["doc"])
            docs.append(doc)
            store.update_file(sid, idx, state="done", doc_type=doc.doc_type, ocr_used=doc.ocr_used,
                              source_format=doc.source_format, seconds=round(time.time() - now, 1))
            continue
        if status in ("ok", "crashed", "doc_timeout"):
            our_fault = our_fault or bool(reply and reply.get("system"))
            msg = {"ok": (reply or {}).get("error", ""),
                   "crashed": "The reader stopped unexpectedly while reading this file. Try a clearer scan or a smaller file.",
                   "doc_timeout": f"Stopped: reading this document took longer than {config.DOC_TIMEOUT // 60} minutes. "
                                  "Try a clearer scan or upload the pages separately."}[status]
            store.update_file(sid, idx, state="error", error=msg)
            failed.append((f["filename"], msg))
            continue
        stop = status
        store.update_file(sid, idx, state="skipped", error=_skipped(stop))
        failed.append((f["filename"], _skipped(stop)))

    # 3. Results
    if stop == "deleted":
        return
    if stop == "cancelled":
        store.set_state(sid, "cancelled")
        jobs.finish(job_id, "cancelled", "Cancelled while it was running.")
        return
    rep = report.build(docs, failed)
    label = report.label(docs) or files[0]["filename"]
    store.finish(sid, rep, label)
    if stop == "job_timeout":
        jobs.finish(job_id, "timed_out", f"Stopped after {config.SHIPMENT_TIMEOUT // 60} minutes. The results cover "
                                         "only the documents read in time, and today's check was given back.", refund=True)
    elif our_fault:
        jobs.finish(job_id, "done", "Some documents could not be read because of a problem on our side, "
                                    "so today's check was given back.", refund=True)
    else:
        jobs.finish(job_id, "done")
    notify.job_finished(job["user_id"], sid, "timed_out" if stop else "done", rep["verdict"], label)


# ---------- main loop ----------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    store.init()
    jobs.requeue_running()
    reader = Reader()

    def shutdown(*_):
        reader.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    reader.start()
    log.info("Worker ready")
    last_sweep = 0.0
    while True:
        try:
            heartbeat()
            for job in jobs.expire_waiting():
                notify.job_finished(job["user_id"], job["shipment_id"], "expired")
            if time.time() - last_sweep > SWEEP_EVERY:
                retention.sweep()
                last_sweep = time.time()
            job = jobs.claim_next()
            if not job:
                time.sleep(POLL)
                continue
            log.info("Checking %s", job["shipment_id"])
            try:
                run_job(job, reader)
            except Exception:
                log.exception("Check %s failed", job["shipment_id"])
                jobs.finish(job["id"], "failed", "Something went wrong on our side. Today's check was given back.",
                            refund=True)
                store.set_state(job["shipment_id"], "failed")
                notify.job_finished(job["user_id"], job["shipment_id"], "failed")
        except Exception:
            log.exception("Worker loop error")
            time.sleep(5)


if __name__ == "__main__":
    main()
