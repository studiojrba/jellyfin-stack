#!/usr/bin/env python3
import json,urllib.request,urllib.parse
KEY="dc4865146fd5436dbeadb0781e6599bf";B="http://localhost:8096"
ANIME="0c41907140d802bb58430fed7e2cd79e"
def g(p):
    r=urllib.request.Request(B+p,headers={"X-Emby-Token":KEY})
    with urllib.request.urlopen(r,timeout=120) as x:return json.load(x)

ENG={"eng","en","english"}
def has_eng(streams):
    for s in (streams or []):
        if s.get("Type")=="Subtitle":
            lang=(s.get("Language") or "").lower()
            if lang in ENG: return True
    return False
def sub_langs(streams):
    out=[]
    for s in (streams or []):
        if s.get("Type")=="Subtitle":
            out.append((s.get("Language") or "?").lower())
    return out

eps=g("/Items?"+urllib.parse.urlencode({
    "ParentId":ANIME,"IncludeItemTypes":"Episode","Recursive":"true",
    "Fields":"MediaStreams,SeriesName","Limit":"100000"})).get("Items",[])
print("total anime episodes scanned:",len(eps))

from collections import defaultdict
series=defaultdict(lambda:{"total":0,"eng":0,"langs":set()})
for e in eps:
    sn=e.get("SeriesName") or "?"
    ms=e.get("MediaStreams")
    series[sn]["total"]+=1
    if has_eng(ms): series[sn]["eng"]+=1
    for l in sub_langs(ms): series[sn]["langs"].add(l)

print("\n=== SERIES MISSING ENGLISH SUBS (any episode) ===")
any_missing=False
for sn in sorted(series):
    d=series[sn]; miss=d["total"]-d["eng"]
    if miss>0:
        any_missing=True
        print(f"  {sn}: {miss}/{d['total']} episodes missing eng | sub langs present: {sorted(d['langs'])}")
if not any_missing: print("  (none - all anime episodes have an English subtitle)")

print("\n=== fully-covered series (have eng on all eps) ===")
for sn in sorted(series):
    d=series[sn]
    if d["total"]-d["eng"]==0:
        print(f"  {sn}: {d['eng']}/{d['total']} OK")
