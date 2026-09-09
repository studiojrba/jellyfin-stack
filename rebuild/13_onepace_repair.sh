#!/usr/bin/env bash
# One-command One Pace repair/check for the host running this Compose stack.
#
# What it does:
#   1. Ensures decypharr + onepace-maintenance are running.
#   2. Runs the One Pace maintenance script (re-add, symlink, NFO/poster generation).
#   3. Verifies the host library has symlinks + NFOs.
#   4. Verifies Jellyfin can read a real One Pace symlink target.
#   5. If Jellyfin cannot read it, restarts Jellyfin after decypharr is mounted and retests.
#
# It does not delete Jellyfin metadata. If Jellyfin already cached bad "[One Pace"
# episode items, delete the One Pace series/library in Jellyfin and run this script,
# then scan the Jellyfin library that contains /data/media/anime.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

OP_LIB_HOST="${OP_LIB_HOST:-$ROOT/data/media/anime/One Pace}"
OP_LIB_CONT="${OP_LIB_CONT:-/data/media/anime/One Pace}"
COMPOSE="${COMPOSE:-docker compose}"
# Read tests sample from this season onward (Sabaody Archipelago = Season 22).
OP_MIN_SEASON="${OP_MIN_SEASON:-22}"

sep() { echo; echo "=== $* ==="; }

compose() {
  # shellcheck disable=SC2086
  $COMPOSE "$@"
}

compose_exec() {
  # shellcheck disable=SC2086
  $COMPOSE exec -T "$@"
}

wait_for_decypharr_mount() {
  sep "Waiting for decypharr mount"
  for i in $(seq 1 18); do
    count="$(compose_exec decypharr sh -lc 'ls /mnt/remote/__all__ 2>/dev/null | wc -l' 2>/dev/null || true)"
    count="${count:-0}"
    echo "decypharr /mnt/remote/__all__ entries: $count"
    if [ "$count" -gt 0 ] 2>/dev/null; then
      return 0
    fi
    sleep 5
  done
  echo "ERROR: decypharr mount did not become visible."
  echo "Recent decypharr mount/error logs:"
  compose logs --tail 80 decypharr 2>&1 | grep -iE 'error|mount|fuse|rclone|torbox|403|unmount' | tail -40 || true
  return 1
}

run_maintenance() {
  sep "Running One Pace maintenance"
  compose_exec onepace-maintenance sh /work/op_maint.sh
}

count_library_files() {
  sep "Host library counts"
  if [ ! -d "$OP_LIB_HOST" ]; then
    echo "ERROR: missing host library: $OP_LIB_HOST"
    return 1
  fi

  symlinks="$(find "$OP_LIB_HOST" -maxdepth 2 -type l 2>/dev/null | wc -l | awk '{print $1}')"
  nfos="$(find "$OP_LIB_HOST" -maxdepth 2 -name '*.nfo' 2>/dev/null | wc -l | awk '{print $1}')"
  host_unresolved="$(find "$OP_LIB_HOST" -maxdepth 2 -type l 2>/dev/null | while IFS= read -r lnk; do [ -e "$lnk" ] || echo "$lnk"; done | wc -l | awk '{print $1}')"

  echo "symlinks=$symlinks"
  echo "nfos=$nfos"
  echo "host_unresolved_symlinks=$host_unresolved (expected when links target /mnt/remote container paths)"

  if [ "$symlinks" -eq 0 ] || [ "$nfos" -eq 0 ]; then
    echo "ERROR: One Pace library was not populated."
    return 1
  fi
  return 0
}

jellyfin_read_test() {
  compose_exec jellyfin sh -lc '
    set -u
    # Sample from OP_MIN_SEASON onward first (rate-limited link requests are a scarce
    # resource; spend them on the seasons actually being watched), fall back to any season.
    find "'"$OP_LIB_CONT"'" -maxdepth 2 -type l 2>/dev/null \
      | awk -F"/Season " -v min="'"$OP_MIN_SEASON"'" "NF > 1 { split(\$2, a, \"/\"); if (a[1] + 0 >= min) print }" \
      | head -n 10 > /tmp/onepace-read-samples.txt
    if [ ! -s /tmp/onepace-read-samples.txt ]; then
      find "'"$OP_LIB_CONT"'" -maxdepth 2 -type l 2>/dev/null | head -n 10 > /tmp/onepace-read-samples.txt
    fi
    if [ ! -s /tmp/onepace-read-samples.txt ]; then
      echo "ERROR: no One Pace symlink visible inside Jellyfin at '"$OP_LIB_CONT"'"
      exit 2
    fi
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      echo "sample=$f"
      echo "target=$(readlink "$f")"
      if ! stat "$f" >/dev/null 2>&1; then
        echo "FAIL: stat could not resolve sample"
        continue
      fi
      if dd if="$f" bs=1M count=1 of=/dev/null >/tmp/onepace-read-test.log 2>&1; then
        cat /tmp/onepace-read-test.log
        echo "OK: Jellyfin read this sample"
        exit 0
      fi
      cat /tmp/onepace-read-test.log
      echo "FAIL: Jellyfin could not read this sample"
    done < /tmp/onepace-read-samples.txt
    echo "ERROR: Jellyfin could not read any tested One Pace sample."
    exit 1
  '
}

torbox_rate_limited() {
  compose logs --tail 40 decypharr 2>&1 | grep -q 'HTTP 429'
}

repair_jellyfin_mount_if_needed() {
  sep "Testing Jellyfin media access"
  if jellyfin_read_test; then
    echo "Jellyfin can read One Pace media."
    return 0
  fi

  if torbox_rate_limited; then
    sep "TorBox is rate-limiting (HTTP 429)"
    echo "decypharr cannot get download links right now because TorBox throttled this account"
    echo "(usually after a full library scan probed every episode). The mount, symlinks, and"
    echo "NFOs are fine — do NOT rescan or rerun this script repeatedly; that extends the limit."
    echo "Wait ~30-60 minutes, then try playing a single episode in Jellyfin."
    return 1
  fi

  sep "Restarting Jellyfin after decypharr mount"
  echo "Jellyfin could not read the symlink target. Restarting Jellyfin so the rslave mount is inherited."
  compose restart jellyfin
  sleep 15

  sep "Retesting Jellyfin media access"
  if jellyfin_read_test; then
    echo "Jellyfin can read One Pace media after restart."
    return 0
  fi

  echo "ERROR: Jellyfin still cannot read One Pace media after restart."
  echo "Recent Jellyfin/decypharr logs:"
  compose logs --tail 80 jellyfin decypharr 2>&1 | grep -iE 'error|mount|fuse|rclone|permission|denied|media source|playback' | tail -60 || true
  return 1
}

sep "Container status before repair"
compose ps decypharr jellyfin onepace-maintenance || true

sep "Ensuring required services are up"
compose up -d decypharr onepace-maintenance

wait_for_decypharr_mount || exit 1
run_maintenance || exit 1
count_library_files || exit 1
sep "Ensuring Jellyfin is up after decypharr mounted"
compose up -d jellyfin
repair_jellyfin_mount_if_needed || exit 1

sep "Next step"
echo "In Jellyfin, scan the library that contains /data/media/anime (usually Anime)."
echo "If One Pace was already cached with raw '[One Pace' episode names, delete that One Pace series first, then scan."

sep "DONE"
