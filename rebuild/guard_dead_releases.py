#!/usr/bin/env python3
"""Stop the arrs from re-downloading NZBs for content whose articles are gone.

THE PROBLEM THIS SOLVES
-----------------------
When an NZB's articles have aged out or been taken down, decypharr's SAB shim
rejects the add outright (HTTP 500, `NNTP ARTICLE_NOT_FOUND (code 430)`). Unlike a
download that fails *after* being accepted, this leaves NO trace in the arr: no
queue item, no history record, no blocklist entry. The arr therefore believes it
never tried that release and re-picks the exact same one on the next search.

Each of those attempts is a real NZB download billed against the indexer account.
On 2026-07-27 NZB Finder sent an "Action Required" warning -- 659 duplicate
downloads across 116 releases -- and threatened termination. Root cause was four
permanently-unobtainable Sopranos S05 episodes: every search walked ~15 dead
candidates, each one a fresh NZB fetch, forever, because nothing was ever
blocklisted.

Sonarr's own `autoRedownloadFailed` amplifier is now off (Settings -> Download
Clients), which stops the instant-retry cascade. This script handles the other
half: content that can never be satisfied at all.

WHAT IT DOES
------------
Reads decypharr's log for add-time NNTP 430 rejections, maps each dead release
back to an episode/movie via the arr's own /parse endpoint, and accumulates the
set of distinct dead releases per item. Once an item has burned through
DEAD_THRESHOLD distinct releases, it is unmonitored -- the arr stops searching it,
so it stops fetching NZBs for it.

Unmonitoring is the right lever because there is no API to blocklist a release the
arr never recorded. It is fully reversible: re-monitor in the UI (or clear the
state file) the day you add an indexer with better retention.

SAFETY GUARDS
-------------
  * Only NNTP 430 (articles genuinely gone) counts. Transient add errors -- shim
    down, timeouts, auth -- are ignored, so an outage can never unmonitor anything.
  * Only items with NO file are touched. Anything already satisfied is skipped,
    so a failed *upgrade* search can never unmonitor working content.
  * Only individual episodes/movies. Never a season, never a series.
  * MAX_ACTIONS per run caps the blast radius if something unexpected floods.
  * Every action logs the item and the full list of dead releases that justified
    it, so a wrong call is traceable and undoable from stack_keeper.log.

Exit 0 if it unmonitored >=1 item (signals the keeper a change happened), else 2.
Arr keys are derived from the gitignored decypharr config (no secrets committed).
"""
import json, os, re, subprocess, sys, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "rebuild/.dead_release_state.json")
ARRS = {"sonarr": "http://localhost:8989", "radarr": "http://localhost:7878"}

DEAD_THRESHOLD = 8      # distinct dead releases before an item is given up on
MAX_ACTIONS = 20        # per-run cap on unmonitors
LOG_WINDOW = "3h"       # decypharr log lookback (keeper runs every 15min; overlap is deduped)
SEEN_RETENTION_DAYS = 14

ANSI = re.compile(r"\x1b\[[0-9;]*m")
# 2026-07-27 15:49:29 | ERROR | [sabnzbd] Failed to add NZB file error="...NNTP
# ARTICLE_NOT_FOUND (code 430)..." filename=The.Sopranos.S05E02...nzb
LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Failed to add NZB file.*filename=(?P<file>\S+)")
DEAD = "ARTICLE_NOT_FOUND"


def _tokens():
    cfg = json.load(open(os.path.join(REPO, "config/decypharr/config.json")))
    return {a["name"]: a.get("token", "") for a in cfg.get("arrs", [])}


def _req(arr, keys, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"X-Api-Key": keys[arr]}
    if body is not None:
        h["Content-Type"] = "application/json"
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(ARRS[arr] + path, data=data, headers=h, method=method),
            timeout=60)
        t = r.read().decode()
        return json.loads(t) if t.strip() else None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


def _load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"seen": {}, "items": {}}


