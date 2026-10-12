"""Accounts, login sessions, one-time email links and shared workspaces.

Passwords are hashed with Argon2. Session, verification, reset and invite tokens are random,
sent to the browser or by email once, and stored only as SHA-256 hashes.
"""

import hashlib
import secrets
import time
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from . import config
from .store import _db

SESSION_DAYS = 30
TOKEN_TTL = {"verify": 3 * 86400, "reset": 3600}
INVITE_DAYS = 7
MIN_PASSWORD = 10

_ph = PasswordHasher()
_DUMMY = _ph.hash("evens out the timing for unknown emails")


class AccountError(ValueError):
    pass


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > 200:
        raise AccountError("That password is too long (200 characters at most).")


# ---------- users ----------

def create_user(email: str, name: str, password: str) -> dict:
    """A new, unverified account with its own workspace."""
    check_password(password)
    uid, ws, now = uuid.uuid4().hex, uuid.uuid4().hex, time.time()
    with _db(immediate=True) as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AccountError("exists")
        c.execute("""INSERT INTO users (id, email, name, password_hash, terms_version, terms_at, current_workspace, created)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (uid, email, name, _ph.hash(password), config.TERMS_VERSION, now, ws, now))
        c.execute("INSERT INTO workspaces VALUES (?,?,?,?)", (ws, f"{name}'s workspace", uid, now))
        c.execute("INSERT INTO members VALUES (?,?,?,?)", (ws, uid, "owner", now))
    return get_user(uid)


def get_user(uid: str) -> dict | None:
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def user_by_email(email: str) -> dict | None:
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (normalise_email(email),)).fetchone()
    return dict(row) if row else None


def authenticate(email: str, password: str) -> dict | None:
    user = user_by_email(email)
    try:
        _ph.verify(user["password_hash"] if user else _DUMMY, password)
    except (VerificationError, InvalidHashError):
        return None
    return user


def update_user(uid: str, **fields) -> None:
    allowed = {k: v for k, v in fields.items()
               if k in ("name", "notify_email", "verified", "role", "daily_limit", "terms_version", "terms_at",
                        "current_workspace")}
    if not allowed:
        return
    with _db() as c:
        c.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?", (*allowed.values(), uid))


def set_password(uid: str, password: str) -> None:
    """Change the password and end every existing session."""
    check_password(password)
    with _db() as c:
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_ph.hash(password), uid))
        c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))


def delete_user(uid: str) -> list[str]:
    """Remove the account and the workspaces it owns. Returns the shipment ids the caller must erase."""
    with _db(immediate=True) as c:
        owned = [r[0] for r in c.execute("SELECT id FROM workspaces WHERE owner_id = ?", (uid,))]
        marks = ",".join("?" * len(owned))
        shipments = [r[0] for r in c.execute(f"SELECT id FROM shipments WHERE workspace_id IN ({marks})", owned)]
        # Members who were looking at a deleted workspace fall back to their own
        c.execute(f"""UPDATE users SET current_workspace =
                        (SELECT id FROM workspaces w WHERE w.owner_id = users.id)
                      WHERE current_workspace IN ({marks})""", owned)
        c.execute("UPDATE shipments SET created_by = NULL WHERE created_by = ?", (uid,))
        c.execute("DELETE FROM users WHERE id = ?", (uid,))
        c.execute("DELETE FROM usage WHERE user_id = ?", (uid,))
    return shipments


# ---------- sessions and one-time tokens ----------

def create_session(uid: str) -> str:
    token, now = secrets.token_urlsafe(32), time.time()
    with _db() as c:
        c.execute("INSERT INTO sessions VALUES (?,?,?,?)", (_h(token), uid, now, now + SESSION_DAYS * 86400))
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    now, full = time.time(), SESSION_DAYS * 86400
    with _db() as c:
        row = c.execute("""SELECT u.*, s.expires AS session_expires FROM sessions s JOIN users u ON u.id = s.user_id
                           WHERE s.token_hash = ? AND s.expires > ?""", (_h(token), now)).fetchone()
    if not row:
        return None
    if row["session_expires"] < now + full - 3600:   # sliding expiry, written at most once an hour
        with _db(immediate=True) as c:
            c.execute("UPDATE sessions SET expires = ? WHERE token_hash = ?", (now + full, _h(token)))
    user = dict(row)
    user.pop("session_expires")
    return user


def end_session(token: str | None) -> None:
    if token:
        with _db() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (_h(token),))


def end_all_sessions(uid: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))


def issue_token(uid: str, purpose: str) -> str:
    token = secrets.token_urlsafe(32)
    with _db() as c:
        c.execute("DELETE FROM tokens WHERE user_id = ? AND purpose = ?", (uid, purpose))   # only the latest link works
        c.execute("INSERT INTO tokens VALUES (?,?,?,?)", (_h(token), uid, purpose, time.time() + TOKEN_TTL[purpose]))
    return token


def use_token(token: str, purpose: str) -> str | None:
    """The user id the link was issued to, consuming the link. None if unknown, used or expired."""
    with _db(immediate=True) as c:
        row = c.execute("SELECT user_id, expires FROM tokens WHERE token_hash = ? AND purpose = ?",
                        (_h(token), purpose)).fetchone()
        c.execute("DELETE FROM tokens WHERE token_hash = ?", (_h(token),))
    return row["user_id"] if row and row["expires"] > time.time() else None


# ---------- workspaces ----------

def workspaces_of(uid: str) -> list[dict]:
    with _db() as c:
        rows = c.execute("""SELECT w.id, w.name, m.role, w.owner_id,
                                   (SELECT COUNT(*) FROM members x WHERE x.workspace_id = w.id) AS members
                            FROM members m JOIN workspaces w ON w.id = m.workspace_id
                            WHERE m.user_id = ? ORDER BY m.role = 'owner' DESC, w.name""", (uid,)).fetchall()
    return [dict(r) for r in rows]


def role_in(workspace_id: str | None, uid: str) -> str | None:
    if not workspace_id:
        return None
    with _db() as c:
        row = c.execute("SELECT role FROM members WHERE workspace_id = ? AND user_id = ?", (workspace_id, uid)).fetchone()
    return row["role"] if row else None


def current_workspace(user: dict) -> str:
    """The workspace new checks go into: the one the user picked, if still a member, else their own."""
    if role_in(user.get("current_workspace"), user["id"]):
        return user["current_workspace"]
    own = next(w["id"] for w in workspaces_of(user["id"]) if w["role"] == "owner")
    update_user(user["id"], current_workspace=own)
    return own


def members(workspace_id: str) -> list[dict]:
    with _db() as c:
        rows = c.execute("""SELECT u.id, u.name, u.email, m.role FROM members m JOIN users u ON u.id = m.user_id
                            WHERE m.workspace_id = ? ORDER BY m.role = 'owner' DESC, u.name""",
                         (workspace_id,)).fetchall()
    return [dict(r) for r in rows]


def rename_workspace(workspace_id: str, name: str) -> None:
    with _db() as c:
        c.execute("UPDATE workspaces SET name = ? WHERE id = ?", (name, workspace_id))


def create_invite(workspace_id: str, email: str, invited_by: str) -> str:
    token, now = secrets.token_urlsafe(32), time.time()
    with _db(immediate=True) as c:
        if c.execute("""SELECT 1 FROM members m JOIN users u ON u.id = m.user_id
                        WHERE m.workspace_id = ? AND u.email = ?""", (workspace_id, email)).fetchone():
            raise AccountError(f"{email} is already a member of this workspace.")
        if c.execute("SELECT COUNT(*) FROM invites WHERE workspace_id = ? AND expires > ?",
                     (workspace_id, now)).fetchone()[0] >= 20:
            raise AccountError("Too many open invitations. Cancel some before inviting more people.")
        c.execute("DELETE FROM invites WHERE workspace_id = ? AND email = ?", (workspace_id, email))
        c.execute("INSERT INTO invites VALUES (?,?,?,?,?,?)",
                  (_h(token), workspace_id, email, invited_by, now, now + INVITE_DAYS * 86400))
    return token


def invites(workspace_id: str) -> list[dict]:
    with _db() as c:
        rows = c.execute("SELECT email, created, expires FROM invites WHERE workspace_id = ? AND expires > ?",
                         (workspace_id, time.time())).fetchall()
    return [dict(r) for r in rows]


def cancel_invite(workspace_id: str, email: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM invites WHERE workspace_id = ? AND email = ?", (workspace_id, email))


def invite_details(token: str) -> dict | None:
    with _db() as c:
        row = c.execute("""SELECT i.email, i.expires, w.id AS workspace_id, w.name AS workspace,
                                  u.name AS invited_by
                           FROM invites i JOIN workspaces w ON w.id = i.workspace_id
                           LEFT JOIN users u ON u.id = i.invited_by WHERE i.token_hash = ?""", (_h(token),)).fetchone()
    return dict(row) if row and row["expires"] > time.time() else None


def accept_invite(token: str, user: dict) -> str:
    """Join the workspace if the invitation was sent to this account's email. Returns the workspace id."""
    inv = invite_details(token)
    if not inv:
        raise AccountError("This invitation has expired or was cancelled. Ask for a new one.")
    if inv["email"] != user["email"]:
        raise AccountError(f"This invitation was sent to {inv['email']}. Log in with that email to accept it.")
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO members VALUES (?,?,?,?)", (inv["workspace_id"], user["id"], "member", time.time()))
        c.execute("DELETE FROM invites WHERE token_hash = ?", (_h(token),))
        c.execute("UPDATE users SET current_workspace = ? WHERE id = ?", (inv["workspace_id"], user["id"]))
    return inv["workspace_id"]


def remove_member(workspace_id: str, uid: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM members WHERE workspace_id = ? AND user_id = ? AND role != 'owner'", (workspace_id, uid))


# ---------- push subscriptions ----------

def add_push(uid: str, endpoint: str, p256dh: str, auth: str) -> None:
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO push_subs VALUES (?,?,?,?,?)", (endpoint, uid, p256dh, auth, time.time()))


def remove_push(endpoint: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))


def push_subs(uid: str) -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM push_subs WHERE user_id = ?", (uid,))]


# ---------- housekeeping ----------

def cleanup(now: float | None = None) -> list[str]:
    """Drop expired sessions, links and invitations, and accounts never verified within the retention period.

    Returns shipment ids of removed accounts' workspaces for the caller to erase.
    """
    now = now or time.time()
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        c.execute("DELETE FROM tokens WHERE expires < ?", (now,))
        c.execute("DELETE FROM invites WHERE expires < ?", (now,))
        c.execute("DELETE FROM usage WHERE day < date(?, 'unixepoch', '-40 days')", (now,))
        stale = [r[0] for r in c.execute("SELECT id FROM users WHERE verified = 0 AND created < ?",
                                         (now - config.RETENTION_DAYS * 86400,))]
    erase = []
    for uid in stale:
        erase += delete_user(uid)
    return erase
