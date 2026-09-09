#!/usr/bin/env bash
# Diagnose One Pace playback failure in Jellyfin
set -uo pipefail

MOUNT="/mnt/remote"
OP_LIB="/data/media/anime/One Pace"

sep(){ echo; echo "─── $* ───────────────────────────────────────────"; }

sep "1. CONTAINER STATUS"
docker inspect --format '{{.Name}}  state={{.State.Status}}  health={{.State.Health.Status}}' \
    decypharr onepace-maintenance jellyfin 2>/dev/null

sep "2. MOUNT CHECK (inside decypharr)"
echo " decypharr /mnt/remote:"
docker exec decypharr ls /mnt/remote/ 2>/dev/null | head -10 || echo "  (exec failed)"
echo
echo " decypharr /mnt/remote/__all__ One Pace entries:"
docker exec decypharr ls "/mnt/remote/__all__/" 2>/dev/null | grep -i "one.pace" | head -10 || echo "  (none found)"

sep "3. SYMLINK LIBRARY CHECK"
echo " One Pace lib dirs:"
ls "$OP_LIB/" 2>/dev/null | head -20 || echo "  (missing: $OP_LIB)"
echo
echo " Sample symlink validity (first 10):"
find "$OP_LIB" -maxdepth 2 -type l 2>/dev/null | head -10 | while read -r lnk; do
    target=$(readlink "$lnk")
    if [ -e "$lnk" ]; then
        echo "  OK      $(basename "$lnk")"
    else
        echo "  BROKEN  $(basename "$lnk") -> $target"
    fi
done

sep "4. BROKEN SYMLINK COUNT"
total=0; broken=0
while IFS= read -r lnk; do
    total=$((total+1))
    [ -e "$lnk" ] || broken=$((broken+1))
done < <(find "$OP_LIB" -type l 2>/dev/null)
echo " total=$total  broken=$broken"

sep "5. RECENT onepace-maintenance LOGS"
docker logs --tail 40 onepace-maintenance 2>&1 | tail -40

sep "6. DECYPHARR MOUNT HEALTH"
echo -n " decypharr health: "
docker inspect -f '{{.State.Health.Status}}' decypharr 2>/dev/null
echo " recent decypharr errors/mount issues:"
docker logs --tail 60 decypharr 2>&1 | grep -iE 'error|mount|fuse|rclone|unmount|stall' | tail -15

sep "7. JELLYFIN — can it read a One Pace file?"
# Pick one symlink and test if jellyfin container can stat it
sample=$(find "$OP_LIB" -type l 2>/dev/null | head -1)
if [ -n "$sample" ]; then
    # Get path relative to /data
    rel="${sample#/home/jrbaprz/jellyfin-stack}"
    echo " Testing: $sample"
    docker exec jellyfin stat "/data/media/anime/One Pace/$(basename "$(dirname "$sample")")/$(basename "$sample")" 2>/dev/null \
        && echo "  jellyfin: file accessible" \
        || echo "  jellyfin: CANNOT ACCESS file"
else
    echo " No symlinks found to test"
fi

echo
echo "=== DONE $(date) ==="
