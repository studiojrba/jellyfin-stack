#!/usr/bin/env python3
import json, os, urllib.request, time
KEY=os.environ.get("TORBOX_KEY","e749fcd2-f95e-4704-a85c-fa2f43d82afd")
B="https://api.torbox.app/v1/api"; UA="Mozilla/5.0 (onepace-keeper)"
def get(path):
    req=urllib.request.Request(B+path, headers={"Authorization":"Bearer "+KEY,"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=40) as r: return r.status, json.load(r)
# pick one cached one-pace torrent
_,d=get("/torrents/mylist?bypass_cache=true&limit=2000&offset=0")
rows=d.get("data") or []
op=[t for t in rows if "one pace" in (t.get("name") or "").lower()]
tor=op[0]
tid=tor.get("id"); files=tor.get("files") or []
print("test torrent:", tor.get("name"), "state=", tor.get("download_state"), "files=", len(files))
# request 5 links spaced 0.5s apart, show status + retry-after
for i,fi in enumerate(files[:5]):
    fid=fi.get("id")
    try:
        st,r=get(f"/torrents/requestdl?token={KEY}&torrent_id={tid}&file_id={fid}")
        link=(r.get("data") or "")
        print(f"  {i} status={st} success={r.get('success')} detail={r.get('detail')} link?={'yes' if link else 'no'}")
    except urllib.error.HTTPError as e:
        ra=e.headers.get("Retry-After")
        print(f"  {i} HTTPError {e.code} retry-after={ra} body={e.read()[:120]}")
    except Exception as e:
        print(f"  {i} ERR {e}")
    time.sleep(0.5)
