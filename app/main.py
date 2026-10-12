"""TallyTime web API. Run: uvicorn app.main:app (and the worker: python -m app.worker)

The web app only accepts uploads, queues checks and serves results; the worker does the reading.
Every shipment belongs to a workspace and is visible only to that workspace's members.
"""

import asyncio
import json
import mimetypes
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import accounts, auth, jobs, progress, retention, store, uploads
from .auth import active_user
from .formats import SUPPORTED

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = retention.UPLOADS
DEMO = ROOT / "data" / "demo"
STATIC = ROOT / "static"
HEARTBEAT = ROOT / "data" / "worker.heartbeat"
DEMOS = ("clean", "errors", "scanned", "bundle", "mixed", "quality", "lc")
DEMO_SECONDS = 3

CSP = ("default-src 'self'; script-src 'self' https://challenges.cloudflare.com; "
       "frame-src https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")

app = FastAPI(title="TallyTime: Export Document Verification", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)


@app.on_event("startup")
def _startup():
    store.init()


@app.middleware("http")
async def guard(request: Request, call_next):
    """Refuse cross-site writes (CSRF) and add security headers."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", CSP)
    return response


def _limit_error(e: jobs.LimitError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _start(files: list[tuple[str, Path]], user: dict, demo: bool = False) -> str:
    """Copy the files into the shipment's folder and put the check in the queue."""
    sid = uuid.uuid4().hex[:16]
    folder = UPLOADS / sid
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for name, src in files:
        dst = folder / Path(name).name
        shutil.copyfile(src, dst)
        items.append({"filename": dst.name, "path": str(dst), "state": "queued", "page_count": uploads.page_count(dst)})
    store.create(sid, items, workspace_id=accounts.current_workspace(user), created_by=user["id"], demo=demo)
    try:
        expected = DEMO_SECONDS * len(items) if demo else progress.upload_estimate(items)   # demos come from the cache
        jobs.enqueue(sid, user, expected, counted=not demo)
    except jobs.LimitError as e:   # someone else filled the last slot in the meantime
        retention.erase_shipment(sid)
        raise _limit_error(e)
    return sid


