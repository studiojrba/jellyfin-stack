#!/usr/bin/env bash
# Unstick Radarr/Sonarr queues where decypharr SAB mock has items
# perpetually at "Downloading 100%" without ever flipping to Completed.
#
# Root cause: after a stack restart decypharr rehydrates these items in an
# intermediate state; they never fire their completion transition.
#
# Fix: delete them from the SAB queue (symlinks on disk are preserved), then
# trigger a manual folder scan so *arrs import the already-present content.
# Any items with no on-disk content get caught by a follow-up missing search.
set -uo pipefail

SK=d1c99179d7784fc0b0ed06ceaf942c76
RK=95683c4e38974f558e96c63af17df5c5
RADARR="http://localhost:7878"
SONARR="http://localhost:8989"
SAB="http://localhost:8282"
DL_BASE="/data/downloads"

sep(){ echo; echo "─── $* ───────────────────────────────────────────────"; }

sep "1. SNAPSHOT"
SAB_RAW=$(curl -sf "$SAB/sabnzbd/api?mode=queue&output=json&start=0&limit=500")
TOTAL=$(echo "$SAB_RAW" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["queue"]["slots"]))')
STUCK=$(echo "$SAB_RAW" | python3 -c '
import json,sys
slots=json.load(sys.stdin)["queue"]["slots"]
print(sum(1 for s in slots if s.get("status")=="Downloading" and str(s.get("percentage",""))=="100"))
')
echo " SAB total=$TOTAL  stuck-at-100%=$STUCK"

if [[ "$STUCK" -eq 0 ]]; then
    echo " Nothing stuck — done."
    exit 0
fi

sep "2. DOWNLOAD FOLDER CHECK"
for cat in sonarr radarr; do
    n=$(ls "$DL_BASE/$cat/" 2>/dev/null | wc -l)
    echo " $cat: $n dirs in $DL_BASE/$cat/"
done

VALID=0; BROKEN=0
while IFS= read -r lnk; do
    if [ -e "$lnk" ]; then VALID=$((VALID+1)); else BROKEN=$((BROKEN+1)); fi
done < <(find "$DL_BASE" -maxdepth 3 -type l 2>/dev/null)
echo " Symlinks: valid=$VALID  broken=$BROKEN"

sep "3. DELETE STUCK ITEMS FROM SAB QUEUE"
NZO_IDS=$(echo "$SAB_RAW" | python3 -c '
import json,sys
slots=json.load(sys.stdin)["queue"]["slots"]
stuck=[s["nzo_id"] for s in slots if s.get("status")=="Downloading" and str(s.get("percentage",""))=="100"]
print(" ".join(stuck))
')
echo " Deleting $STUCK NZO IDs..."
DELETED=0; FAILED=0
for nzo_id in $NZO_IDS; do
    resp=$(curl -sf "$SAB/sabnzbd/api?mode=queue&name=delete&value=$nzo_id&output=json" 2>/dev/null || echo '{"status":false}')
    ok=$(echo "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","false"))' 2>/dev/null || echo false)
    if [[ "$ok" == "True" ]]; then
        DELETED=$((DELETED+1))
    else
        FAILED=$((FAILED+1))
        echo "  FAIL: $nzo_id → $resp"
    fi
done
echo " Deleted=$DELETED  Failed=$FAILED"

# Also delete from *arr queues to unblock them
sep "3b. REMOVE FROM *ARR QUEUES (blocklist=false so re-grab is allowed)"
# Radarr: get queue IDs for items whose trackedDownloadState=downloading
python3 - <<PYEOF
import urllib.request, json, sys

def delete_arr_queue(host, key, param, name):
    url = f"{host}/api/v3/queue?page=1&pageSize=500&{param}=true"
    req = urllib.request.Request(url, headers={"X-Api-Key": key})
    d = json.loads(urllib.request.urlopen(req).read())
    recs = d.get("records", [])
    stuck = [r["id"] for r in recs if r.get("trackedDownloadState") == "downloading"]
    print(f"  {name}: {len(stuck)} stuck queue IDs to remove")
    ok = err = 0
    for qid in stuck:
        try:
            del_url = f"{host}/api/v3/queue/{qid}?blocklist=false&removeFromClient=true"
            req2 = urllib.request.Request(del_url, method="DELETE", headers={"X-Api-Key": key})
            urllib.request.urlopen(req2)
            ok += 1
        except Exception as e:
            err += 1
    print(f"  {name}: removed={ok} errors={err}")

delete_arr_queue("http://localhost:7878", "95683c4e38974f558e96c63af17df5c5", "includeUnknownMovieItems", "Radarr")
delete_arr_queue("http://localhost:8989", "d1c99179d7784fc0b0ed06ceaf942c76", "includeUnknownSeriesItems", "Sonarr")
PYEOF

sep "4. TRIGGER MANUAL IMPORT SCANS (pick up any existing symlinks)"
echo " Waiting 10s for *arrs to register queue removals..."
sleep 10

scan_resp=$(curl -sf -X POST -H "X-Api-Key: $SK" -H "Content-Type: application/json" \
    "$SONARR/api/v3/command" -d "{\"name\":\"DownloadedEpisodesScan\",\"path\":\"$DL_BASE/sonarr\"}" 2>/dev/null)
echo " Sonarr scan: $(echo "$scan_resp" | python3 -c 'import json,sys; r=json.load(sys.stdin); print("id="+str(r.get("id"))+" status="+str(r.get("status")))' 2>/dev/null || echo 'failed')"

scan_resp=$(curl -sf -X POST -H "X-Api-Key: $RK" -H "Content-Type: application/json" \
    "$RADARR/api/v3/command" -d "{\"name\":\"DownloadedMoviesScan\",\"path\":\"$DL_BASE/radarr\"}" 2>/dev/null)
echo " Radarr scan: $(echo "$scan_resp" | python3 -c 'import json,sys; r=json.load(sys.stdin); print("id="+str(r.get("id"))+" status="+str(r.get("status")))' 2>/dev/null || echo 'failed')"

echo " Waiting 60s for import processing..."
sleep 60

sep "5. TRIGGER MISSING SEARCHES (for anything that had no symlink yet)"
curl -sf -X POST -H "X-Api-Key: $RK" -H "Content-Type: application/json" \
    "$RADARR/api/v3/command" -d '{"name":"MissingMoviesSearch"}' \
    | python3 -c 'import json,sys; r=json.load(sys.stdin); print("  Radarr MissingMoviesSearch id="+str(r.get("id")))' 2>/dev/null || echo "  radarr search failed"

curl -sf -X POST -H "X-Api-Key: $SK" -H "Content-Type: application/json" \
    "$SONARR/api/v3/command" -d '{"name":"MissingEpisodeSearch"}' \
    | python3 -c 'import json,sys; r=json.load(sys.stdin); print("  Sonarr MissingEpisodeSearch id="+str(r.get("id")))' 2>/dev/null || echo "  sonarr search failed"

sep "6. FINAL QUEUE STATE"
python3 - <<'PYEOF'
import urllib.request, json
from collections import Counter

def show(host, key, param, name):
    url = f"{host}/api/v3/queue?page=1&pageSize=300&{param}=true"
    req = urllib.request.Request(url, headers={"X-Api-Key": key})
    d = json.loads(urllib.request.urlopen(req).read())
    recs = d.get("records", [])
    print(f"  {name}: total={d.get('totalRecords')}")
    print(f"    status={dict(Counter(r.get('status') for r in recs))}")
    print(f"    state= {dict(Counter(r.get('trackedDownloadState') for r in recs))}")

show("http://localhost:8989", "d1c99179d7784fc0b0ed06ceaf942c76", "includeUnknownSeriesItems", "Sonarr")
show("http://localhost:7878", "95683c4e38974f558e96c63af17df5c5", "includeUnknownMovieItems", "Radarr")
PYEOF

sep "SAB queue after"
curl -sf "$SAB/sabnzbd/api?mode=queue&output=json" | python3 -c '
import json,sys
from collections import Counter
q=json.load(sys.stdin)["queue"]; sl=q.get("slots",[])
print(" slots:", len(sl), dict(Counter(s.get("status") for s in sl)))
' 2>/dev/null || echo " (empty)"

echo
echo "=== DONE $(date) ==="
