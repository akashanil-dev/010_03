"""Outgoing email through Brevo's SMTP relay. Without SMTP settings, emails are logged instead (development).

Emails never contain document contents: only links back to the site.
"""

import json
import logging
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import make_msgid

from . import config

log = logging.getLogger("tallytime.mail")
SENT: list[dict] = []   # development and tests: what would have been sent


def send(to: str, subject: str, text: str) -> None:
    if not config.SMTP_HOST:
        SENT.append({"to": to, "subject": subject, "text": text})
        log.warning("Email (SMTP not configured) to %s: %s\n%s", to, subject, text)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.MAIL_FROM, to, subject
    msg["Message-ID"] = make_msgid(domain=config.MAIL_FROM.split("@")[-1].strip(">"))
    msg.set_content(text + f"\n\n--\nTallyTime · {config.PUBLIC_URL}\n")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    except Exception:
        log.exception("Could not send email to %s", to)


def link(path: str) -> str:
    return f"{config.PUBLIC_URL}/{path.lstrip('/')}"


def verification(to: str, name: str, token: str) -> None:
    send(to, "Confirm your email for TallyTime",
         f"Hello {name},\n\nConfirm your email to start checking export documents:\n\n"
         f"{link('#verify=' + token)}\n\nThe link works for 3 days. If you did not sign up, ignore this email.")


def already_registered(to: str) -> None:
    send(to, "You already have a TallyTime account",
         f"Someone (probably you) tried to sign up with this email, but you already have an account.\n\n"
         f"Log in: {link('#login')}\nForgot your password? {link('#forgot')}\n\n"
         "If this was not you, you can ignore this email.")


def password_reset(to: str, token: str) -> None:
    send(to, "Reset your TallyTime password",
         f"Use this link to choose a new password:\n\n{link('#reset=' + token)}\n\n"
         "The link works for 1 hour. If you did not ask for this, ignore this email; your password is unchanged.")


def invitation(to: str, inviter: str, workspace: str, token: str) -> None:
    send(to, f"{inviter} invited you to review export documents on TallyTime",
         f"{inviter} invited you to the workspace \"{workspace}\" on TallyTime, where you can review "
         f"shipment checks together.\n\nAccept: {link('#invite=' + token)}\n\n"
         f"Sign up or log in with this email address ({to}). The invitation expires in 7 days.")


def check_finished(to: str, name: str, sid: str, outcome: str) -> None:
    send(to, f"TallyTime: {outcome}",
         f"Hello {name},\n\n{outcome}.\n\nOpen it: {link('#' + sid)}\n\n"
         "You can turn these emails off in your account settings.")


def turnstile_ok(token: str | None, ip: str | None) -> bool:
    """Cloudflare Turnstile bot check. Always passes when Turnstile is not configured."""
    if not config.TURNSTILE_SECRET:
        return True
    if not token:
        return False
    data = urllib.parse.urlencode({"secret": config.TURNSTILE_SECRET, "response": token, "remoteip": ip or ""}).encode()
    try:
        with urllib.request.urlopen("https://challenges.cloudflare.com/turnstile/v0/siteverify", data, timeout=10) as r:
            return bool(json.load(r).get("success"))
    except Exception:
        log.exception("Turnstile check failed")
        return False
