#!/usr/bin/env bash
cd /home/jrbaprz/torbox-stack || exit 1
KEY="d1c99179d7784fc0b0ed06ceaf942c76"
echo "=== states before ==="
docker ps -a --format '{{.Names}} {{.Status}}' | grep -iE "decypharr|jellyfin|sonarr|radarr|maint"
echo "=== step1: stop decypharr to release the stuck ffprobe FUSE read in sonarr ==="
timeout 40 docker stop decypharr 2>&1 | sed 's/^/  /'
sleep 3
echo "  sonarr stuck ffprobe still present?"
docker top sonarr 2>/dev/null | grep -c ffprobe || echo "  (docker top failed)"
echo "=== step2: compose down (should work now) ==="
timeout 120 docker compose down 2>&1 | tail -10
sleep 3
echo "=== step3: clear stale FUSE mountpoint on host ==="
timeout 10 fusermount -uz /home/jrbaprz/torbox-stack/mount 2>&1 | sed 's/^/  /'
sudo umount -l /home/jrbaprz/torbox-stack/mount 2>/dev/null
ls -la /home/jrbaprz/torbox-stack/mount 2>&1 | head -2
echo "=== step4: compose up -d ==="
timeout 120 docker compose up -d 2>&1 | tail -12
echo "=== step5: verify mount propagation (decypharr + jellyfin) ==="
for i in $(seq 1 36); do
  sleep 5
  dn=$(docker exec decypharr sh -c 'ls /mnt/remote/__all__ 2>/dev/null | wc -l' 2>/dev/null)
  jf=$(docker exec jellyfin sh -c 'ls /mnt/remote/__all__ 2>/dev/null | wc -l' 2>/dev/null)
  echo "  t=$((i*5))s decypharr=${dn:-NA} jellyfin=${jf:-NA}"
  if [ -n "$jf" ] && [ "$jf" -gt 5 ]; then echo "  PROPAGATION OK"; break; fi
done
echo "=== step6: One Pace Sabaody read test (playback path) ==="
f=$(docker exec jellyfin sh -c "find /mnt/remote/__all__ -path '*One Pace*Sabaody Archipelago 03*' -name '*.mkv' 2>/dev/null | head -1" 2>/dev/null)
docker exec jellyfin sh -c "b=\$(timeout 25 dd if=\"$f\" bs=1M count=3 2>/dev/null | wc -c); echo \"  Sabaody read: \$((b/1048576))MB\"" 2>/dev/null
echo "=== step7: sonarr API ==="
for i in $(seq 1 45); do
  sleep 4
  code=$(docker run --rm --network host curlimages/curl:latest -s -o /dev/null -w '%{http_code}' -H "X-Api-Key: $KEY" http://localhost:8989/api/v3/system/status 2>/dev/null)
  echo "  t=$((i*4))s sonarr-api=$code"
  [ "$code" = "200" ] && break
done
