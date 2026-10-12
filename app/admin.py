"""Server administration from the command line (run on the VM as the tallytime user):

    python -m app.admin stats                   queue, accounts and today's usage
    python -m app.admin users                   list accounts
    python -m app.admin set-limit EMAIL N       daily checks for one account (e.g. a pilot exporter)
    python -m app.admin reset-limit EMAIL       back to the default limit
    python -m app.admin verify EMAIL            confirm an email by hand (if the email never arrived)
    python -m app.admin delete-user EMAIL       delete an account, its workspace and its shipments
    python -m app.admin sweep                   run the retention sweep now
"""

import sys
import time

from . import accounts, config, limits, retention, store
from .store import _db


def stats() -> None:
    with _db() as c:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        print(f"Accounts: {q('SELECT COUNT(*) FROM users')} ({q('SELECT COUNT(*) FROM users WHERE verified = 1')} verified)")
        print(f"Workspaces shared with others: {q('SELECT COUNT(*) FROM (SELECT workspace_id FROM members GROUP BY workspace_id HAVING COUNT(*) > 1)')}")
        print(f"Shipments stored: {q('SELECT COUNT(*) FROM shipments')}")
        waiting = q("SELECT COUNT(*) FROM jobs WHERE state = 'queued'")
        running = q("SELECT COUNT(*) FROM jobs WHERE state = 'running'")
        print(f"Queue: {waiting} waiting, {running} running")
        print(f"Checks used today: {q('SELECT COALESCE(SUM(used), 0) FROM usage WHERE day = ?', limits.today())}")
        for state, n in c.execute("SELECT state, COUNT(*) FROM jobs WHERE finished_at > ? GROUP BY state",
                                  (time.time() - 86400,)):
            print(f"  last 24 h, {state}: {n}")


def users() -> None:
    with _db() as c:
        for r in c.execute("SELECT email, name, verified, daily_limit, created FROM users ORDER BY created"):
            limit = r["daily_limit"] if r["daily_limit"] is not None else f"{config.DAILY_SHIPMENTS} (default)"
            print(f"{r['email']:<40} {r['name']:<24} {'verified' if r['verified'] else 'UNVERIFIED':<11} "
                  f"limit {limit:<14} since {time.strftime('%Y-%m-%d', time.localtime(r['created']))}")


def _user(email: str) -> dict:
    user = accounts.user_by_email(email)
    if not user:
        sys.exit(f"No account with email {email}")
    return user


def main(argv: list[str]) -> None:
    store.init()
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd == "stats":
        stats()
    elif cmd == "users":
        users()
    elif cmd == "set-limit" and len(args) == 2:
        accounts.update_user(_user(args[0])["id"], daily_limit=int(args[1]))
        print(f"{args[0]} can now run {args[1]} checks a day.")
    elif cmd == "reset-limit" and len(args) == 1:
        accounts.update_user(_user(args[0])["id"], daily_limit=None)
        print(f"{args[0]} is back to the default of {config.DAILY_SHIPMENTS} checks a day.")
    elif cmd == "verify" and len(args) == 1:
        accounts.update_user(_user(args[0])["id"], verified=1)
        print(f"{args[0]} is verified.")
    elif cmd == "delete-user" and len(args) == 1:
        for sid in accounts.delete_user(_user(args[0])["id"]):
            retention.erase_shipment(sid)
        print(f"Deleted {args[0]} and their workspace.")
    elif cmd == "sweep":
        print(retention.sweep())
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
