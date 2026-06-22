#!/usr/bin/env bash
# Fix wedged decypharr usenet queue: restart decypharr, verify mount, kick imports, report.
RAD_KEY="95683c4e38974f558e96c63af17df5c5"
SON_KEY="d1c99179d7784fc0b0ed06ceaf942c76"

echo "=== 1) restarting decypharr to clear wedged usenet queue ==="
docker restart decypharr
echo "   waiting for healthy..."
for i in $(seq 1 30); do
  h=$(docker inspect decypharr --format '{{.State.Health.Status}}' 2>/dev/null)
  echo "   t=${i}x5s health=$h"
  [ "$h" = "healthy" ] && break
  sleep 5
done

echo "=== 2) verify mount visible in jellyfin ==="
sleep 5
vis=$(docker exec jellyfin sh -c 'ls /data/media/anime/ 2>/dev/null | wc -l')
echo "   jellyfin sees $vis anime dirs"
if [ "$vis" -eq 0 ]; then
  echo "   !! mount NOT visible -> run:  bash ~/torbox-stack/op_fullrecover.sh   then re-run this script"
  exit 1
fi

echo "=== 3) check SAB queue/history right after restart ==="
curl -s --max-time 10 'http://localhost:8282/sabnzbd/api?mode=queue&output=json' | python3 -c "
import json,sys
from collections import Counter
q=json.load(sys.stdin).get('queue',{})
print('   queue slots:',len(q.get('slots',[])),'statuses:',dict(Counter(s.get('status') for s in q.get('slots',[]))))
"
curl -s --max-time 10 'http://localhost:8282/sabnzbd/api?mode=history&output=json&limit=200' | python3 -c "
import json,sys
from collections import Counter
s=json.load(sys.stdin).get('history',{}).get('slots',[])
print('   history items:',len(s),'statuses:',dict(Counter(x.get('status') for x in s)))
"

echo "=== 4) kick imports on Radarr + Sonarr ==="
curl -s -X POST 'http://localhost:7878/api/v3/command' -H "X-Api-Key: $RAD_KEY" -H 'Content-Type: application/json' -d '{"name":"ProcessMonitoredDownloads"}' -o /dev/null -w "   radarr kick HTTP %{http_code}\n"
curl -s -X POST 'http://localhost:8989/api/v3/command' -H "X-Api-Key: $SON_KEY" -H 'Content-Type: application/json' -d '{"name":"ProcessMonitoredDownloads"}' -o /dev/null -w "   sonarr kick HTTP %{http_code}\n"

echo "   waiting 60s for processing..."
sleep 60

echo "=== 5) results ==="
for nm in radarr sonarr; do
  if [ "$nm" = radarr ]; then port=7878; key=$RAD_KEY; else port=8989; key=$SON_KEY; fi
  curl -s --max-time 15 "http://localhost:$port/api/v3/queue?pageSize=500" -H "X-Api-Key: $key" | python3 -c "
import json,sys
from collections import Counter
recs=json.load(sys.stdin)['records']
c=Counter(x.get('trackedDownloadState') for x in recs)
print('   $nm total=%d %s'%(len(recs),dict(c)))
"
done
echo "=== done ==="
