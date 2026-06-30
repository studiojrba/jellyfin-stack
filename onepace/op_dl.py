#!/usr/bin/env python3
import json, os, urllib.request, urllib.parse
KEY=os.environ.get("TORBOX_KEY","")
B="https://api.torbox.app/v1/api"; UA="Mozilla/5.0 (onepace-keeper)"
def get(path):
    req=urllib.request.Request(B+path, headers={"Authorization":"Bearer "+KEY,"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=40) as r: return json.load(r)
d=get("/torrents/mylist?bypass_cache=true&limit=2000&offset=0")
rows=d.get("data") or []
tor=None
for t in rows:
    n=(t.get("name") or "")
    if "Sabaody Archipelago [720p]" in n and "490-513" in n:
        tor=t; break
if not tor:
    # fallback: any sabaody 720p
    for t in rows:
        if "Sabaody Archipelago" in (t.get("name") or "") and "720p" in (t.get("name") or ""):
            tor=t; break
print("torrent:", tor.get("name"), "id=", tor.get("id"), "state=", tor.get("download_state"))
files=tor.get("files") or []
print("file count:", len(files))
tid=tor.get("id")
for fi in files[:6]:
    fid=fi.get("id"); short=fi.get("short_name") or fi.get("name")
    try:
        r=get(f"/torrents/requestdl?token={KEY}&torrent_id={tid}&file_id={fid}")
        ok=r.get("success"); link=(r.get("data") or "")[:60]
        print(f"  file_id={fid} {short[:45]!r} -> success={ok} link={link}")
    except Exception as e:
        print(f"  file_id={fid} {short[:45]!r} -> ERROR {e}")
