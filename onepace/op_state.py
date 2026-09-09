#!/usr/bin/env python3
import json, os, urllib.request
KEY = os.environ.get("TORBOX_KEY", "")
B   = "https://api.torbox.app/v1/api"
UA  = "Mozilla/5.0 (onepace-keeper)"
def api_get(path):
    req = urllib.request.Request(B+path, headers={"Authorization":"Bearer "+KEY,"User-Agent":UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)
d = api_get("/torrents/mylist?bypass_cache=true&limit=2000&offset=0")
rows = d.get("data") or []
op = [t for t in rows if "one pace" in (t.get("name") or "").lower()]
print(f"total torrents in account={len(rows)} one_pace={len(op)}")
from collections import Counter
states = Counter()
notdone = []
for t in op:
    st = t.get("download_state") or "?"
    states[st]+=1
    fin = t.get("download_finished"); pres = t.get("download_present"); cached=t.get("cached")
    if not fin:
        notdone.append((t.get("name"), st, fin, pres, cached))
print("states:", dict(states))
print(f"not download_finished: {len(notdone)}")
for n in notdone[:15]:
    print("  ", n)
