#!/usr/bin/env bash
# Nightly backup of ACCOUNT data only (accounts, workspaces, members). Documents, results, reviews and the
# queue are removed from the copy, so a backup never keeps shipment data past the 7-day promise.
# Keeps 7 nightly copies. Installed as a cron job by setup.sh.
set -euo pipefail
DB=/opt/tallytime/data/tally.db
OUT=/var/backups/tallytime
mkdir -p "$OUT"
chmod 700 "$OUT"
TMP=$(mktemp "$OUT/.partial.XXXXXX")
sqlite3 "$DB" ".backup '$TMP'"
sqlite3 "$TMP" "DELETE FROM jobs; DELETE FROM audit; DELETE FROM reviews; DELETE FROM files; DELETE FROM shipments;
                DELETE FROM sessions; DELETE FROM tokens; DELETE FROM push_subs; VACUUM;"
mv "$TMP" "$OUT/accounts-$(date +%F).db"
find "$OUT" -name 'accounts-*.db' -mtime +6 -delete
