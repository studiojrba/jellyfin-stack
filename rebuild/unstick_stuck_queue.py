#!/usr/bin/env python3
"""Clear decypharr SAB (usenet) downloads stuck at "Downloading 100%".

decypharr's SAB mock sometimes leaves completed usenet downloads perpetually at
"Downloading 100%" without firing the completion transition (notably after a
decypharr/stack restart). Sonarr/Radarr then wait forever to import a download
that is actually finished, so the queue fills with stale items.

Safety guard: only clears an item that was ALSO seen stuck on the PREVIOUS run
(persisted >= 1 keeper cycle, ~15 min) -- a genuine just-completed download flips
to Completed within seconds and never lingers a whole cycle, so this can't delete
a fresh completion. State persists in rebuild/.queue_state.json.

For each cleared item: removes it from the arr queue (removeFromClient=true,
blocklist=false so a future re-grab is allowed) and deletes the SAB slot. Content
already imported into the library is untouched (removeFromClient only clears the
download-client entry, not library files). Prints a one-line summary; exit code 0
if it cleared >=1 item (signals the keeper to run an import scan), 2 if nothing.

Arr keys are derived from the gitignored decypharr config (no secrets committed).
"""
import json, os, sys, urllib.request, urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAB = os.environ.get("SAB_URL", "http://localhost:8282")
STATE = os.path.join(REPO, "rebuild", ".queue_state.json")
ARRS = {
    "sonarr": ("http://localhost:8989", "includeUnknownSeriesItems"),
    "radarr": ("http://localhost:7878", "includeUnknownMovieItems"),
}

def _tokens():
    cfg = json.load(open(os.path.join(REPO, "config/decypharr/config.json")))
    return {a["name"]: a.get("token", "") for a in cfg.get("arrs", [])}

def _get(url, key=None):
    h = {"X-Api-Key": key} if key else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30).read())

def sab_stuck():
    q = _get(f"{SAB}/sabnzbd/api?mode=queue&output=json&start=0&limit=500")["queue"]["slots"]
    return {s["nzo_id"]: s.get("filename", "") for s in q
            if s.get("status") == "Downloading" and str(s.get("percentage", "")) == "100"}

def main():
    try:
        current = sab_stuck()
    except Exception as e:
        print(f"unstick: SAB query failed ({e})"); return 2
    prev = set()
    if os.path.exists(STATE):
        try: prev = set(json.load(open(STATE)).get("stuck", []))
        except Exception: pass
    # Persist current for next run BEFORE acting, so a crash mid-clear still records state.
    json.dump({"stuck": list(current)}, open(STATE, "w"))

    to_clear = [n for n in current if n in prev]   # stuck this run AND last run
    if not to_clear:
        if current:
            print(f"unstick: {len(current)} at 100% (new this cycle; will clear next run if still stuck)")
        return 2

    tokens = _tokens()
    removed_arr = 0
    # remove matching arr queue items (match by downloadId == nzo_id)
    for name, (host, param) in ARRS.items():
        key = tokens.get(name)
        if not key: continue
        try:
            recs = _get(f"{host}/api/v3/queue?page=1&pageSize=500&{param}=true", key).get("records", [])
        except Exception:
            continue
        for r in recs:
            if r.get("downloadId") in to_clear or (r.get("trackedDownloadState") == "downloading" and r.get("sizeleft") == 0):
                try:
                    u = f"{host}/api/v3/queue/{r['id']}?blocklist=false&removeFromClient=true"
                    urllib.request.urlopen(urllib.request.Request(u, method="DELETE", headers={"X-Api-Key": key}), timeout=30)
                    removed_arr += 1
                except Exception:
                    pass
    # delete SAB slots directly (belt-and-suspenders)
    for nzo in to_clear:
        try:
            urllib.request.urlopen(f"{SAB}/sabnzbd/api?mode=queue&name=delete&value={nzo}&output=json", timeout=30)
        except Exception:
            pass
    # best-effort: import any completed-but-unimported content in the download folder
    scans = {"sonarr": ("http://localhost:8989", "DownloadedEpisodesScan", "/data/downloads/sonarr"),
             "radarr": ("http://localhost:7878", "DownloadedMoviesScan", "/data/downloads/radarr")}
    for name, (host, cmd, path) in scans.items():
        key = tokens.get(name)
        if not key: continue
        try:
            body = json.dumps({"name": cmd, "path": path}).encode()
            urllib.request.urlopen(urllib.request.Request(
                f"{host}/api/v3/command", data=body,
                headers={"X-Api-Key": key, "Content-Type": "application/json"}), timeout=30)
        except Exception:
            pass
    print(f"unstick: cleared {len(to_clear)} stuck download(s); removed {removed_arr} arr queue item(s)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
