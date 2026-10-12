"""Settings for the public deployment, read from the environment (.env). Defaults suit local development."""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
SECURE_COOKIES = urlparse(PUBLIC_URL).scheme == "https"

# Limits (Phase 3)
DAILY_SHIPMENTS = _int("DAILY_SHIPMENTS", 5)          # per account, resets at midnight IST
MAX_ACTIVE_PER_USER = _int("MAX_ACTIVE_PER_USER", 3)  # running + waiting checks per account
DOC_TIMEOUT = _int("DOC_TIMEOUT", 300)                # seconds one document may take
SHIPMENT_TIMEOUT = _int("SHIPMENT_TIMEOUT", 1800)     # seconds a whole check may take once started
QUEUE_TIMEOUT = _int("QUEUE_TIMEOUT", 7200)           # seconds a check may wait before it starts
BUSY_BACKLOG = _int("BUSY_BACKLOG", 7200)             # refuse new checks when this much work is waiting
TIMEZONE = os.getenv("QUOTA_TIMEZONE", "Asia/Kolkata")

# Retention (Phase 5)
RETENTION_DAYS = _int("RETENTION_DAYS", 7)
TERMS_VERSION = "2026-10-12"   # bump when the terms or privacy policy change; users re-accept

# Email through Brevo SMTP. Without SMTP_HOST, emails are written to the log instead (development).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "TallyTime <no-reply@akashanil.dev>")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "privacy@akashanil.dev")

# Cloudflare Turnstile bot check on sign-up and password reset. Skipped when not configured.
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET", "")

# Web Push. Generate keys with: python -m app.notify keys
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", f"mailto:{CONTACT_EMAIL}")
