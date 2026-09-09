#!/usr/bin/env python3
import json,os,urllib.request,urllib.parse,time

def _env(name):
    v = os.environ.get(name)
    if v: return v
    try:
        for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except FileNotFoundError:
        pass
    return None

KEY=_env("JELLYFIN_API_KEY");BASE="http://localhost:8096"
if not KEY:
    raise SystemExit("JELLYFIN_API_KEY not set (env or .env)")
AUTH={"Authorization":'MediaBrowser Token="%s"'%KEY}
def get(p):
    r=urllib.request.Request(BASE+p,headers=AUTH)
    with urllib.request.urlopen(r,timeout=90) as x:return json.load(x)
def post(p):
    r=urllib.request.Request(BASE+p,data=b"",headers=AUTH,method="POST")
    with urllib.request.urlopen(r,timeout=90) as x:return x.status

def _find_series_id():
    r=get("/Items?"+urllib.parse.urlencode({"IncludeItemTypes":"Series","Recursive":"true","SearchTerm":"One Pace"}))
    for it in r.get("Items",[]):
        if it.get("Name")=="One Pace": return it["Id"]
    return None

SID=os.environ.get("ONEPACE_SERIES_ID") or _find_series_id()
if not SID:
    raise SystemExit("Could not find the One Pace series in Jellyfin (set ONEPACE_SERIES_ID to override)")
def epcount():
    seas=get("/Items?"+urllib.parse.urlencode({"ParentId":SID,"IncludeItemTypes":"Season"}))
    t=0
    for s in seas.get("Items",[]):
        ch=get("/Items?"+urllib.parse.urlencode({"ParentId":s["Id"],"IncludeItemTypes":"Episode"}))
        t+=ch.get("TotalRecordCount")
    return t
print("episodes before:", epcount())
# step 1: clear episode DB items (files stay) via replaceAllMetadata, metadata-only (no images)
rp=urllib.parse.urlencode({"metadataRefreshMode":"FullRefresh","imageRefreshMode":"None","replaceAllMetadata":"true"})
print("clear refresh:", post(f"/Items/{SID}/Refresh?"+rp))
# wait for episodes to drop
for i in range(30):
    time.sleep(6)
    c=epcount()
    if c<=4:
        print(f"episodes cleared (now {c}) after {6*(i+1)}s"); break
else:
    print("episodes not fully cleared:", epcount())
