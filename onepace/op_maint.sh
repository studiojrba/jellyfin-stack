#!/usr/bin/env sh
# One Pace maintenance: re-add any purged torrents, then refresh library symlinks.
# Runs from host (cron) or inside the onepace-maintenance container loop.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
MOUNT="${OP_MOUNT:-/mnt/remote}"
echo "===== One Pace maintenance $(date '+%Y-%m-%d %H:%M:%S') ====="
# 1) Re-add any purged torrents (TorBox API only; this is the core anti-decay step).
python3 "$DIR/op_readd.py"
# 2) Pre-fetch + cache the One Pace metadata *before* any new symlink goes live. If a
#    newly-symlinked episode gets scanned by Jellyfin before its NFO exists, Jellyfin
#    caches it as the raw filename forever -- no rescan or forced metadata refresh ever
#    fixes it (verified; see op_nfo.py docstring). The metadata fetch below is a network
#    round-trip and the slowest step in this whole pipeline, so warming the cache here
#    (instead of inside the write pass after symlinking) shrinks the window where a new
#    symlink is visible without a matching NFO down to a pure-filesystem write.
OP_NFO_FETCH_ONLY=1 python3 "$DIR/op_nfo.py" || echo "metadata pre-fetch failed (non-fatal; NFO write pass will retry/fall back to cache)"
# 3) Refresh symlinks ONLY if the FUSE mount is visible here. If it isn't (e.g. this
#    runs in a container that didn't inherit decypharr's mount), that's fine: re-added
#    torrents reappear at the same mount path, so existing symlinks self-heal.
if [ ! -d "$MOUNT/__all__" ]; then
  echo "mount not visible here; skipping symlink refresh (existing links self-heal on re-add)"
elif [ "$(ls "$MOUNT/__all__" 2>/dev/null | grep -ci 'one pace')" -gt 0 ]; then
  python3 "$DIR/op_symlink.py"
else
  echo "mount visible but no One Pace entries found; skipping symlink refresh"
fi
# 4) Regenerate Jellyfin NFO metadata + posters (CRC-keyed) using the cache warmed in
#    step 2 (OP_NFO_OFFLINE=1 skips the network fetch), so new episodes symlinked in
#    step 3 get their NFO written immediately -- no new/updated files sit without a
#    matching NFO for longer than this pure-filesystem pass takes.
OP_NFO_OFFLINE=1 python3 "$DIR/op_nfo.py" || echo "op_nfo.py failed (non-fatal)"
echo "===== done ====="
