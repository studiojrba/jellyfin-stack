#!/usr/bin/env python3
import json,urllib.request
B="http://localhost:8989/api/v3";KEY="d1c99179d7784fc0b0ed06ceaf942c76"
GROUPS=["LostYears","ToonsHub","Baws","Kaleido-Flax","NanakoRaws"]
def req(p,method="GET",body=None):
    data=json.dumps(body).encode() if body is not None else None
    r=urllib.request.Request(B+p,data=data,method=method,
        headers={"X-Api-Key":KEY,"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=90) as x:
        t=x.read().decode()
        return x.status,(json.loads(t) if t.strip() else None)

# 1) existing release profiles
st,profs=req("/releaseprofile")
print("existing release profiles:",[p.get("name") for p in (profs or [])])
have=any(p.get("name")=="Block incomplete fansub groups" for p in (profs or []))
if not have:
    body={"name":"Block incomplete fansub groups","enabled":True,
          "required":[],"ignored":GROUPS,"indexerId":0,"tags":[]}
    try:
        st,res=req("/releaseprofile",method="POST",body=body)
        print("create release profile ->",st)
    except Exception as e:
        print("create err:",str(e)[:200])
else:
    print("release profile already exists")

# 2) blocklist+remove current bracket-group queue items
st,q=req("/queue?pageSize=2000")
recs=q["records"]
targets=[x for x in recs if (x.get("title") or "").strip().startswith("[")]
print("\nbracket items to remove now:",len(targets))
done=set()
for x in targets:
    did=x.get("downloadId")
    if did in done: continue
    done.add(did)
    try:
        req("/queue/%d?removeFromClient=true&blocklist=true"%x["id"],method="DELETE")
        print("  removed:",(x.get("title") or "")[:55])
    except Exception as e:
        print("  err",str(e)[:50])
