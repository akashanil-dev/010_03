"""The check queue: one job per shipment, run one at a time in arrival order by the worker.

Limits are enforced here, inside one transaction, so two uploads at the same moment cannot both slip
past the daily quota or the per-account cap.
"""

import time

from . import config, limits, progress
from .store import _db

ACTIVE = ("queued", "running")


class LimitError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _limit(user: dict) -> int:
    return user["daily_limit"] if user.get("daily_limit") is not None else config.DAILY_SHIPMENTS


def quota(user: dict, now: float | None = None) -> dict:
    with _db() as c:
        row = c.execute("SELECT used FROM usage WHERE user_id = ? AND day = ?", (user["id"], limits.today(now))).fetchone()
    used, limit = (row["used"] if row else 0), _limit(user)
    return {"limit": limit, "used": used, "left": max(limit - used, 0), "resets_at": limits.next_reset(now)}


def _backlog(c, t: dict, now: float) -> float:
    """Seconds of work queued or running across everyone."""
    total = c.execute("SELECT COALESCE(SUM(expected), 0) FROM jobs WHERE state = 'queued'").fetchone()[0]
    running = c.execute("SELECT shipment_id FROM jobs WHERE state = 'running'").fetchone()
    if running:
        total += progress.remaining(_files(c, running[0]), t, now)
    return total


def _files(c, sid: str) -> list[dict]:
    from .store import _file_dict
    return [_file_dict(r) for r in c.execute("SELECT * FROM files WHERE shipment_id = ? ORDER BY idx", (sid,))]


def check(user: dict, counted: bool = True) -> None:
    """Raise LimitError if this account cannot start another check now (before any file is saved)."""
    with _db() as c:
        _check(c, user, counted, progress.load(), time.time())


def _check(c, user: dict, counted: bool, t: dict, now: float) -> None:
    if counted:
        row = c.execute("SELECT used FROM usage WHERE user_id = ? AND day = ?", (user["id"], limits.today(now))).fetchone()
        if row and row["used"] >= _limit(user):
            raise LimitError(429, f"You have used all {_limit(user)} checks for today. "
                                  "The limit resets at midnight (India time). Demo shipments do not count.")
    active = c.execute(f"SELECT COUNT(*) FROM jobs WHERE user_id = ? AND state IN {ACTIVE}", (user["id"],)).fetchone()[0]
    if active >= config.MAX_ACTIVE_PER_USER:
        raise LimitError(429, f"You already have {active} checks running or waiting. "
                              "Wait for one to finish, or cancel one, before starting another.")
    if _backlog(c, t, now) > config.BUSY_BACKLOG:
        raise LimitError(503, "TallyTime is very busy right now and the queue is full. Please try again in an hour.")


def enqueue(sid: str, user: dict, expected: float, counted: bool = True) -> None:
    now, t = time.time(), progress.load()
    with _db(immediate=True) as c:
        _check(c, user, counted, t, now)
        day = limits.today(now)
        c.execute("""INSERT INTO jobs (shipment_id, user_id, state, queued_at, expected, counted, day)
                     VALUES (?,?,?,?,?,?,?)""", (sid, user["id"], "queued", now, expected, int(counted), day))
        if counted:
            c.execute("""INSERT INTO usage VALUES (?,?,1)
                         ON CONFLICT (user_id, day) DO UPDATE SET used = used + 1""", (user["id"], day))


def _refund(c, job) -> None:
    if job["counted"]:
        c.execute("UPDATE usage SET used = MAX(used - 1, 0) WHERE user_id = ? AND day = ?", (job["user_id"], job["day"]))
        c.execute("UPDATE jobs SET counted = 0 WHERE id = ?", (job["id"],))


def for_shipment(sid: str) -> dict | None:
    with _db() as c:
        row = c.execute("SELECT * FROM jobs WHERE shipment_id = ?", (sid,)).fetchone()
    return dict(row) if row else None