def _save(st):
    cut = (datetime.now(timezone.utc) - timedelta(days=SEEN_RETENTION_DAYS)).strftime("%Y-%m-%d")
    st["seen"] = {k: v for k, v in st["seen"].items() if k[:10] >= cut}
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def _dead_events(window=LOG_WINDOW):
    """(timestamp, release) for add-time NNTP 430 rejections in the log window."""
    try:
        out = subprocess.run(
            ["docker", "compose", "logs", "--since", window, "--no-log-prefix", "decypharr"],
            cwd=REPO, capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return []
    events = []
    for raw in out.splitlines():
        line = ANSI.sub("", raw)
        if DEAD not in line:
            continue
        m = LINE.match(line)
        if not m:
            continue
        rel = m.group("file")
        if rel.endswith(".nzb"):
            rel = rel[:-4]
        events.append((m.group("ts"), rel))
    return events


_RESOLVE_CACHE = {}


def _resolve(release, keys):
    """Map a release name to ('sonarr', episodeId) / ('radarr', movieId), or None.

    Memoised: a stuck item retries the same handful of releases over and over, so
    without this a burst would re-parse the same title hundreds of times.
    """
    if release in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[release]
    _RESOLVE_CACHE[release] = r = _resolve_uncached(release, keys)
    return r


def _resolve_uncached(release, keys):
    q = "/api/v3/parse?title=" + urllib.parse.quote(release)
    p = _req("sonarr", keys, q)
    if p and p.get("series") and p.get("episodes"):
        eps = p["episodes"]
        # Season packs cover many episodes; attributing a pack's death to every episode
        # would trip the threshold far too fast. Only single-episode releases count.
        if len(eps) == 1:
            return "sonarr", eps[0]["id"], f'{p["series"]["title"]} S{eps[0]["seasonNumber"]:02d}E{eps[0]["episodeNumber"]:02d}'
        return None
    p = _req("radarr", keys, q)
    if p and p.get("movie"):
        return "radarr", p["movie"]["id"], p["movie"]["title"]
    return None


def _still_wanted(arr, item_id, keys):
    """True only if the item is monitored AND has no file (so giving up is meaningful)."""
    if arr == "sonarr":
        e = _req("sonarr", keys, f"/api/v3/episode/{item_id}")
        return bool(e) and e.get("monitored") and not e.get("hasFile")
    m = _req("radarr", keys, f"/api/v3/movie/{item_id}")
    return bool(m) and m.get("monitored") and not m.get("hasFile")


def _unmonitor(arr, item_id, keys):
    if arr == "sonarr":
        return _req("sonarr", keys, "/api/v3/episode/monitor", method="PUT",
                    body={"episodeIds": [item_id], "monitored": False}) is not None
    m = _req("radarr", keys, f"/api/v3/movie/{item_id}")
    if not m:
        return False
    m["monitored"] = False
    return _req("radarr", keys, f"/api/v3/movie/{item_id}", method="PUT", body=m) is not None


def main():
    # --dry-run reports what it would do without unmonitoring or persisting state;
    # --window overrides the log lookback (both are for validating changes by hand).
    dry = "--dry-run" in sys.argv
    window = LOG_WINDOW
    if "--window" in sys.argv:
        window = sys.argv[sys.argv.index("--window") + 1]
    keys = _tokens()
    st = _load()
    events = _dead_events(window)
    if not events:
        print("dead-release guard: no NNTP 430 add failures in the last " + window)
        return 2

    fresh = 0
    for ts, rel in events:
        seen_key = f"{ts}|{rel}"
        if seen_key in st["seen"]:
            continue
        st["seen"][seen_key] = 1
        fresh += 1
        r = _resolve(rel, keys)
        if not r:
            continue
        arr, item_id, label = r
        k = f"{arr}:{item_id}"
        rec = st["items"].setdefault(k, {"label": label, "releases": [], "unmonitored": False})
        rec["label"] = label
        if rel not in rec["releases"]:
            rec["releases"].append(rel)

    acted = 0
    for k, rec in st["items"].items():
        if rec["unmonitored"] or len(rec["releases"]) < DEAD_THRESHOLD or acted >= MAX_ACTIONS:
            continue
        arr, item_id = k.split(":", 1)
        item_id = int(item_id)
        if not _still_wanted(arr, item_id, keys):
            # Satisfied or already unmonitored since we last looked -- drop the tally so a
            # future genuine problem starts from a clean slate.
            rec["releases"] = []
            continue
        if dry:
            print(f'dead-release guard: [dry-run] WOULD UNMONITOR {rec["label"]} '
                  f'after {len(rec["releases"])} dead releases')
            acted += 1
            continue
        if _unmonitor(arr, item_id, keys):
            rec["unmonitored"] = True
            acted += 1
            print(f'dead-release guard: UNMONITORED {rec["label"]} '
                  f'after {len(rec["releases"])} dead releases (NNTP 430 at add):')
            for r_ in rec["releases"]:
                print(f"    - {r_}")
            print("    re-monitor in the UI once a better-retention indexer is added")

    if not dry:
        _save(st)
    if acted:
        print(f"dead-release guard: {acted} item(s) unmonitored, {fresh} new failures seen")
        return 0
    pend = {k: len(v["releases"]) for k, v in st["items"].items()
            if v["releases"] and not v["unmonitored"]}
    if pend:
        worst = max(pend.values())
        print(f"dead-release guard: {fresh} new failures, {len(pend)} item(s) accumulating "
              f"(worst {worst}/{DEAD_THRESHOLD}); nothing unmonitored")
    else:
        print(f"dead-release guard: {fresh} new failures, none attributable; nothing unmonitored")
    return 2


if __name__ == "__main__":
    sys.exit(main())
