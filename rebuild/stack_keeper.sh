#!/usr/bin/env bash
# jellyfin-stack keeper (mini PC / jerba-server, native Docker).
#
# Two standing safety nets, run together on a timer + at boot:
#   1) MOUNT HEALTH: detect decypharr's rclone FUSE mount going stale (e.g. after a
#      decypharr restart/crash), clear it, and re-propagate to consumer containers.
#      Signature: consumers see 0 entries under /mnt/remote even though decypharr is up,
#      or the host mountpoint returns "Transport endpoint is not connected".
#   2) SYMLINK HEALTH: idempotently rebuild any missing Sonarr/Radarr library symlinks
#      from cached mount content (arr_symlink_rebuild.py). No-op when nothing is missing.
# A Jellyfin rescan fires only when something actually changed.
#
# Holds no secrets: reads JELLYFIN_API_KEY from the gitignored .env at runtime.
set -u
# Portable: resolve the repo root from this script's own location (rebuild/..),
# so the keeper works regardless of where the stack is checked out or which user
# runs it. Override with STACK_REPO if you ever relocate the script itself.
REPO="${STACK_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO" || exit 0
LOG="$REPO/rebuild/stack_keeper.log"
exec >>"$LOG" 2>&1
echo "==================== keeper $(date '+%F %T') ===================="

CONSUMERS="jellyfin sonarr radarr onepace-maintenance"
MERGED="./mount/__all__"

jf_rescan() {
  local key
  key=$(grep -m1 '^JELLYFIN_API_KEY=' .env 2>/dev/null | cut -d= -f2- | tr -d '"'\'' \r')
  [ -z "$key" ] && { echo "  rescan skipped (no JELLYFIN_API_KEY in .env)"; return; }
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    "http://localhost:8096/Library/Refresh" -H "Authorization: MediaBrowser Token=\"$key\"")
  echo "  jellyfin rescan -> HTTP $code"
}

mount_entries() {  # entry count as seen inside jellyfin (the propagated view)
  docker exec jellyfin sh -c 'ls /mnt/remote/__all__ 2>/dev/null | wc -l' 2>/dev/null || echo 0
}

mount_is_stale() {
  # stale if the host mountpoint is a disconnected FUSE endpoint, or decypharr is up
  # but consumers see nothing.
  if ! ls "$MERGED" >/dev/null 2>&1; then return 0; fi          # transport endpoint error
  docker ps --format '{{.Names}}' | grep -q '^decypharr$' || return 1  # decypharr down: leave to compose
  [ "$(mount_entries)" -gt 0 ] && return 1 || return 0
}

heal_mount() {
  echo ">>> stale mount detected -> healing"
  fusermount3 -u ./mount 2>/dev/null || fusermount -u ./mount 2>/dev/null || true
  # `up -d` only starts a stopped container. When decypharr is still running but its
  # internal rclone died (e.g. the cache filled the disk), rclone's RC port stays dead
  # and decypharr's own recovery loop logs "Successfully recovered mount" forever while
  # /mnt/remote stays empty -- so a running-but-empty decypharr needs a real restart.
  if docker exec decypharr sh -c 'ls /mnt/remote/__all__ 2>/dev/null | grep -q .' 2>/dev/null; then
    docker compose up -d decypharr >/dev/null 2>&1
  else
    echo "  decypharr up but its own mount is empty -> restarting it"
    docker compose restart decypharr >/dev/null 2>&1
  fi
  for i in $(seq 1 30); do
    docker exec decypharr sh -c 'ls /mnt/remote/__all__ 2>/dev/null | grep -q .' 2>/dev/null && break
    sleep 3
  done
  echo "  decypharr mount back ($(docker exec decypharr sh -c 'ls /mnt/remote/__all__ | wc -l' 2>/dev/null) entries); restarting consumers"
  docker compose restart $CONSUMERS >/dev/null 2>&1
  for i in $(seq 1 20); do [ "$(mount_entries)" -gt 0 ] && break; sleep 3; done
  echo "  jellyfin now sees $(mount_entries) entries"
}

changed=0

# 1) MOUNT HEALTH
if mount_is_stale; then
  heal_mount; changed=1
else
  echo "mount healthy (jellyfin sees $(mount_entries) entries)"
fi

# 2) SYMLINK HEALTH (idempotent; only rebuilds what's missing)
if ls "$MERGED" >/dev/null 2>&1; then
  out=$(python3 rebuild/arr_symlink_rebuild.py --apply 2>&1)
  created=$(printf '%s\n' "$out" | sed -n 's/.*created=\([0-9]*\).*/\1/p' | tail -1)
  echo "symlink health: ${created:-0} created"
  [ "${created:-0}" -gt 0 ] 2>/dev/null && changed=1
else
  echo "symlink health skipped (mount not readable)"
fi

# 3) QUEUE HEALTH: clear decypharr SAB (usenet) downloads stuck at 100% that never
# fired their completion transition (common after a decypharr restart). Guarded to only
# clear items stuck across >=1 cycle, so a fresh completion is never touched.
if out=$(python3 rebuild/unstick_stuck_queue.py 2>&1); then
  echo "$out"; changed=1          # exit 0 = it cleared something
else
  [ -n "$out" ] && echo "$out"     # exit 2 = nothing to clear (or new-this-cycle)
fi

# 3b) IMPORT HEALTH: force-import downloads stuck at importPending solely because the
# media analyzer couldn't read a runtime off the FUSE symlink ("Unable to determine if
# file is a sample"). Distinct from the SAB-stuck case above: here the download completed
# and only the import stalls. Guarded to sample-ONLY rejections on large, matched files.
if out=$(python3 rebuild/unstick_sample_imports.py 2>&1); then
  echo "$out"; changed=1          # exit 0 = it force-imported something
else
  [ -n "$out" ] && echo "$out"     # exit 2 = nothing stuck on sample check
fi

# 3b-ii) IMPORT HEALTH, the silent variant: items parked at importPending with NO
# rejection at all -- the arr states no objection and still never imports. Step 3b cannot
# see these (it keys off a "sample" status message; these have no status messages), which
# is how 82 of them accumulated unnoticed over six days before 2026-08-04. Paced to stay
# under decypharr's 10/min link limit, so a large backlog drains across several runs.
if out=$(python3 rebuild/unstick_clean_imports.py 2>&1); then
  echo "$out"; changed=1          # exit 0 = it force-imported something
else
  [ -n "$out" ] && echo "$out"     # exit 2 = nothing parked without a rejection
fi

# 3c) INDEXER HEALTH: give up on content whose NZB articles are gone. Those adds are
# rejected by decypharr before the arr records anything (no history, no blocklist), so
# the arr re-fetches the same dead NZBs forever -- which earned an indexer "duplicate
# downloads" warning on 2026-07-27. Unmonitors an episode/movie only after it has burned
# through DEAD_THRESHOLD distinct NNTP-430 releases, and never one that has a file.
# Deliberately does NOT set changed=1: unmonitoring alters no media, so no rescan.
out=$(python3 rebuild/guard_dead_releases.py 2>&1) || true
[ -n "$out" ] && echo "$out"

# 4) Rescan Jellyfin only if something changed
[ "$changed" = 1 ] && jf_rescan || echo "no changes; rescan not needed"
echo "==================== keeper done ===================="
