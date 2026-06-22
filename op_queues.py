#!/usr/bin/env python3
import json, urllib.request
from collections import Counter

SON = ("http://localhost:8989", "d1c99179d7784fc0b0ed06ceaf942c76")
RAD = ("http://localhost:7878", "95683c4e38974f558e96c63af17df5c5")

def get(svc, p):
    base, key = svc
    r = urllib.request.Request(base + p, headers={"X-Api-Key": key})
    return json.load(urllib.request.urlopen(r, timeout=30))

for name, svc in (("SONARR", SON), ("RADARR", RAD)):
    q = get(svc, "/api/v3/queue?pageSize=2000")
    recs = q["records"]
    state = Counter(x.get("trackedDownloadState") for x in recs)
    proto = Counter(x.get("protocol") for x in recs)
    print(f"\n{'='*55}")
    print(f"{name}  total={len(recs)}")
    print(f"  by state: {dict(state)}")
    print(f"  by proto: {dict(proto)}")
    blocked = [x for x in recs if x.get("trackedDownloadState") == "importBlocked"]
    if blocked:
        print(f"  importBlocked ({len(blocked)}):")
        for x in blocked[:8]:
            msgs = [m for sm in x.get("statusMessages", []) for m in sm.get("messages", [])]
            print(f"    - {(x.get('title') or '')[:55]}")
            for m in msgs[:2]: print(f"        ! {m[:70]}")
    pending = [x for x in recs if x.get("trackedDownloadState") == "importPending"]
    if pending:
        print(f"  importPending ({len(pending)}) sample:")
        for x in pending[:5]: print(f"    - {(x.get('title') or '')[:60]}")
