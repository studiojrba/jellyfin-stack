#!/usr/bin/env bash
# Diagnose persistent TorBox HTTP 429 rate-limiting via decypharr.
# Read-only: counts 429s over time, identifies whether the traffic is a background
# bulk link-refresh (decypharr) vs on-demand reads (Jellyfin/*arr), and prints the
# live decypharr rate-limit settings so they can be compared to TorBox's real limits.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

COMPOSE="${COMPOSE:-docker compose}"
SINCE="${SINCE:-12h}"

sep() { echo; echo "=== $* ==="; }

sep "1. 429 errors per hour (last $SINCE of decypharr logs)"
# shellcheck disable=SC2086
$COMPOSE logs --since "$SINCE" -t decypharr 2>&1 | grep 'HTTP 429' \
  | sed -E 's/.*([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}).*/\1:00/' | sort | uniq -c \
  || echo "(no 429s found in the window)"

sep "2. Distinct files that got 429s (top 20 by attempts)"
# shellcheck disable=SC2086
$COMPOSE logs --since "$SINCE" decypharr 2>&1 | grep 'HTTP 429' \
  | sed -E 's/.*Error streaming file: ([^"]*) error=.*/\1/' | sort | uniq -c | sort -rn | head -20 \
  || echo "(none)"

sep "3. Same-file retry loops? (files 429ing more than 5 times)"
# shellcheck disable=SC2086
loops="$($COMPOSE logs --since "$SINCE" decypharr 2>&1 | grep 'HTTP 429' \
  | sed -E 's/.*Error streaming file: ([^"]*) error=.*/\1/' | sort | uniq -c | awk '$1 > 5' | wc -l)"
echo "files with >5 429 attempts: $loops"
echo "(high count = something is retrying the same files in a loop, keeping the limit tripped)"

sep "4. Live decypharr rate-limit settings (config/decypharr/config.json)"
if [ -f config/decypharr/config.json ]; then
  python3 - <<'EOF'
import json
cfg = json.load(open("config/decypharr/config.json"))
for d in cfg.get("debrids", []):
    print(f"provider={d.get('provider')}")
    for k in ("rate_limit", "download_rate_limit", "download_links_refresh_interval",
              "workers", "auto_expire_links_after", "torrents_refresh_interval"):
        print(f"  {k} = {d.get(k)}")
rep = cfg.get("repair") or {}
print(f"repair.recheck_interval = {rep.get('recheck_interval')}, repair.workers = {rep.get('workers')}")
EOF
else
  echo "(config/decypharr/config.json not found)"
fi

sep "5. Other link-request traffic in the window (non-429 activity, sample)"
# shellcheck disable=SC2086
$COMPOSE logs --since "$SINCE" decypharr 2>&1 | grep -iE 'refresh|repair|link' | grep -v 'HTTP 429' | tail -15 \
  || echo "(none)"

sep "6. What to do with the results"
cat <<'EOF'
- 429s clustered in one hour, then quiet         -> one-off scan burst; the limit should clear.
- 429s in EVERY hour of the window               -> background traffic keeps re-tripping the limit.
  Usual culprits, in order:
    1. decypharr bulk link refresh: lower "workers" (e.g. 300 -> 10) and/or raise
       "download_links_refresh_interval" (e.g. 24h -> 72h) in config/decypharr/config.json.
    2. "download_rate_limit" set above TorBox's real limit: lower it (e.g. 90/minute -> 10/minute)
       so decypharr backs off instead of hammering.
    3. Jellyfin deep-read scheduled tasks (trickplay/chapter images): run `python3 op_audit.py`
       and disarm anything flagged DANGER.
  After editing config/decypharr/config.json: `docker compose restart decypharr`, then restart
  the rslave consumers (jellyfin, sonarr, radarr, onepace-maintenance) so the new mount propagates.
- Also check https://torbox.app dashboard for plan-level API/link quotas.
EOF
