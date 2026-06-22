#!/usr/bin/env bash
# Self-heal the torbox-stack after a reboot when Docker Desktop binds STALE
# empty snapshots (containers auto-start before WSL's filesystem is ready).
# Idempotent: detects the stale signature and only recreates if needed.
set -u
cd /home/jrbaprz/torbox-stack || exit 0
LOG=/home/jrbaprz/torbox-stack/rebuild/autoheal.log
exec >>"$LOG" 2>&1
echo "==================== autoheal $(date) ===================="

# Derive the TorBox key from the live (gitignored) config so this script holds no secret.
TORBOX_KEY=$(grep -o '"api_key": *"[^"]*"' config/decypharr/config.json 2>/dev/null | head -1 | sed 's/.*"api_key": *"//; s/"$//')

# 1) Wait for Docker Desktop integration to be ready (up to ~5 min).
ok=0
for i in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then ok=1; break; fi
  sleep 5
done
[ "$ok" = 1 ] || { echo "docker never came up; exiting (will retry next boot)"; exit 0; }

# 2) Give compose autostart a moment to bring containers up.
for i in $(seq 1 12); do
  docker ps --format '{{.Names}}' | grep -q '^decypharr$' && break
  sleep 5
done

stale=0
# Signature A: decypharr container is NOT reading the real config.json
# (real config contains the TorBox key; a stale blank snapshot does not).
if ! docker ps --format '{{.Names}}' | grep -q '^decypharr$'; then
  echo "stale: decypharr container not running"; stale=1
elif [ -n "$TORBOX_KEY" ]; then
  docker exec decypharr sh -c "grep -q '$TORBOX_KEY' /app/config.json" 2>/dev/null \
    || { echo "stale: decypharr not reading real config.json"; stale=1; }
fi

# Signature B: any *arr container API key != the preserved on-disk key.
for a in prowlarr sonarr radarr; do
  real=$(grep -o '<ApiKey>[^<]*' "config/$a/config.xml" 2>/dev/null | sed 's/<ApiKey>//')
  cont=$(docker exec "$a" sh -c 'grep -o "<ApiKey>[^<]*" /config/config.xml | sed "s/<ApiKey>//"' 2>/dev/null)
  if [ -z "$real" ] || [ "$real" != "$cont" ]; then
    echo "stale: $a key divergence (real=$real container=$cont)"; stale=1
  fi
done

if [ "$stale" = 1 ]; then
  echo ">>> STALE detected -> docker compose down && up"
  docker compose down
  docker compose up -d
  echo ">>> recreate complete"
else
  echo "stack healthy; no action needed"
fi
echo "==================== autoheal done ===================="