def claim_next() -> dict | None:
    """Take the oldest waiting job (the worker calls this; one job runs at a time)."""
    with _db(immediate=True) as c:
        if c.execute("SELECT 1 FROM jobs WHERE state = 'running'").fetchone():
            return None
        row = c.execute("SELECT * FROM jobs WHERE state = 'queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        now = time.time()
        c.execute("UPDATE jobs SET state = 'running', started_at = ? WHERE id = ?", (now, row["id"]))
        c.execute("UPDATE shipments SET state = 'processing' WHERE id = ?", (row["shipment_id"],))
    return dict(row) | {"state": "running", "started_at": now}


def requeue_running() -> None:
    """After a worker restart, jobs it was running go back to the front of the queue."""
    with _db(immediate=True) as c:
        for (sid,) in c.execute("SELECT shipment_id FROM jobs WHERE state = 'running'").fetchall():
            for f in _files(c, sid):
                if f["state"] != "done":
                    c.execute("UPDATE files SET state = 'queued' WHERE shipment_id = ? AND filename = ?",
                              (sid, f["filename"]))
            c.execute("UPDATE shipments SET state = 'queued' WHERE id = ?", (sid,))
        c.execute("UPDATE jobs SET state = 'queued', started_at = NULL WHERE state = 'running'")


def request_cancel(sid: str) -> str | None:
    """Cancel a check: at once if waiting, at the worker's next look if running. Returns the job's new state."""
    with _db(immediate=True) as c:
        job = c.execute("SELECT * FROM jobs WHERE shipment_id = ?", (sid,)).fetchone()
        if not job or job["state"] not in ACTIVE:
            return None
        if job["state"] == "queued":
            c.execute("UPDATE jobs SET state = 'cancelled', finished_at = ?, reason = ? WHERE id = ?",
                      (time.time(), "Cancelled before it started.", job["id"]))
            c.execute("UPDATE shipments SET state = 'cancelled' WHERE id = ?", (sid,))
            _refund(c, job)   # nothing was used
            return "cancelled"
        c.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job["id"],))
        return "cancelling"


def stop_reason(job_id: int) -> str | None:
    """Why the worker should stop this job now: 'cancelled', 'deleted', or None to carry on."""
    with _db() as c:
        row = c.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return "deleted"
    return "cancelled" if row["cancel_requested"] else None


def finish(job_id: int, state: str, reason: str = "", refund: bool = False) -> None:
    with _db(immediate=True) as c:
        job = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return
        c.execute("UPDATE jobs SET state = ?, finished_at = ?, reason = ? WHERE id = ?",
                  (state, time.time(), reason, job_id))
        if refund:
            _refund(c, job)


def expire_waiting(now: float | None = None) -> list[dict]:
    """Cancel jobs that waited longer than the queue timeout, refunding the quota. Returns them."""
    now = now or time.time()
    with _db(immediate=True) as c:
        rows = c.execute("SELECT * FROM jobs WHERE state = 'queued' AND queued_at < ?",
                         (now - config.QUEUE_TIMEOUT,)).fetchall()
        hours = config.QUEUE_TIMEOUT / 3600
        for job in rows:
            c.execute("UPDATE jobs SET state = 'timed_out', finished_at = ?, reason = ? WHERE id = ?",
                      (now, f"Cancelled automatically: it waited more than {hours:g} hours to start. "
                            "Today's check was given back; please upload again.", job["id"]))
            c.execute("UPDATE shipments SET state = 'cancelled' WHERE id = ?", (job["shipment_id"],))
            _refund(c, job)
    return [dict(r) for r in rows]


def snapshot(workspace_ids: list[str], now: float | None = None) -> dict:
    """Queue state for one person: their workspaces' checks in detail, everyone else's only as counts."""
    now, t = now or time.time(), progress.load()
    marks = ",".join("?" * len(workspace_ids))
    with _db() as c:
        queued = c.execute("SELECT id, expected FROM jobs WHERE state = 'queued' ORDER BY id").fetchall()
        running = c.execute("SELECT * FROM jobs WHERE state = 'running'").fetchone()
        running_left = progress.remaining(_files(c, running["shipment_id"]), t, now) if running else 0.0
        mine = c.execute(f"""SELECT j.*, s.label, s.workspace_id, u.name AS by_name
                             FROM jobs j JOIN shipments s ON s.id = j.shipment_id
                             LEFT JOIN users u ON u.id = j.user_id
                             WHERE s.workspace_id IN ({marks})
                               AND (j.state IN {ACTIVE} OR j.finished_at > ?)
                             ORDER BY j.id DESC LIMIT 30""", (*workspace_ids, now - 86400)).fetchall()
        out = []
        for j in mine:
            item = {"shipment_id": j["shipment_id"], "state": j["state"], "label": j["label"],
                    "by": j["by_name"] or "", "queued_at": j["queued_at"], "started_at": j["started_at"],
                    "finished_at": j["finished_at"], "reason": j["reason"] or "",
                    "cancelling": bool(j["cancel_requested"])}
            if j["state"] == "queued":
                ahead = [q for q in queued if q["id"] < j["id"]]
                item["ahead"] = len(ahead) + (1 if running else 0)
                item["starts_in"] = round(running_left + sum(q["expected"] for q in ahead))
                item["eta"] = round(item["starts_in"] + j["expected"])
            elif j["state"] == "running":
                files = _files(c, j["shipment_id"])
                item["eta"] = round(progress.remaining(files, t, now))
                item["percent"] = _percent(files, t, now)
            out.append(item)
    return {"jobs": out, "waiting": len(queued), "busy": bool(running)}


def _percent(files: list[dict], t: dict, now: float) -> int:
    weights = [sum(progress.expected(f, t)) for f in files]
    done = [progress.file_estimate(f, t, now)[0] for f in files]
    return int(sum(w * d for w, d in zip(weights, done)) / (sum(weights) or 1))
