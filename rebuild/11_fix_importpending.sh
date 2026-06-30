#!/usr/bin/env bash
# Fix Sonarr items stuck at "Downloaded - Waiting to Import"
# with "Unable to determine if file is a sample" warning.
#
# Strategy:
#   1. Show what's actually in the Sonarr download folder
#   2. Get queue items in importPending state with their downloadIds + paths
#   3. Call Sonarr's /manualimport endpoint to map files → episodes
#   4. POST the import with importMode=auto to force it through
set -uo pipefail

SK=d1c99179d7784fc0b0ed06ceaf942c76
SONARR="http://localhost:8989"
DL_SONARR="/data/downloads/sonarr"

sep(){ echo; echo "─── $* ───────────────────────────────────────────"; }

sep "1. DOWNLOAD FOLDER STATE"
echo " dirs in $DL_SONARR:"
ls "$DL_SONARR/" 2>/dev/null | head -30 || echo "  (empty or missing)"
echo
echo " symlink check (depth 3):"
find "$DL_SONARR" -maxdepth 3 -type l 2>/dev/null | while read -r lnk; do
    target=$(readlink "$lnk")
    if [ -e "$lnk" ]; then
        size=$(stat -c%s "$lnk" 2>/dev/null || echo "?")
        echo "  OK  $(basename "$lnk") → $target  [${size}B]"
    else
        echo "  BROKEN $(basename "$lnk") → $target"
    fi
done

sep "2. SONARR importPending QUEUE ITEMS"
python3 - <<'PYEOF'
import urllib.request, json

url = "http://localhost:8989/api/v3/queue?page=1&pageSize=200&includeUnknownSeriesItems=true"
req = urllib.request.Request(url, headers={"X-Api-Key": "d1c99179d7784fc0b0ed06ceaf942c76"})
d = json.loads(urllib.request.urlopen(req).read())
recs = [r for r in d.get("records", []) if r.get("trackedDownloadState") == "importPending"]
print(f" {len(recs)} importPending items:")
for r in recs:
    title = r.get("title", "")[:55]
    dl_id = r.get("downloadId", "")
    msgs  = [m.get("title","") for m in (r.get("statusMessages") or [])]
    print(f"  [{r['id']}] {title}")
    print(f"       downloadId={dl_id}")
    for m in msgs:
        print(f"       msg: {m}")
PYEOF

sep "3. ATTEMPT MANUAL IMPORT (auto-map + force)"
python3 - <<'PYEOF'
import urllib.request, json, sys

SK  = "d1c99179d7784fc0b0ed06ceaf942c76"
BASE = "http://localhost:8989"
DL   = "/data/downloads/sonarr"

def api(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
          headers={"X-Api-Key": SK, "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        return {"error": str(e)}

# Get importPending items
q = api("GET", "/api/v3/queue?page=1&pageSize=200&includeUnknownSeriesItems=true")
pending = [r for r in q.get("records", []) if r.get("trackedDownloadState") == "importPending"]
print(f" {len(pending)} importPending items to process")

imported = 0
for item in pending:
    qid    = item["id"]
    dl_id  = item.get("downloadId", "")
    title  = item.get("title", "")

    # Ask Sonarr to scan the folder for this download
    folder = f"{DL}/{title}"
    scan = api("GET", f"/api/v3/manualimport?folder={urllib.parse.quote(folder)}&downloadId={dl_id}&filterExistingFiles=false")

    import urllib.parse
    if isinstance(scan, list) and scan:
        files = []
        for f in scan:
            if not f.get("series"): continue
            files.append({
                "path":              f["path"],
                "seriesId":          f["series"]["id"],
                "episodeIds":        [e["id"] for e in f.get("episodes", [])],
                "quality":           f["quality"],
                "releaseGroup":      f.get("releaseGroup", ""),
                "downloadId":        dl_id,
                "languages":         f.get("languages", [{"id":1,"name":"English"}]),
                "indexerFlags":      f.get("indexerFlags", 0),
                "disableRelativePath": False,
            })
        if files:
            result = api("POST", "/api/v3/command",
                         {"name": "ManualImport", "files": files, "importMode": "auto"})
            print(f"  [{qid}] {title[:50]} → ManualImport id={result.get('id')} status={result.get('status')}")
            imported += 1
        else:
            print(f"  [{qid}] {title[:50]} → no mappable files found in folder scan")
    else:
        # Folder doesn't exist — remove from queue, let re-search handle it
        print(f"  [{qid}] {title[:50]} → no download folder, removing from queue")
        del_url = f"/api/v3/queue/{qid}?blocklist=false&removeFromClient=false"
        api("DELETE", del_url)

print(f"\n Attempted import for {imported}/{len(pending)} items")
PYEOF

sep "4. WAIT + FINAL STATE"
echo " Waiting 30s..."
sleep 30

python3 - <<'PYEOF'
import urllib.request, json
from collections import Counter

url = "http://localhost:8989/api/v3/queue?page=1&pageSize=200&includeUnknownSeriesItems=true"
req = urllib.request.Request(url, headers={"X-Api-Key": "d1c99179d7784fc0b0ed06ceaf942c76"})
d = json.loads(urllib.request.urlopen(req).read())
recs = d.get("records", [])
print(f" Sonarr queue total={d.get('totalRecords')}")
print(f"   state={dict(Counter(r.get('trackedDownloadState') for r in recs))}")
print(f"   status={dict(Counter(r.get('status') for r in recs))}")
PYEOF

echo
echo "=== DONE $(date) ==="
