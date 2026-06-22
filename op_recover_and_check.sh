#!/usr/bin/env bash
RAD_KEY="95683c4e38974f558e96c63af17df5c5"
SON_KEY="d1c99179d7784fc0b0ed06ceaf942c76"

echo "########## STEP A: full recovery (fixes stale bind mount) ##########"
bash ~/torbox-stack/op_fullrecover.sh

echo
echo "########## STEP B: wait for decypharr healthy ##########"
for i in $(seq 1 24); do
  h=$(docker inspect decypharr --format '{{.State.Health.Status}}' 2>/dev/null)
  echo "   t=${i}x5s decypharr=$h"
  [ "$h" = "healthy" ] && break
  sleep 5
done

echo
echo "########## STEP C: SAB queue + history ##########"
curl -s --max-time 10 'http://localhost:8282/sabnzbd/api?mode=queue&output=json' 2>/dev/null | python3 -c "
import json,sys
from collections import Counter
try:
    q=json.load(sys.stdin).get('queue',{})
    print('   queue slots:',len(q.get('slots',[])),dict(Counter(s.get('status') for s in q.get('slots',[]))))
except Exception as e: print('   queue err:',e)
" 2>/dev/null || echo "   SAB queue not responding"
curl -s --max-time 10 'http://localhost:8282/sabnzbd/api?mode=history&output=json&limit=300' 2>/dev/null | python3 -c "
import json,sys
from collections import Counter
try:
    s=json.load(sys.stdin).get('history',{}).get('slots',[])
    print('   history items:',len(s),dict(Counter(x.get('status') for x in s)))
except Exception as e: print('   history err:',e)
" 2>/dev/null || echo "   SAB history not responding"

echo
echo "########## STEP D: kick imports + wait ##########"
curl -s -X POST 'http://localhost:7878/api/v3/command' -H "X-Api-Key: $RAD_KEY" -H 'Content-Type: application/json' -d '{"name":"ProcessMonitoredDownloads"}' -o /dev/null -w "   radarr kick HTTP %{http_code}\n"
curl -s -X POST 'http://localhost:8989/api/v3/command' -H "X-Api-Key: $SON_KEY" -H 'Content-Type: application/json' -d '{"name":"ProcessMonitoredDownloads"}' -o /dev/null -w "   sonarr kick HTTP %{http_code}\n"
sleep 45

echo
echo "########## STEP E: queue states ##########"
curl -s --max-time 15 "http://localhost:7878/api/v3/queue?pageSize=500" -H "X-Api-Key: $RAD_KEY" | python3 -c "
import json,sys
from collections import Counter
r=json.load(sys.stdin)['records']
print('   RADARR queue total=%d %s'%(len(r),dict(Counter(x.get('trackedDownloadState') for x in r))))
"
curl -s --max-time 15 "http://localhost:8989/api/v3/queue?pageSize=500" -H "X-Api-Key: $SON_KEY" | python3 -c "
import json,sys
from collections import Counter
r=json.load(sys.stdin)['records']
print('   SONARR queue total=%d %s'%(len(r),dict(Counter(x.get('trackedDownloadState') for x in r))))
"

echo
echo "########## STEP F: did things actually import? (library file counts) ##########"
curl -s --max-time 20 "http://localhost:7878/api/v3/movie" -H "X-Api-Key: $RAD_KEY" | python3 -c "
import json,sys
m=json.load(sys.stdin)
have=sum(1 for x in m if x.get('hasFile'))
print('   RADARR movies: %d total, %d with file, %d missing'%(len(m),have,len(m)-have))
"
echo
echo "########## STEP G: recent Radarr history (last 10 events) ##########"
curl -s --max-time 15 "http://localhost:7878/api/v3/history?pageSize=10&sortKey=date&sortDirection=descending" -H "X-Api-Key: $RAD_KEY" | python3 -c "
import json,sys
for x in json.load(sys.stdin).get('records',[]):
    print('   ',x.get('eventType'), (x.get('sourceTitle') or '')[:50])
"
echo "########## done ##########"
