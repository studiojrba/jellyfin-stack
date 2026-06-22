#!/usr/bin/env python3
import json,urllib.request,urllib.parse,time
KEY="dc4865146fd5436dbeadb0781e6599bf";BASE="http://localhost:8096"
def get(p):
    r=urllib.request.Request(BASE+p,headers={"X-Emby-Token":KEY})
    with urllib.request.urlopen(r,timeout=90) as x:return json.load(x)
def post(p):
    r=urllib.request.Request(BASE+p,data=b"",headers={"X-Emby-Token":KEY},method="POST")
    with urllib.request.urlopen(r,timeout=90) as x:return x.status
SID="e562be9e37ad3defa5372aa5e3c318cf"
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
