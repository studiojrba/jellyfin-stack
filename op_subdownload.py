#!/usr/bin/env python3
import json,urllib.request,urllib.parse,urllib.error,time
KEY="dc4865146fd5436dbeadb0781e6599bf";B="http://localhost:8096"
ANIME="0c41907140d802bb58430fed7e2cd79e"
def call(method,p):
    r=urllib.request.Request(B+p,method=method,headers={"X-Emby-Token":KEY})
    try:
        with urllib.request.urlopen(r,timeout=90) as x:
            raw=x.read(); return x.status,(json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code,e.read().decode("utf-8","replace")[:200]
def g(p):
    r=urllib.request.Request(B+p,headers={"X-Emby-Token":KEY})
    with urllib.request.urlopen(r,timeout=120) as x:return json.load(x)
ENG={"eng","en","english"}
def has_eng(it): return any((s.get("Language") or "").lower() in ENG for s in (it.get("MediaStreams") or []) if s.get("Type")=="Subtitle")

eps=g("/Items?"+urllib.parse.urlencode({
    "ParentId":ANIME,"IncludeItemTypes":"Episode","Recursive":"true",
    "Fields":"MediaStreams,SeriesName","Limit":"100000"})).get("Items",[])
# genuine gaps only (exclude One Pace = re-probe case)
targets=[e for e in eps if not has_eng(e) and (e.get("SeriesName") or "")!="One Pace"]
print("episodes to fetch English subs for:",len(targets))

ok=0; fail=0
for e in targets:
    eid=e["Id"]; nm=f"{e.get('SeriesName')} - {e.get('Name')}"[:55]
    st,res=call("GET",f"/Items/{eid}/RemoteSearch/Subtitles/eng")
    if st>=400:
        print(f"  SEARCH ERR {st} {nm}: {res}"); fail+=1
        if st in (401,403): print("  >>> auth problem - stopping"); break
        continue
    if not res:
        print(f"  no results: {nm}"); fail+=1; continue
    # pick highest community rating / first
    res_sorted=sorted(res,key=lambda r:(r.get("CommunityRating") or 0, r.get("DownloadCount") or 0),reverse=True)
    sid=res_sorted[0].get("Id")
    dst,dres=call("POST",f"/Items/{eid}/RemoteSearch/Subtitles/{urllib.parse.quote(sid,safe='')}")
    if dst<400:
        ok+=1; print(f"  OK  {nm}  <- {res_sorted[0].get('ProviderName')} score={res_sorted[0].get('CommunityRating')}")
    else:
        fail+=1; print(f"  DL ERR {dst} {nm}: {dres}")
        if dst==406 or (isinstance(dres,str) and "quota" in dres.lower()):
            print("  >>> likely daily quota hit - stopping"); break
    time.sleep(1.5)
print(f"\nDONE: downloaded={ok} failed={fail}")
