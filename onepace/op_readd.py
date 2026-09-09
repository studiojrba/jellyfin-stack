#!/usr/bin/env python3
"""Re-add any One Pace manifest torrents that TorBox has purged from the account.
Cached torrents re-add instantly. Safe to run repeatedly (idempotent)."""
import json, os, time, urllib.request, urllib.parse, mimetypes, sys

KEY = os.environ.get("TORBOX_KEY", "")
MAN = os.environ.get("OP_MANIFEST", "/home/jrbaprz/jellyfin-stack/onepace_final.json")
B   = "https://api.torbox.app/v1/api"

UA = "Mozilla/5.0 (onepace-keeper)"  # TorBox/Cloudflare 403s the default Python urllib UA

def api_get(path):
    req = urllib.request.Request(B+path, headers={"Authorization":"Bearer "+KEY, "User-Agent":UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)

def add_magnet(magnet):
    # multipart/form-data with a single 'magnet' field
    boundary = "----opboundary7c3a"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"magnet\"\r\n\r\n{magnet}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"seed\"\r\n\r\n1\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"allow_zip\"\r\n\r\nfalse\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(B+"/torrents/createtorrent", data=body,
        headers={"Authorization":"Bearer "+KEY, "User-Agent":UA,
                 "Content-Type":f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def main():
    man = json.load(open(MAN))
    try:
        d = api_get("/torrents/mylist?bypass_cache=true&limit=2000&offset=0")
        have = {(t.get("hash") or "").lower() for t in (d.get("data") or [])}
    except Exception as e:
        print("mylist error:", e); return 1
    missing = [m for m in man if m["hash"] and m["hash"].lower() not in have]
    print(f"manifest={len(man)} in_account={len(have)} missing={len(missing)}")
    re_added = 0
    for m in missing:
        try:
            r = add_magnet(m["magnet"])
            if r.get("success"):
                re_added += 1
                print("  re-added:", m["title"])
            else:
                print("  FAIL:", m["title"], r.get("detail") or r.get("error"))
        except Exception as e:
            print("  ERR:", m["title"], e)
        time.sleep(2)
    print(f"re-added {re_added}/{len(missing)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
