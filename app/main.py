"""Tally web API. Run: uvicorn app.main:app"""

import mimetypes
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

from . import report, store
from .parsing import SUPPORTED, warm_up
from .pipeline import file_hash, process_file
from .splitting import split_bundle

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "data" / "uploads"
DEMO = ROOT / "data" / "demo"
STATIC = ROOT / "static"

app = FastAPI(title="Tally: Export Document Verification")
SHIPMENTS: dict[str, dict] = store.load_all()   # working copy; every change is saved to SQLite
LOCK = threading.Lock()           # the local model reads one document at a time


@app.on_event("startup")
def _startup():
    threading.Thread(target=warm_up, daemon=True).start()


def _expand_bundles(s: dict):
    """Replace any merged PDF holding several documents with one entry per document."""
    expanded = []
    for item in s["files"]:
        if Path(item["path"]).suffix.lower() != ".pdf":
            item["state"] = "queued"
            expanded.append(item)
            continue
        item["state"] = "splitting"
        try:
            with LOCK:
                parts = split_bundle(Path(item["path"]), Path(item["path"]).parent)
        except Exception:
            parts = None
        if not parts:
            item["state"] = "queued"
            expanded.append(item)
            continue
        source_hash = file_hash(Path(item["path"]))
        for p in parts:
            expanded.append({"filename": p["filename"], "path": p["path"], "state": "queued",
                             "bundle": item["filename"], "pages": p["pages"],
                             "cache_key": f"{source_hash}_p{'-'.join(map(str, p['pages']))}"})
    s["files"] = expanded


def _process(sid: str):
    s = SHIPMENTS[sid]
    _expand_bundles(s)
    docs = []
    for item in s["files"]:
        item["state"] = "reading"
        item["started"] = time.time()
        try:
            with LOCK:
                doc = process_file(Path(item["path"]), item["filename"], item.get("cache_key"))
            docs.append(doc)
            item.update(state="done", doc_type=doc.doc_type, ocr_used=doc.ocr_used, source_format=doc.source_format,
                        seconds=round(time.time() - item["started"], 1))
        except Exception as exc:  # keep going with the other documents
            item.update(state="error", error=str(exc))
    s["report"] = report.build(docs)
    s["label"] = _label(docs) or sid
    s["state"] = "done"
    store.save(s)


def _label(docs) -> str:
    """'KME/EXP/26-27/0093 · Noordhaven Foods B.V.' from the invoice, falling back to any document."""
    def first(key, prefer):
        for d in sorted(docs, key=lambda d: d.doc_type != prefer):
            f = d.fields.get(key)
            if f and f.raw:
                return f.raw.split(",")[0]
        return None
    inv = first("doc_number", "commercial_invoice") if any(d.doc_type == "commercial_invoice" for d in docs) else None
    return " · ".join(x for x in (inv, first("consignee_name", "commercial_invoice")) if x)


def _start(files: list[tuple[str, Path]]) -> str:
    sid = uuid.uuid4().hex[:10]
    folder = UPLOADS / sid
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for name, src in files:
        dst = folder / Path(name).name
        shutil.copyfile(src, dst)
        items.append({"filename": dst.name, "path": str(dst), "state": "queued"})
    SHIPMENTS[sid] = {"id": sid, "created": time.time(), "state": "processing", "files": items, "report": None,
                      "reviews": {}, "audit": []}
    threading.Thread(target=_process, args=(sid,), daemon=True).start()
    return sid


@app.post("/api/shipments")
async def create_shipment(files: list[UploadFile] = File(...)):
    tmp = UPLOADS / "_incoming" / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        saved = []
        for f in files:
            if Path(f.filename or "").suffix.lower() not in SUPPORTED:
                raise HTTPException(400, f"{f.filename}: unsupported file type. Use PDF, image (JPG/PNG/TIFF), "
                                         "Excel, Word or CSV.")
            p = tmp / Path(f.filename).name
            p.write_bytes(await f.read())
            saved.append((f.filename, p))
        return {"id": _start(saved)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/demo/{name}")
def demo(name: str):
    folder = DEMO / name
    if name not in ("clean", "errors", "scanned", "bundle", "mixed") or not folder.exists():
        raise HTTPException(404, "Unknown demo set")
    return {"id": _start([(p.name, p) for p in sorted(folder.iterdir()) if p.suffix.lower() in SUPPORTED])}


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
        item = {k: v for k, v in f.items() if k not in ("path", "started", "cache_key")}
        if f["state"] == "reading":
            item["elapsed"] = round(now - f["started"], 1)
        files.append(item)
    return {"id": sid, "label": s.get("label"), "created": s.get("created"), "state": s["state"], "files": files,
            "report": s["report"],
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
    store.save(s)
    return {"ok": True}


@app.get("/api/shipments/{sid}/files/{filename}")
def get_file(sid: str, filename: str):
    s = _get(sid)
    for f in s["files"]:
        if f["filename"] == filename:
            media = mimetypes.guess_type(f["path"])[0] or "application/octet-stream"
            return FileResponse(f["path"], media_type=media, filename=f["filename"],
                                content_disposition_type="inline")
    raise HTTPException(404, "File not found")


@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: str):
    _get(sid)
    shutil.rmtree(UPLOADS / sid, ignore_errors=True)
    SHIPMENTS.pop(sid, None)
    store.delete(sid)
    return {"deleted": sid}


@app.get("/api/dashboard")
def dashboard():
    return store.dashboard(list(SHIPMENTS.values()))


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
