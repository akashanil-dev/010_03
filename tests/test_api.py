"""Accounts, data isolation, workspaces, limits and the queue through the HTTP API. Run: pytest -q"""

import re

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import accounts, config, jobs, mailer, store
from app.main import app


def client() -> TestClient:
    return TestClient(app)


def token_from_last_email(kind: str) -> str:
    return re.search(rf"#{kind}=([\w-]+)", mailer.SENT[-1]["text"]).group(1)


def signed_up(name: str, email: str) -> TestClient:
    c = client()
    r = c.post("/api/auth/signup", json={"name": name, "email": email, "password": "correct horse 1",
                                         "accept_terms": True})
    assert r.status_code == 200, r.text
    assert c.post("/api/auth/verify", json={"token": token_from_last_email("verify")}).status_code == 200
    return c


def pdf_bytes(text: str = "COMMERCIAL INVOICE") -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def upload(c: TestClient, name: str = "invoice.pdf"):
    return c.post("/api/shipments", files=[("files", (name, pdf_bytes(), "application/pdf"))])


# ---------- accounts ----------

def test_signup_verify_login_logout():
    c = client()
    assert c.get("/api/me").status_code == 401
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "Asha@Example.com", "password": "short",
                                         "accept_terms": True})
    assert r.status_code == 400 and "10 characters" in r.json()["detail"]
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "Asha@Example.com", "password": "long enough 1",
                                         "accept_terms": False})
    assert r.status_code == 400
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "Asha@Example.com", "password": "long enough 1",
                                         "accept_terms": True})
    assert r.status_code == 200 and mailer.SENT[-1]["to"] == "asha@example.com"

    # Not verified yet: can log in, but cannot run checks
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "long enough 1"}).status_code == 200
    me = c.get("/api/me").json()
    assert me["verified"] is False and me["quota"]["left"] == config.DAILY_SHIPMENTS
    assert c.post("/api/demo/clean").status_code == 403

    assert c.post("/api/auth/verify", json={"token": token_from_last_email("verify")}).status_code == 200
    assert c.get("/api/me").json()["verified"] is True
    assert c.post("/api/auth/verify", json={"token": "used-or-wrong"}).status_code == 400

    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong password"}).status_code == 400


def test_signup_does_not_reveal_existing_accounts():
    signed_up("Asha", "asha@example.com")
    r = client().post("/api/auth/signup", json={"name": "X", "email": "asha@example.com",
                                                "password": "another pass 1", "accept_terms": True})
    assert r.status_code == 200 and "sent a confirmation link" in r.json()["message"]
    assert mailer.SENT[-1]["subject"] == "You already have a TallyTime account"


