"""Tally web API. Run: uvicorn app.main:app"""

import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import report
from .parsing import warm_up
from .pipeline import process_file

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "data" / "uploads"
DEMO = ROOT / "data" / "demo"
STATIC = ROOT / "static"

app = FastAPI(title="Tally: Export Document Verification")
SHIPMENTS: dict[str, dict] = {}   # in-memory store; uploads live on disk until deleted
LOCK = threading.Lock()           # the local model reads one document at a time


@app.on_event("startup")
def _startup():
    threading.Thread(target=warm_up, daemon=True).start()


def _process(sid: str):
    s = SHIPMENTS[sid]
    docs = []
    for item in s["files"]:
        item["state"] = "reading"
        item["started"] = time.time()
        try:
            with LOCK:
                doc = process_file(Path(item["path"]), item["filename"])
            docs.append(doc)
            item.update(state="done", doc_type=doc.doc_type, ocr_used=doc.ocr_used,
                        seconds=round(time.time() - item["started"], 1))
        except Exception as exc:  # keep going with the other documents
            item.update(state="error", error=str(exc))
    s["report"] = report.build(docs)
    s["state"] = "done"


def _start(files: list[tuple[str, Path]]) -> str:
    sid = uuid.uuid4().hex[:10]
    folder = UPLOADS / sid
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for name, src in files:
        dst = folder / Path(name).name
        shutil.copyfile(src, dst)
        items.append({"filename": dst.name, "path": str(dst), "state": "queued"})
    SHIPMENTS[sid] = {"id": sid, "state": "processing", "files": items, "report": None, "reviews": {}, "audit": []}
    threading.Thread(target=_process, args=(sid,), daemon=True).start()
    return sid


@app.post("/api/shipments")
async def create_shipment(files: list[UploadFile] = File(...)):
    tmp = UPLOADS / "_incoming" / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        saved = []
        for f in files:
            if not (f.filename or "").lower().endswith(".pdf"):
                raise HTTPException(400, f"{f.filename}: only PDF files are supported")
            p = tmp / Path(f.filename).name
            p.write_bytes(await f.read())
            saved.append((f.filename, p))
        return {"id": _start(saved)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/demo/{name}")
def demo(name: str):
    folder = DEMO / name
    if name not in ("clean", "errors", "scanned") or not folder.exists():
        raise HTTPException(404, "Unknown demo set")
    return {"id": _start([(p.name, p) for p in sorted(folder.glob("*.pdf"))])}


def _get(sid: str) -> dict:
    s = SHIPMENTS.get(sid)
    if not s:
        raise HTTPException(404, "Shipment not found (it may have been deleted)")
    return s


@app.get("/api/shipments/{sid}")
def get_shipment(sid: str):
    s = _get(sid)
    now = time.time()
    files = []
    for f in s["files"]:
        item = {k: v for k, v in f.items() if k not in ("path", "started")}
        if f["state"] == "reading":
            item["elapsed"] = round(now - f["started"], 1)
        files.append(item)
    return {"id": sid, "state": s["state"], "files": files, "report": s["report"],
            "reviews": s["reviews"], "audit": s["audit"]}


class Review(BaseModel):
    check_id: str
    decision: str          # "confirmed" (a real problem) | "overridden" (accepted as is)
    note: str = ""
    reviewer: str = "Reviewer"


@app.post("/api/shipments/{sid}/reviews")
def add_review(sid: str, review: Review):
    s = _get(sid)
    if review.decision not in ("confirmed", "overridden"):
        raise HTTPException(400, "decision must be 'confirmed' or 'overridden'")
    if review.decision == "overridden" and not review.note.strip():
        raise HTTPException(400, "A note is required to override a flag")
    entry = review.model_dump() | {"at": datetime.now().isoformat(timespec="seconds")}
    s["reviews"][review.check_id] = entry
    s["audit"].append(entry)
    return {"ok": True}


@app.get("/api/shipments/{sid}/files/{filename}")
def get_file(sid: str, filename: str):
    s = _get(sid)
    for f in s["files"]:
        if f["filename"] == filename:
            return FileResponse(f["path"], media_type="application/pdf")
    raise HTTPException(404, "File not found")


@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: str):
    _get(sid)
    shutil.rmtree(UPLOADS / sid, ignore_errors=True)
    SHIPMENTS.pop(sid, None)
    return {"deleted": sid}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
