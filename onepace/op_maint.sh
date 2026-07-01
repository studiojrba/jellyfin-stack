#!/usr/bin/env sh
# One Pace maintenance: re-add any purged torrents, then refresh library symlinks.
# Runs from host (cron) or inside the onepace-maintenance container loop.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
MOUNT="${OP_MOUNT:-/mnt/remote}"
echo "===== One Pace maintenance $(date '+%Y-%m-%d %H:%M:%S') ====="
# 1) Re-add any purged torrents (TorBox API only; this is the core anti-decay step).
python3 "$DIR/op_readd.py"
# 2) Refresh symlinks ONLY if the FUSE mount is visible here. If it isn't (e.g. this
#    runs in a container that didn't inherit decypharr's mount), that's fine: re-added
#    torrents reappear at the same mount path, so existing symlinks self-heal.
if [ ! -d "$MOUNT/__all__" ]; then
  echo "mount not visible here; skipping symlink refresh (existing links self-heal on re-add)"
elif [ "$(ls "$MOUNT/__all__" 2>/dev/null | grep -ci 'one pace')" -gt 0 ]; then
  python3 "$DIR/op_symlink.py"
else
  echo "mount visible but no One Pace entries found; skipping symlink refresh"
fi
# 3) Regenerate Jellyfin NFO metadata + posters (offline, CRC-keyed). Cheap + idempotent,
#    so new One Pace releases get titles/plots/art without depending on the flaky
#    api.onepace.net plugin backend. Jellyfin applies new NFOs on its next scan.
python3 "$DIR/op_nfo.py" || echo "op_nfo.py failed (non-fatal)"
echo "===== done ====="
