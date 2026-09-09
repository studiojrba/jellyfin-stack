#!/usr/bin/env bash
# Diagnose why Sonarr/Radarr queues are stuck. Read-only.
set -u
arr_key() { python3 -c "import json,sys;c=json.load(open('config/decypharr/config.json'));print(next((a.get('token','') for a in c.get('arrs',[]) if a.get('name')==sys.argv[1]),''))" "$1"; }
SK="${SONARR_KEY:-$(arr_key sonarr)}"
RK="${RADARR_KEY:-$(arr_key radarr)}"

q(){ # $1=name $2=port $3=key $4=unknownparam
  echo "############## $1 queue ##############"
  curl -s -H "X-Api-Key: $3" "http://localhost:$2/api/v3/queue?page=1&pageSize=300&$4=true" | python3 -c '
import json,sys
from collections import Counter
d=json.load(sys.stdin); recs=d.get("records",[])
print(" totalRecords:", d.get("totalRecords"))
print(" status        :", dict(Counter(r.get("status") for r in recs)))
print(" trackedState  :", dict(Counter(r.get("trackedDownloadState") for r in recs)))
print(" trackedStatus :", dict(Counter(r.get("trackedDownloadStatus") for r in recs)))
print(" protocol      :", dict(Counter(r.get("protocol") for r in recs)))
print(" --- sample (first 8) ---")
for r in recs[:8]:
    print("  [%s/%s] %s" % (r.get("status"), r.get("trackedDownloadState"), (r.get("title") or "")[:60]))
    for m in (r.get("statusMessages") or [])[:2]:
        print("       msg:", m.get("title"), (m.get("messages") or [])[:1])
    if r.get("errorMessage"): print("       err:", r.get("errorMessage"))
' 2>/dev/null || echo "  (queue parse failed)"
}

q Sonarr 8989 "$SK" includeUnknownSeriesItems
q Radarr 7878 "$RK" includeUnknownMovieItems

echo
echo "############## decypharr SAB mock: queue ##############"
curl -s "http://localhost:8282/sabnzbd/api?mode=queue&output=json" | python3 -c '
import json,sys
from collections import Counter
d=json.load(sys.stdin); q=d.get("queue",{}); sl=q.get("slots",[])
print(" sab status:", q.get("status"), "  slots:", len(sl))
print(" slot states:", dict(Counter(s.get("status") for s in sl)))
for s in sl[:6]: print("   ", s.get("status"), s.get("percentage"), "%", (s.get("filename") or "")[:45])
' 2>/dev/null || echo "  (SAB queue empty/!json)"

echo "############## decypharr SAB mock: history ##############"
curl -s "http://localhost:8282/sabnzbd/api?mode=history&output=json&limit=8" | python3 -c '
import json,sys
from collections import Counter
d=json.load(sys.stdin); sl=d.get("history",{}).get("slots",[])
print(" history slots:", len(sl), dict(Counter(s.get("status") for s in sl)))
for s in sl[:6]: print("   ", s.get("status"), (s.get("name") or "")[:50], s.get("fail_message",""))
' 2>/dev/null || echo "  (SAB history empty/!json)"

echo
echo "############## decypharr health + recent error/throttle log ##############"
echo -n " health: "; docker inspect -f '{{.State.Health.Status}}' decypharr 2>/dev/null
docker logs --tail 80 decypharr 2>&1 | grep -Ei 'error|throttl|rate.?limit|429|stall|repair|symlink|fail|timeout|ffprobe' | tail -20
echo "=== DONE ==="
