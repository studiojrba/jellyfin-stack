#!/usr/bin/env bash
KEY="d1c99179d7784fc0b0ed06ceaf942c76"
echo "=== Sonarr queue ==="
docker run --rm --network host python:3.12-slim python3 -c "
import json,urllib.request
from collections import Counter
r=urllib.request.Request('http://localhost:8989/api/v3/queue?pageSize=2000',headers={'X-Api-Key':'$KEY'})
recs=json.load(urllib.request.urlopen(r,timeout=30))['records']
c=Counter(x.get('trackedDownloadState') for x in recs)
print('  total=%d'%len(recs), dict(c))
"
echo "=== ffprobe hang check (0 = none) ==="
docker top sonarr 2>/dev/null | grep -c ffprobe
echo "=== One Pace warming procs ==="
docker exec jellyfin sh -c 'grep -la opwarm /proc/[0-9]*/cmdline 2>/dev/null | wc -l'
echo "=== One Pace Sabaody read test ==="
docker exec jellyfin sh -c 'f=$(find "/data/media/anime/One Pace" -ipath "*Sabaody*" -name "*.mkv" 2>/dev/null | head -1); [ -n "$f" ] && dd if="$f" bs=1M count=2 of=/dev/null 2>&1 | tail -1 || echo "no sabaody file found"'
echo "=== release profile (fansub ban) ==="
docker run --rm --network host python:3.12-slim python3 -c "
import json,urllib.request
r=urllib.request.Request('http://localhost:8989/api/v3/releaseprofile',headers={'X-Api-Key':'$KEY'})
for p in json.load(urllib.request.urlopen(r,timeout=30)):
    print('  ',p.get('name'),'enabled=%s'%p.get('enabled'),'ignored=%s'%p.get('ignored'))
"
echo "=== container health ==="
docker ps --format '{{.Names}}: {{.Status}}' | grep -iE 'decypharr|jellyfin|sonarr|radarr'
