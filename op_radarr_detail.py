#!/usr/bin/env python3
import json, urllib.request
from datetime import datetime, timezone

B = "http://localhost:7878"; KEY = "95683c4e38974f558e96c63af17df5c5"

def get(p):
    r = urllib.request.Request(B + p, headers={"X-Api-Key": KEY})
    return json.load(urllib.request.urlopen(r, timeout=30))

recs = get("/api/v3/queue?pageSize=500&includeMovie=true")["records"]
now = datetime.now(timezone.utc)

print(f"Radarr queue: {len(recs)} items\n")
for x in sorted(recs, key=lambda r: r.get("added",""), reverse=False):
    title = (x.get("title") or "")[:55]
    state = x.get("trackedDownloadState","?")
    status = x.get("status","?")
    proto = x.get("protocol","?")
    size_mb = round((x.get("size") or 0) / 1024**2)
    left_mb = round((x.get("sizeleft") or 0) / 1024**2)
    pct = round(100 * (1 - (x.get("sizeleft",0) / (x.get("size",1) or 1))), 1)
    added = x.get("added","")[:10]
    msgs = [m for sm in x.get("statusMessages",[]) for m in sm.get("messages",[])]
    err = x.get("errorMessage","")
    print(f"  [{added}] {pct:5.1f}% | {state:12s} | {proto:6s} | {size_mb:6}MB | {title}")
    for m in msgs[:2]: print(f"           ! {m[:75]}")
    if err: print(f"           ERR: {err[:75]}")
