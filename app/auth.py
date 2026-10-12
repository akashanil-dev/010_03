"""Sign-up, login, email verification, password reset, account settings and shared workspaces.

Sessions live in an HttpOnly cookie. Links sent by email carry their token after '#', so tokens never
reach server logs; the page posts them here.
"""

import re
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import accounts, config, jobs, limits, mailer, retention
from .accounts import AccountError

COOKIE = "tt_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
router = APIRouter(prefix="/api")


# ---------- dependencies ----------

def ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def current_user(request: Request) -> dict:
    user = accounts.session_user(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Please log in.")
    return user


def active_user(user: dict = Depends(current_user)) -> dict:
    """A logged-in user who has confirmed their email and accepted the current terms."""
    if not user["verified"]:
        raise HTTPException(403, "Confirm your email first. We sent you a link when you signed up.")
    if user["terms_version"] != config.TERMS_VERSION:
        raise HTTPException(403, "Please accept the updated Terms of Use and Privacy Policy to continue.")
    return user


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=accounts.SESSION_DAYS * 86400, httponly=True,
                        secure=config.SECURE_COOKIES, samesite="lax", path="/")


def _email(raw: str) -> str:
    email = accounts.normalise_email(raw)
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "Enter a valid email address.")
    return email


def _name(raw: str) -> str:
    name = " ".join(raw.split())[:60]
    if not name:
        raise HTTPException(400, "Enter your name.")
    return name


def _bad(e: AccountError):
    return HTTPException(400, str(e))


# ---------- public ----------

@router.get("/public-config")
def public_config():
    return {"turnstile_site_key": config.TURNSTILE_SITE_KEY, "terms_version": config.TERMS_VERSION,
            "daily_shipments": config.DAILY_SHIPMENTS, "retention_days": config.RETENTION_DAYS,
            "doc_timeout": config.DOC_TIMEOUT, "shipment_timeout": config.SHIPMENT_TIMEOUT,
            "queue_timeout": config.QUEUE_TIMEOUT, "contact_email": config.CONTACT_EMAIL}


class Signup(BaseModel):
    name: str
    email: str
    password: str
    accept_terms: bool = False
    turnstile: str | None = None


@router.post("/auth/signup")
def signup(body: Signup, request: Request, tasks: BackgroundTasks):
    limits.hit("signup", ip(request))
    if not body.accept_terms:
        raise HTTPException(400, "Please accept the Terms of Use and Privacy Policy.")
    if not mailer.turnstile_ok(body.turnstile, ip(request)):
        raise HTTPException(400, "The bot check failed. Please try again.")
    email, name = _email(body.email), _name(body.name)
    try:
        user = accounts.create_user(email, name, body.password)
        tasks.add_task(mailer.verification, email, name, accounts.issue_token(user["id"], "verify"))
    except AccountError as e:
        if str(e) != "exists":
            raise _bad(e)
        tasks.add_task(mailer.already_registered, email)   # same answer either way: no account probing
    return {"ok": True, "message": f"We sent a confirmation link to {email}. Open it to finish signing up."}


