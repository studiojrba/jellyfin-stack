#!/usr/bin/env bash
# One-command diagnosis for One Pace playback failures in Jellyfin.
# Answers, in order: (1) can Jellyfin read the media bytes right now?
# (2) is TorBox rate-limiting (429) or otherwise erroring in decypharr?
# (3) did Jellyfin's player/transcoder (ffmpeg) fail?
# Read-only: does not restart anything or touch metadata.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

OP_LIB_CONT="${OP_LIB_CONT:-/data/media/anime/One Pace}"
COMPOSE="${COMPOSE:-docker compose}"
# Read tests sample from this season onward (Sabaody Archipelago = Season 22), so
# scarce rate-limited link requests are spent on the seasons actually being watched.
OP_MIN_SEASON="${OP_MIN_SEASON:-22}"

sep() { echo; echo "=== $* ==="; }

sep "1. Jellyfin media read test (is the source readable right now?)"
# shellcheck disable=SC2086
$COMPOSE exec -T jellyfin sh -lc '
  f="$(find "'"$OP_LIB_CONT"'" -maxdepth 2 -type l 2>/dev/null \
    | awk -F"/Season " -v min="'"$OP_MIN_SEASON"'" "NF > 1 { split(\$2, a, \"/\"); if (a[1] + 0 >= min) print }" \
    | head -n 1)"
  [ -n "$f" ] || f="$(find "'"$OP_LIB_CONT"'" -maxdepth 2 -type l 2>/dev/null | head -n 1)"
  if [ -z "$f" ]; then echo "ERROR: no One Pace symlinks visible in jellyfin"; exit 2; fi
  echo "sample=$f"
  if dd if="$f" bs=1M count=2 of=/dev/null 2>&1; then
    echo "READ OK: source bytes are readable — playback failure is NOT a mount/TorBox-link problem"
  else
    echo "READ FAILED: source is not readable (mount or TorBox link problem)"
  fi
'

sep "2. decypharr: recent TorBox/link errors (last 15 min of logs)"
# shellcheck disable=SC2086
$COMPOSE logs --since 15m decypharr 2>&1 | grep -iE 'error|429|403|rate|link|stream' | tail -20 \
  || echo "(no recent decypharr errors)"

sep "3. Jellyfin server log: playback/ffmpeg errors (last 15 min)"
# shellcheck disable=SC2086
$COMPOSE logs --since 15m jellyfin 2>&1 | grep -iE 'error|ffmpeg|transcod|playback|fatal|nvenc|cuda' | tail -30 \
  || echo "(no recent jellyfin errors in container logs)"

sep "4. Jellyfin transcode logs (most recent, tail)"
# shellcheck disable=SC2086
$COMPOSE exec -T jellyfin sh -lc '
  d=/config/log
  latest="$(ls -t "$d"/FFmpeg.Transcode* "$d"/ffmpeg-transcode* 2>/dev/null | head -n 1)"
  if [ -z "$latest" ]; then
    echo "(no transcode logs found — playback may have failed before ffmpeg started, or it direct-played)"
    exit 0
  fi
  echo "log=$latest"
  echo "----"
  tail -n 40 "$latest"
'

sep "5. Verdict hints"
echo "READ FAILED + 429s in section 2      -> still TorBox rate-limited: wait longer, do not rescan."
echo "READ OK + nvenc/cuda errors in 3/4   -> GPU transcode broken: test with a client that direct-plays,"
echo "                                        or temporarily disable hardware transcoding in Jellyfin"
echo "                                        (Dashboard > Playback > Transcoding)."
echo "READ OK + no ffmpeg logs             -> likely a browser/client codec issue: try another client"
echo "                                        (phone app/TV) or another browser."
