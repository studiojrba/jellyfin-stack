#!/usr/bin/env python3
import json, os, urllib.request, urllib.error, time
KEY=os.environ.get("TORBOX_KEY","e749fcd2-f95e-4704-a85c-fa2f43d82afd")
B="https://api.torbox.app/v1/api"; UA="Mozilla/5.0 (onepace-keeper)"
def raw(path):
    req=urllib.request.Request(B+path, headers={"Authorization":"Bearer "+KEY,"User-Agent":UA})
    return urllib.request.urlopen(req,timeout=40)
def get(path):
    with raw(path) as r: return json.load(r)
d=get("/torrents/mylist?bypass_cache=true&limit=2000&offset=0")
rows=d.get("data") or []
pairs=[]
for t in rows:
    if "one pace" in (t.get("name") or "").lower():
        for fi in (t.get("files") or []):
            pairs.append((t["id"], fi["id"]))
print("total one-pace (tid,fid) pairs:", len(pairs))
# wait for window reset: poll one cheap request until it succeeds
print("waiting for rate window to reset...")
tid,fid=pairs[0]
for _ in range(20):
    try:
        with raw(f"/torrents/requestdl?token={KEY}&torrent_id={tid}&file_id={fid}") as r:
            if r.status==200: print("window open"); break
    except urllib.error.HTTPError as e:
        ra=e.headers.get("Retry-After")
        print("  still limited, retry-after=", ra); time.sleep(min(int(ra or 10)+2, 70))
# now fire as fast as possible, count successes until 429
ok=0
t0=time.time()
for (tid,fid) in pairs[1:400]:
    try:
        with raw(f"/torrents/requestdl?token={KEY}&torrent_id={tid}&file_id={fid}") as r:
            ok+=1
    except urllib.error.HTTPError as e:
        if e.code==429:
            print(f"429 after {ok} successes in {time.time()-t0:.1f}s (retry-after={e.headers.get('Retry-After')})")
            break
        else:
            print("other err", e.code)
print("total successes this window:", ok)
