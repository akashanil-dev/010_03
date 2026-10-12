"""Seven-day retention: uploaded files, readings, results, reviews and the audit trail are erased
automatically, along with anything else that should not be kept (expired logins and links, accounts never
verified). The worker runs sweep() every hour.
"""

import logging
import shutil
import time
from pathlib import Path

from . import accounts, cache, config, store

log = logging.getLogger("tallytime.retention")
UPLOADS = Path(__file__).resolve().parent.parent / "data" / "uploads"


def erase_shipment(sid: str) -> None:
    """Remove every trace of one shipment: cached readings, uploaded files and database rows."""
    s = store.get(sid)
    if s:
        folder = cache.folder(s["workspace_id"], s["demo"])
        for f in s["files"]:
            cache.forget(folder, Path(f["path"]), f.get("cache_key"))
    shutil.rmtree(UPLOADS / sid, ignore_errors=True)
    store.delete(sid)


def sweep(now: float | None = None) -> dict:
    now = now or time.time()
    expired = store.expired(now)
    for sid in expired:
        erase_shipment(sid)
    erased_accounts = accounts.cleanup(now)
    for sid in erased_accounts:
        erase_shipment(sid)
    stale_cache = cache.sweep(config.RETENTION_DAYS * 86400, now)
    # Upload folders whose shipment no longer exists (e.g. a crash between saving and recording)
    orphans = 0
    for d in UPLOADS.glob("*"):
        if d.is_dir() and d.name != "_incoming" and d.stat().st_mtime < now - 3600 and not store.get(d.name):
            shutil.rmtree(d, ignore_errors=True)
            orphans += 1
    for d in (UPLOADS / "_incoming").glob("*"):
        if d.stat().st_mtime < now - 3600:
            shutil.rmtree(d, ignore_errors=True)
    result = {"shipments": len(expired), "account_shipments": len(erased_accounts), "cache": stale_cache,
              "orphan_folders": orphans}
    if any(result.values()):
        log.info("Retention sweep: %s", result)
    return result
