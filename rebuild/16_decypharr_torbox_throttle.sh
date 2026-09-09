#!/usr/bin/env bash
# Safely lower decypharr's TorBox link-request concurrency/rate settings.
#
# Why: a full Jellyfin scan of One Pace can make decypharr request hundreds of
# TorBox download links in a burst. The previous defaults (workers=300,
# download_rate_limit=90/minute, download_links_refresh_interval=24h) are too
# aggressive for a rate-limited account and can leave playback stuck on HTTP 429.
#
# Run from the host with this repo checked out:
#   bash rebuild/16_decypharr_torbox_throttle.sh
#
# Override defaults if needed:
#   TORBOX_WORKERS=5 TORBOX_DOWNLOAD_RATE_LIMIT=5/minute bash rebuild/16_decypharr_torbox_throttle.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

CONFIG="${CONFIG:-config/decypharr/config.json}"
WORKERS="${TORBOX_WORKERS:-10}"
DOWNLOAD_RATE_LIMIT="${TORBOX_DOWNLOAD_RATE_LIMIT:-10/minute}"
LINK_REFRESH_INTERVAL="${TORBOX_LINK_REFRESH_INTERVAL:-72h}"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: missing $CONFIG"
  exit 1
fi

backup="${CONFIG}.bak-$(date +%Y%m%d-%H%M%S)"
cp "$CONFIG" "$backup" || exit 1

python3 - "$CONFIG" "$WORKERS" "$DOWNLOAD_RATE_LIMIT" "$LINK_REFRESH_INTERVAL" <<'PY'
import json
import sys

path, workers, download_rate_limit, link_refresh_interval = sys.argv[1:]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

changed = []
for debrid in cfg.get("debrids", []):
    if debrid.get("provider") != "torbox":
        continue
    updates = {
        "workers": int(workers),
        "download_rate_limit": download_rate_limit,
        "download_links_refresh_interval": link_refresh_interval,
    }
    for key, new_value in updates.items():
        old_value = debrid.get(key)
        if old_value != new_value:
            debrid[key] = new_value
            changed.append((key, old_value, new_value))

with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")

if not changed:
    print("No TorBox throttle settings changed; config already matches requested values.")
else:
    print("Updated TorBox throttle settings:")
    for key, old, new in changed:
        print(f"  {key}: {old!r} -> {new!r}")
PY

echo
echo "Backup written: $backup"
echo
echo "Next commands to apply the config:"
echo "  docker compose restart decypharr"
echo "  sleep 30"
echo "  docker compose restart jellyfin sonarr radarr onepace-maintenance"
echo
echo "Then avoid full Jellyfin scans while TorBox is still returning HTTP 429."
