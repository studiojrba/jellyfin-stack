#!/usr/bin/env bash
# Step 4: force Docker to re-stage the REAL bind mounts, restoring decypharr's
# intact config (rclone mount) and the *arr config.xml files (preserved API keys).
# DO NOT run until 03_confirm.sh shows divergence.
# Run from ~/torbox-stack:  bash rebuild/04_recreate.sh
set -u
cd ~/torbox-stack || exit 1

echo "=== 1) ensure WSL root is rshared (mount propagation prerequisite) ==="
findmnt -no PROPAGATION / | grep -q shared && echo "  / is shared (ok)" || { echo "  making / rshared"; sudo mount --make-rshared / ; }

echo "=== 2) compose down (stops+removes containers; data/volumes kept) ==="
docker compose down

echo "=== 3) clear any stale FUSE mountpoint on host so decypharr can re-mount ==="
# harmless if already clean
fusermount -uz ./mount 2>/dev/null || true
sudo umount -l ./mount 2>/dev/null || true
ls -la ./mount 2>/dev/null | head

echo "=== 4) compose up -d (re-stages bind mounts from REAL ./config) ==="
docker compose up -d

echo "=== 5) wait for decypharr to mount rclone (up to ~90s) ==="
for i in $(seq 1 18); do
  n=$(docker exec decypharr sh -c 'ls /mnt/remote 2>/dev/null | wc -l' 2>/dev/null)
  echo "  t=$((i*5))s decypharr /mnt/remote entries=${n:-0}"
  [ "${n:-0}" -gt 1 ] && break
  sleep 5
done

echo "=== 6) verify decypharr loaded the REAL config (mount_path should be set) ==="
docker logs --tail 15 decypharr 2>&1 | grep -Ei "mount_path|rclone|mounted" | tail -5

echo "=== 7) verify *arr keys now match the preserved on-disk keys ==="
for a in prowlarr sonarr radarr; do
  real=$(grep -o '<ApiKey>[^<]*' "config/$a/config.xml" | sed 's/<ApiKey>//')
  cont=$(docker exec "$a" sh -c 'grep -o "<ApiKey>[^<]*" /config/config.xml | sed "s/<ApiKey>//"' 2>/dev/null)
  match="STILL DIVERGENT"; [ "$real" = "$cont" ] && match="match"
  printf "  %-9s real=%s container=%s [%s]\n" "$a" "$real" "$cont" "$match"
done

echo "=== 8) mount propagation across all consumers ==="
for c in decypharr radarr sonarr jellyfin; do
  n=$(docker exec "$c" sh -c 'ls /mnt/remote 2>/dev/null | wc -l' 2>/dev/null)
  echo "  $c /mnt/remote entries: ${n:-ERROR}"
done
echo "=== DONE ==="
