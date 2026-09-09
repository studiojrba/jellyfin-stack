#!/usr/bin/env python3
"""Clean measurement of TorBox requestdl limit with NO other client running.
Run after `docker stop decypharr`."""
import json, os, urllib.request, urllib.error, time
KEY=os.environ.get("TORBOX_KEY","")
B="https://api.torbox.app/v1/api"; UA="Mozilla/5.0 (onepace-keeper)"
def raw(path):
    req=urllib.request.Request(B+path, headers={"Authorization":"Bearer "+KEY,"User-Agent":UA})
    return urllib.request.urlopen(req,timeout=40)
def get(path):
    with raw(path) as r: return json.load(r)
d=get("/torrents/mylist?bypass_cache=true&limit=2000&offset=0")
pairs=[]
for t in (d.get("data") or []):
    if "one pace" in (t.get("name") or "").lower():
        for fi in (t.get("files") or []):
            pairs.append((t["id"], fi["id"]))
print("pairs:", len(pairs), flush=True)
# Wait for cooldown to fully clear
print("waiting for window to open...", flush=True)
while True:
    tid,fid=pairs[0]
    try:
        with raw(f"/torrents/requestdl?token={KEY}&torrent_id={tid}&file_id={fid}") as r:
            if r.status==200: break
    except urllib.error.HTTPError as e:
        ra=int(e.headers.get("Retry-After") or 30)
        print(f"  cooldown, sleeping {ra+3}s", flush=True); time.sleep(ra+3)
print("window OPEN. firing burst...", flush=True)
ok=1; t0=time.time()
for (tid,fid) in pairs[1:]:
    try:
        with raw(f"/torrents/requestdl?token={KEY}&torrent_id={tid}&file_id={fid}") as r: ok+=1
    except urllib.error.HTTPError as e:
        if e.code==429:
            print(f"=> 429 after {ok} OK in {time.time()-t0:.1f}s, retry-after={e.headers.get('Retry-After')}", flush=True)
            break
print("clean per-window successes:", ok, flush=True)
