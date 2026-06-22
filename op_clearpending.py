#!/usr/bin/env python3
import json, urllib.request

B = "http://localhost:8989"; KEY = "d1c99179d7784fc0b0ed06ceaf942c76"

def req(p, method="GET"):
    r = urllib.request.Request(B + p, method=method, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(r, timeout=30) as x:
        t = x.read()
        return json.loads(t) if t.strip() else None

recs = req("/api/v3/queue?pageSize=2000")["records"]

def has_sample_err(x):
    for m in x.get("statusMessages", []):
        for msg in m.get("messages", []):
            if "sample" in msg.lower():
                return True
    return False

targets = [x for x in recs if x.get("trackedDownloadState") == "importPending" and has_sample_err(x)]
print(f"sample-error pending: {len(targets)}")
done = set()
for x in targets:
    did = x.get("downloadId")
    if did in done: continue
    done.add(did)
    req(f"/api/v3/queue/{x['id']}?removeFromClient=true&blocklist=true", method="DELETE")
    print(f"  blocklisted: {(x.get('title') or '')[:60]}")
print("done — Sonarr will re-search for complete releases")
