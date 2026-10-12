"""Tell the person who started a check that it has finished: Web Push to their browsers, and email if they
turned it on. Push messages are end-to-end encrypted to the browser; emails carry only a link.

Generate the VAPID key pair once with:  python -m app.notify keys
"""

import base64
import json
import logging

from . import accounts, config, mailer

log = logging.getLogger("tallytime.notify")

OUTCOME = {"ready": "ready to file", "review": "needs review", "blocked": "fix before filing"}


def outcome_text(state: str, verdict: str | None = None) -> str:
    if state == "done":
        return f"Your shipment check is finished: {OUTCOME.get(verdict, 'see the results')}"
    if state == "timed_out":
        return "Your shipment check was stopped because it took too long"
    if state == "expired":
        return "Your shipment check was cancelled because it waited too long to start"
    return "Your shipment check could not be completed"


def job_finished(user_id: str | None, sid: str, state: str, verdict: str | None = None, label: str = "") -> None:
    user = accounts.get_user(user_id) if user_id else None
    if not user:
        return
    text = outcome_text(state, verdict)
    push(user["id"], {"title": "TallyTime", "body": f"{text}." + (f"\n{label}" if label else ""),
                      "url": f"/#{sid}", "tag": sid})
    if user["notify_email"] and user["verified"]:
        mailer.check_finished(user["email"], user["name"], sid, text)


def push(user_id: str, payload: dict) -> int:
    """Send to every browser the person subscribed. Returns how many accepted it."""
    if not config.VAPID_PRIVATE_KEY:
        return 0
    from pywebpush import WebPushException, webpush

    sent = 0
    for sub in accounts.push_subs(user_id):
        try:
            webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=json.dumps(payload), vapid_private_key=config.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": config.VAPID_SUBJECT}, ttl=6 * 3600)
            sent += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):   # unsubscribed or expired
                accounts.remove_push(sub["endpoint"])
            else:
                log.warning("Push failed: %s", e)
        except Exception:
            log.exception("Push failed")
    return sent


def generate_keys() -> tuple[str, str]:
    """(public key for the browser, private key for the server), both base64url."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64(public), b64(key.private_numbers().private_value.to_bytes(32, "big"))


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["keys"]:
        pub, priv = generate_keys()
        print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}")
    else:
        print("Usage: python -m app.notify keys")
