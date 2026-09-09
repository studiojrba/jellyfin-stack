#!/usr/bin/env bash
# Recover from Docker Desktop/WSL bind-mount restart failures like:
#   error while creating mount source path ... docker-desktop-bind-mounts ... file exists
#
# This is the targeted version of the full stack recreate: it force-recreates decypharr
# first so the updated config + FUSE mount come back, waits for /mnt/remote, then
# force-recreates rslave consumers so they inherit the fresh mount propagation.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

COMPOSE="${COMPOSE:-docker compose}"

sep() { echo; echo "=== $* ==="; }

compose() {
  # shellcheck disable=SC2086
  $COMPOSE "$@"
}

wait_for_decypharr_mount() {
  sep "Waiting for decypharr mount"
  for i in $(seq 1 24); do
    count="$(compose exec -T decypharr sh -lc 'ls /mnt/remote/__all__ 2>/dev/null | wc -l' 2>/dev/null || true)"
    count="${count:-0}"
    echo "t=$((i * 5))s decypharr /mnt/remote/__all__ entries: $count"
    if [ "$count" -gt 0 ] 2>/dev/null; then
      return 0
    fi
    sleep 5
  done
  echo "ERROR: decypharr mount did not become visible."
  compose logs --tail 80 decypharr 2>&1 | grep -iE 'error|mount|fuse|rclone|torbox|unmount|bind' | tail -50 || true
  return 1
}

sep "Current status"
compose ps decypharr jellyfin sonarr radarr onepace-maintenance || true

sep "Force-recreating decypharr with current config"
compose up -d --force-recreate decypharr || exit 1

wait_for_decypharr_mount || exit 1

sep "Force-recreating rslave consumers after decypharr mount is live"
compose up -d --force-recreate jellyfin sonarr radarr onepace-maintenance || exit 1

sep "Final status"
compose ps decypharr jellyfin sonarr radarr onepace-maintenance || true

sep "DONE"
echo "Updated decypharr config is applied. Do not full-scan Jellyfin while TorBox is 429ing."
echo "Wait for the TorBox cooldown/quota reset, then test one Sabaody episode."