def test_login_is_rate_limited_per_email():
    signed_up("Asha", "asha@example.com")
    c = client()
    codes = [c.post("/api/auth/login", json={"email": "asha@example.com", "password": "nope nope nope"}).status_code
             for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429


def test_password_reset_ends_other_sessions():
    old = signed_up("Asha", "asha@example.com")
    r = client().post("/api/auth/forgot", json={"email": "asha@example.com"})
    assert r.status_code == 200
    c = client()
    assert c.post("/api/auth/reset", json={"token": token_from_last_email("reset"), "password": "brand new pass"}).status_code == 200
    assert c.get("/api/me").status_code == 200
    assert old.get("/api/me").status_code == 401
    assert client().post("/api/auth/forgot", json={"email": "nobody@example.com"}).status_code == 200   # no probing


def test_cross_site_writes_are_refused():
    c = signed_up("Asha", "asha@example.com")
    assert c.post("/api/demo/clean", headers={"Origin": "https://evil.example"}).status_code == 403


# ---------- isolation ----------

def test_other_accounts_cannot_see_a_shipment():
    a, b = signed_up("Asha", "asha@example.com"), signed_up("Bilal", "bilal@example.com")
    sid = upload(a).json()["id"]
    assert a.get(f"/api/shipments/{sid}").status_code == 200
    for method, url in [("get", f"/api/shipments/{sid}"), ("get", f"/api/shipments/{sid}/files/invoice.pdf"),
                        ("post", f"/api/shipments/{sid}/cancel"), ("delete", f"/api/shipments/{sid}")]:
        assert getattr(b, method)(url).status_code == 404, url
    r = b.post(f"/api/shipments/{sid}/reviews", json={"check_id": "x", "decision": "confirmed"})
    assert r.status_code == 404
    assert b.get("/api/queue").json()["jobs"] == []
    assert store.get(sid) is not None   # B's delete did nothing


def test_workspace_invite_shares_shipments():
    a, b = signed_up("Asha", "asha@example.com"), signed_up("Bilal", "bilal@example.com")
    sid = upload(a).json()["id"]
    r = a.post("/api/workspaces/invites", json={"email": "bilal@example.com"})
    assert r.status_code == 200
    token = token_from_last_email("invite")
    assert a.get("/api/me").json()["workspace"]["invites"][0]["email"] == "bilal@example.com"

    # Only the invited email can accept
    c = signed_up("Chitra", "chitra@example.com")
    assert c.post("/api/workspaces/join", json={"token": token}).status_code == 400
    assert b.post("/api/workspaces/join", json={"token": token}).status_code == 200
    me = b.get("/api/me").json()
    assert me["workspace"]["name"] == "Asha's workspace" and me["workspace"]["role"] == "member"
    assert {m["name"] for m in me["workspace"]["members"]} == {"Asha", "Bilal"}
    assert b.get(f"/api/shipments/{sid}").status_code == 200
    assert b.get("/api/queue").json()["jobs"][0]["shipment_id"] == sid
    # A member cannot cancel someone else's check or invite people
    assert b.post(f"/api/shipments/{sid}/cancel").status_code == 403
    assert b.post("/api/workspaces/invites", json={"email": "d@example.com"}).status_code == 403

    # Removed: no longer visible, and back in their own workspace
    member = next(m for m in me["workspace"]["members"] if m["name"] == "Bilal")
    assert a.post("/api/workspaces/remove-member", json={"user_id": member["id"]}).status_code == 200
    assert b.get(f"/api/shipments/{sid}").status_code == 404
    assert b.get("/api/me").json()["workspace"]["name"] == "Bilal's workspace"


def test_reviews_record_the_account():
    a = signed_up("Asha", "asha@example.com")
    sid = upload(a).json()["id"]
    from app.report import build
    from tests.fixtures import errors_docs
    store.finish(sid, build(errors_docs()), "x")
    cid = next(c["id"] for c in store.get(sid)["report"]["checks"] if c["status"] == "error")
    r = a.post(f"/api/shipments/{sid}/reviews", json={"check_id": cid, "decision": "confirmed", "reviewer": "Anjali, Accounts"})
    assert r.status_code == 200
    entry = a.get(f"/api/shipments/{sid}").json()["audit"][0]
    assert entry["reviewer"] == "Anjali, Accounts" and entry["account"] == "Asha"


def test_delete_account_erases_everything(isolated):
    a = signed_up("Asha", "asha@example.com")
    sid = upload(a).json()["id"]
    assert (isolated / "uploads" / sid).exists()
    assert a.post("/api/me/delete", json={"password": "wrong"}).status_code == 400
    assert a.post("/api/me/delete", json={"password": "correct horse 1"}).status_code == 200
    assert store.get(sid) is None and not (isolated / "uploads" / sid).exists()
    assert accounts.user_by_email("asha@example.com") is None
    assert a.get("/api/me").status_code == 401


# ---------- limits and queue ----------

def test_daily_quota_and_demo_runs(monkeypatch):
    monkeypatch.setattr(config, "MAX_ACTIVE_PER_USER", 50)
    a = signed_up("Asha", "asha@example.com")
    for i in range(config.DAILY_SHIPMENTS):
        assert upload(a, f"inv{i}.pdf").status_code == 200
    r = upload(a, "one-more.pdf")
    assert r.status_code == 429 and "resets at midnight" in r.json()["detail"]
    assert a.post("/api/demo/clean").status_code == 200   # demos do not count
    assert a.get("/api/me").json()["quota"]["left"] == 0


def test_active_checks_per_account():
    a = signed_up("Asha", "asha@example.com")
    for i in range(config.MAX_ACTIVE_PER_USER):
        assert a.post("/api/demo/clean").status_code == 200
    r = a.post("/api/demo/clean")
    assert r.status_code == 429 and "running or waiting" in r.json()["detail"]


def test_busy_queue_refuses_new_checks(monkeypatch):
    monkeypatch.setattr(config, "BUSY_BACKLOG", 1)
    a = signed_up("Asha", "asha@example.com")
    assert a.post("/api/demo/clean").status_code == 200
    assert a.post("/api/demo/clean").status_code == 503


def test_cancel_waiting_check_gives_quota_back():
    a = signed_up("Asha", "asha@example.com")
    sid = upload(a).json()["id"]
    assert a.get("/api/me").json()["quota"]["used"] == 1
    assert a.post(f"/api/shipments/{sid}/cancel").json()["state"] == "cancelled"
    assert a.get(f"/api/shipments/{sid}").json()["state"] == "cancelled"
    assert a.get("/api/me").json()["quota"]["used"] == 0
    assert a.post(f"/api/shipments/{sid}/cancel").status_code == 400


def test_queue_positions_and_estimates():
    a, b = signed_up("Asha", "asha@example.com"), signed_up("Bilal", "bilal@example.com")
    first = upload(a).json()["id"]
    second = upload(b).json()["id"]
    assert jobs.claim_next()["shipment_id"] == first
    assert jobs.claim_next() is None   # one at a time
    mine = b.get("/api/queue").json()
    assert mine["waiting"] == 1 and mine["busy"] is True
    job = mine["jobs"][0]
    assert job["shipment_id"] == second and job["ahead"] == 1 and job["starts_in"] > 0 and job["eta"] > job["starts_in"]
    running = a.get(f"/api/shipments/{first}").json()
    assert running["state"] == "processing" and running["job"]["state"] == "running"
    assert running["files"][0]["percent"] == 0 and running["files"][0]["eta"] > 0


def test_running_check_cancel_is_requested_and_restart_requeues():
    a = signed_up("Asha", "asha@example.com")
    sid = upload(a).json()["id"]
    job = jobs.claim_next()
    assert a.post(f"/api/shipments/{sid}/cancel").json()["state"] == "cancelling"
    assert jobs.stop_reason(job["id"]) == "cancelled"
    jobs.requeue_running()
    assert jobs.for_shipment(sid)["state"] == "queued"


def test_waiting_too_long_is_cancelled_and_refunded(monkeypatch):
    a = signed_up("Asha", "asha@example.com")
    sid = upload(a).json()["id"]
    import time
    expired = jobs.expire_waiting(time.time() + config.QUEUE_TIMEOUT + 1)
    assert [j["shipment_id"] for j in expired] == [sid]
    assert store.get(sid)["state"] == "cancelled" and a.get("/api/me").json()["quota"]["used"] == 0


def test_api_docs_need_login():
    assert client().get("/docs").status_code == 401
    assert signed_up("Asha", "asha@example.com").get("/openapi.json").status_code == 200


@pytest.mark.parametrize("path", ["/privacy.html", "/terms.html", "/about.html"])
def test_public_pages(path):
    r = client().get(path)
    assert r.status_code == 200 and config.CONTACT_EMAIL in r.text