@app.post("/api/shipments")
async def create_shipment(request: Request, files: list[UploadFile] = File(...), user: dict = Depends(active_user)):
    from . import limits

    limits.hit("upload", auth.ip(request))
    try:
        jobs.check(user)
    except jobs.LimitError as e:
        raise _limit_error(e)
    if len(files) > uploads.MAX_FILES:
        raise HTTPException(400, f"Too many files: {len(files)}. Upload at most {uploads.MAX_FILES} per shipment.")
    names = [Path(f.filename or "").name for f in files]
    if len(set(names)) != len(names):
        raise HTTPException(400, "Two files have the same name. Rename one and upload again.")
    tmp = UPLOADS / "_incoming" / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        saved, problems = [], []
        for f, name in zip(files, names):
            if Path(name).suffix.lower() not in SUPPORTED:
                problems.append(f"{name}: unsupported file type. Use PDF, image (JPG/PNG/TIFF), Excel, Word or CSV.")
                continue
            p = tmp / name
            try:
                await uploads.save_limited(f, p)
                uploads.check_content(p, name)
                saved.append((name, p))
            except uploads.UploadError as e:
                problems.append(str(e))
        if problems:
            raise HTTPException(400, " ".join(problems))
        return {"id": _start(saved, user)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/demo/{name}")
def demo(name: str, user: dict = Depends(active_user)):
    folder = DEMO / name
    if name not in DEMOS or not folder.exists():
        raise HTTPException(404, "Unknown demo set")
    try:
        jobs.check(user, counted=False)
    except jobs.LimitError as e:
        raise _limit_error(e)
    return {"id": _start([(p.name, p) for p in sorted(folder.iterdir()) if p.suffix.lower() in SUPPORTED], user, demo=True)}


def _shipment(sid: str, user: dict) -> dict:
    """The shipment if this person may see it. Others get the same 404 as for a shipment that does not exist."""
    s = store.get(sid)
    if not s or not accounts.role_in(s["workspace_id"], user["id"]):
        raise HTTPException(404, "Shipment not found (it may have been deleted)")
    return s


HIDDEN = ("path", "started", "cache_key", "stage_started", "chars", "split_checked", "kind")


@app.get("/api/shipments/{sid}")
def get_shipment(sid: str, user: dict = Depends(active_user)):
    s = _shipment(sid, user)
    now, t = time.time(), progress.load()
    files = []
    for f in s["files"]:
        item = {k: v for k, v in f.items() if k not in HIDDEN}
        if f["state"] in ("reading", "splitting"):
            item["elapsed"] = round(now - (f.get("started") or now), 1)
        item["percent"], eta = progress.file_estimate(f, t, now)
        item["eta"] = round(eta)
        files.append(item)
    job = next((j for j in jobs.snapshot([s["workspace_id"]], now)["jobs"] if j["shipment_id"] == sid), None)
    return {"id": sid, "label": s.get("label"), "created": s.get("created"), "expires_at": s["expires_at"],
            "state": s["state"], "files": files, "job": job, "demo": s["demo"],
            "report": s["report"], "reviews": s["reviews"], "audit": s["audit"], "final": s.get("final")}


@app.post("/api/shipments/{sid}/cancel")
def cancel(sid: str, user: dict = Depends(active_user)):
    s = _shipment(sid, user)
    if s["created_by"] != user["id"] and accounts.role_in(s["workspace_id"], user["id"]) != "owner":
        raise HTTPException(403, "Only the person who started this check, or the workspace owner, can cancel it.")
    state = jobs.request_cancel(sid)
    if not state:
        raise HTTPException(400, "This check has already finished.")
    return {"state": state}


class Review(BaseModel):
    check_id: str
    decision: str          # "confirmed" (a real problem) | "overridden" (accepted as is)
    note: str = ""
    reviewer: str = ""


@app.post("/api/shipments/{sid}/reviews")
def add_review(sid: str, review: Review, user: dict = Depends(active_user)):
    s = _shipment(sid, user)
    if review.decision not in ("confirmed", "overridden"):
        raise HTTPException(400, "decision must be 'confirmed' or 'overridden'")
    flags = {c["id"] for c in (s.get("report") or {}).get("checks", []) if c["status"] in ("error", "warning")}
    if review.check_id not in flags:
        raise HTTPException(404, "No such issue on this shipment")
    if len(review.note) > 1000:
        raise HTTPException(400, "The note is too long (1000 characters at most)")
    if review.decision == "overridden" and not review.note.strip():
        raise HTTPException(400, "A note is required to override a flag")
    name = " ".join(review.reviewer.split())[:60] or "Unnamed reviewer"
    entry = review.model_dump() | {"reviewer": name, "at": datetime.now().isoformat(timespec="seconds"),
                                   "account": user["name"]}
    store.add_review(sid, entry)
    return {"ok": True}


@app.get("/api/shipments/{sid}/files/{filename}")
def get_file(sid: str, filename: str, user: dict = Depends(active_user)):
    s = _shipment(sid, user)
    for f in s["files"]:
        if f["filename"] == filename and Path(f["path"]).exists():
            media = mimetypes.guess_type(f["path"])[0] or "application/octet-stream"
            return FileResponse(f["path"], media_type=media, filename=f["filename"],
                                content_disposition_type="inline")
    raise HTTPException(404, "File not found")


@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: str, user: dict = Depends(active_user)):
    _shipment(sid, user)
    jobs.request_cancel(sid)
    retention.erase_shipment(sid)
    return {"deleted": sid}


def _queue(user: dict) -> dict:
    return jobs.snapshot([w["id"] for w in accounts.workspaces_of(user["id"])])


@app.get("/api/queue")
def queue(user: dict = Depends(active_user)):
    return _queue(user)


@app.get("/api/events")
async def events(request: Request, user: dict = Depends(active_user)):
    """Live queue updates (server-sent events) for the queue panel and finish notifications."""
    async def stream():
        last, sent = None, 0.0
        while not await request.is_disconnected():
            body = json.dumps(await run_in_threadpool(_queue, user))
            if body != last or time.time() - sent > 15:   # also a keep-alive
                yield f"data: {body}\n\n"
                last, sent = body, time.time()
            await asyncio.sleep(1.5)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/info")
def info():
    from .llm import model_info
    return model_info()


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(active_user)):
    return store.dashboard(store.finished(accounts.current_workspace(user)))


@app.get("/healthz")
def healthz():
    try:
        beat = time.time() - HEARTBEAT.stat().st_mtime
    except OSError:
        beat = None
    worker_ok = beat is not None and beat < 60
    snap = jobs.snapshot([])
    return JSONResponse({"ok": worker_ok, "worker_seconds_since_heartbeat": beat and round(beat),
                         "waiting": snap["waiting"], "busy": snap["busy"]}, status_code=200 if worker_ok else 503)


@app.get("/openapi.json", include_in_schema=False)
def openapi(user: dict = Depends(active_user)):
    return app.openapi()


@app.get("/docs", include_in_schema=False)
def docs(user: dict = Depends(active_user)):
    page = get_swagger_ui_html(openapi_url="/openapi.json", title="TallyTime API")
    page.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                               "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com")
    return page


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