class Login(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    limits.hit("login", ip(request))
    limits.hit("login_email", accounts.normalise_email(body.email))
    user = accounts.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(400, "That email and password do not match.")
    _set_cookie(response, accounts.create_session(user["id"]))
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    accounts.end_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


class Token(BaseModel):
    token: str


@router.post("/auth/verify")
def verify(body: Token, response: Response):
    uid = accounts.use_token(body.token, "verify")
    if not uid:
        raise HTTPException(400, "This confirmation link has expired or was already used. Log in to get a new one.")
    accounts.update_user(uid, verified=1)
    _set_cookie(response, accounts.create_session(uid))
    return {"ok": True}


@router.post("/auth/resend-verification")
def resend(request: Request, tasks: BackgroundTasks, user: dict = Depends(current_user)):
    limits.hit("email", user["id"])
    if not user["verified"]:
        tasks.add_task(mailer.verification, user["email"], user["name"], accounts.issue_token(user["id"], "verify"))
    return {"ok": True}


class Forgot(BaseModel):
    email: str
    turnstile: str | None = None


@router.post("/auth/forgot")
def forgot(body: Forgot, request: Request, tasks: BackgroundTasks):
    limits.hit("email", ip(request))
    if not mailer.turnstile_ok(body.turnstile, ip(request)):
        raise HTTPException(400, "The bot check failed. Please try again.")
    user = accounts.user_by_email(body.email)
    if user:
        tasks.add_task(mailer.password_reset, user["email"], accounts.issue_token(user["id"], "reset"))
    return {"ok": True, "message": "If an account uses that email, we sent it a link to reset the password."}


class Reset(BaseModel):
    token: str
    password: str


@router.post("/auth/reset")
def reset(body: Reset, response: Response):
    try:
        accounts.check_password(body.password)
    except AccountError as e:
        raise _bad(e)
    uid = accounts.use_token(body.token, "reset")
    if not uid:
        raise HTTPException(400, "This reset link has expired or was already used. Ask for a new one.")
    accounts.set_password(uid, body.password)
    accounts.update_user(uid, verified=1)   # they proved they read this inbox
    _set_cookie(response, accounts.create_session(uid))
    return {"ok": True}


# ---------- the signed-in person ----------

@router.get("/me")
def me(user: dict = Depends(current_user)):
    ws = accounts.current_workspace(user)
    spaces = accounts.workspaces_of(user["id"])
    role = next(w["role"] for w in spaces if w["id"] == ws)
    return {
        "id": user["id"], "name": user["name"], "email": user["email"], "verified": bool(user["verified"]),
        "notify_email": bool(user["notify_email"]), "role": user["role"],
        "needs_terms": user["terms_version"] != config.TERMS_VERSION,
        "quota": jobs.quota(user),
        "workspace": {"id": ws, "role": role, "name": next(w["name"] for w in spaces if w["id"] == ws),
                      "members": accounts.members(ws), "invites": accounts.invites(ws) if role == "owner" else []},
        "workspaces": spaces, "vapid_public_key": config.VAPID_PUBLIC_KEY,
    }


class Settings(BaseModel):
    name: str | None = None
    notify_email: bool | None = None


@router.patch("/me")
def update_me(body: Settings, user: dict = Depends(current_user)):
    changes = {}
    if body.name is not None:
        changes["name"] = _name(body.name)
    if body.notify_email is not None:
        changes["notify_email"] = int(body.notify_email)
    accounts.update_user(user["id"], **changes)
    return {"ok": True}


class Password(BaseModel):
    current: str
    new: str


@router.post("/me/password")
def change_password(body: Password, request: Request, response: Response, user: dict = Depends(current_user)):
    limits.hit("login_email", user["email"])
    if not accounts.authenticate(user["email"], body.current):
        raise HTTPException(400, "Your current password is not correct.")
    try:
        accounts.set_password(user["id"], body.new)
    except AccountError as e:
        raise _bad(e)
    _set_cookie(response, accounts.create_session(user["id"]))   # this browser stays signed in
    return {"ok": True}


@router.post("/me/accept-terms")
def accept_terms(user: dict = Depends(current_user)):
    accounts.update_user(user["id"], terms_version=config.TERMS_VERSION, terms_at=time.time())
    return {"ok": True}


@router.post("/me/logout-everywhere")
def logout_everywhere(response: Response, user: dict = Depends(current_user)):
    accounts.end_all_sessions(user["id"])
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


class Confirm(BaseModel):
    password: str


@router.post("/me/delete")
def delete_me(body: Confirm, response: Response, user: dict = Depends(current_user)):
    """Delete the account, the workspace it owns and every shipment in it, immediately."""
    limits.hit("login_email", user["email"])
    if not accounts.authenticate(user["email"], body.password):
        raise HTTPException(400, "Your password is not correct.")
    for sid in accounts.delete_user(user["id"]):
        retention.erase_shipment(sid)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


class PushSub(BaseModel):
    endpoint: str
    keys: dict


@router.post("/me/push")
def add_push(body: PushSub, user: dict = Depends(active_user)):
    limits.hit("push", user["id"])
    if not body.endpoint.startswith("https://") or not {"p256dh", "auth"} <= body.keys.keys():
        raise HTTPException(400, "Invalid push subscription")
    accounts.add_push(user["id"], body.endpoint, body.keys["p256dh"], body.keys["auth"])
    return {"ok": True}


@router.post("/me/push/remove")
def remove_push(body: PushSub, user: dict = Depends(current_user)):
    if any(s["endpoint"] == body.endpoint for s in accounts.push_subs(user["id"])):
        accounts.remove_push(body.endpoint)
    return {"ok": True}


# ---------- workspaces ----------

def _owner_workspace(user: dict) -> str:
    ws = accounts.current_workspace(user)
    if accounts.role_in(ws, user["id"]) != "owner":
        raise HTTPException(403, "Only the workspace owner can do this.")
    return ws


class Switch(BaseModel):
    workspace_id: str


@router.post("/workspaces/switch")
def switch(body: Switch, user: dict = Depends(active_user)):
    if not accounts.role_in(body.workspace_id, user["id"]):
        raise HTTPException(404, "Workspace not found")
    accounts.update_user(user["id"], current_workspace=body.workspace_id)
    return {"ok": True}


class Rename(BaseModel):
    name: str


@router.post("/workspaces/rename")
def rename(body: Rename, user: dict = Depends(active_user)):
    accounts.rename_workspace(_owner_workspace(user), _name(body.name))
    return {"ok": True}


class Invite(BaseModel):
    email: str


@router.post("/workspaces/invites")
def invite(body: Invite, tasks: BackgroundTasks, user: dict = Depends(active_user)):
    ws = _owner_workspace(user)
    limits.hit("email", user["id"])
    email = _email(body.email)
    try:
        token = accounts.create_invite(ws, email, user["id"])
    except AccountError as e:
        raise _bad(e)
    name = next(w["name"] for w in accounts.workspaces_of(user["id"]) if w["id"] == ws)
    tasks.add_task(mailer.invitation, email, user["name"], name, token)
    return {"ok": True, "message": f"Invitation sent to {email}."}


@router.post("/workspaces/invites/cancel")
def cancel_invite(body: Invite, user: dict = Depends(active_user)):
    accounts.cancel_invite(_owner_workspace(user), accounts.normalise_email(body.email))
    return {"ok": True}


@router.post("/workspaces/invite-details")
def invite_details(body: Token):
    inv = accounts.invite_details(body.token)
    if not inv:
        raise HTTPException(404, "This invitation has expired or was cancelled.")
    return {"email": inv["email"], "workspace": inv["workspace"], "invited_by": inv["invited_by"]}


@router.post("/workspaces/join")
def join(body: Token, user: dict = Depends(active_user)):
    try:
        accounts.accept_invite(body.token, user)
    except AccountError as e:
        raise _bad(e)
    return {"ok": True}


class Member(BaseModel):
    user_id: str


@router.post("/workspaces/remove-member")
def remove_member(body: Member, user: dict = Depends(active_user)):
    """The owner removes someone, or a member leaves (removes themselves)."""
    ws = accounts.current_workspace(user)
    if body.user_id != user["id"] and accounts.role_in(ws, user["id"]) != "owner":
        raise HTTPException(403, "Only the workspace owner can remove members.")
    if accounts.role_in(ws, body.user_id) == "owner":
        raise HTTPException(400, "The owner cannot leave their own workspace.")
    accounts.remove_member(ws, body.user_id)
    return {"ok": True}
