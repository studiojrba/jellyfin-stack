#!/usr/bin/env python3
"""Force-import decypharr downloads parked at importPending with NO rejection at all.

Distinct from unstick_sample_imports.py: there the arr has a concrete (bogus) reason
it won't import -- a sample verdict -- and the fix is to override it. Here the arr
reports *nothing wrong*: /api/v3/manualimport returns the candidate with an empty
`rejections` list, correctly matched to a series/movie, and still never imports it.

Found 2026-08-04: Sonarr had 97 queue items, 82 of them in exactly this state, the
oldest parked for six days. unstick_sample_imports.py could not see any of them --
its prefilter requires "sample" in the queue item's statusMessages, and these items
have no statusMessages at all, so the keeper truthfully reported "nothing stuck on
sample check" the whole time. That blind spot is why this script exists.

Suspected trigger: imports attempted while the FUSE mount was mid-failure (decypharr
returning 504s on TorBox download links, or "Socket not connected" right after a
decypharr restart). Sonarr parks the item and does not retry on its own; the files
themselves read fine afterwards.

Fix = the same ManualImport a human performs by clicking "Import" in the queue UI.

Safety guards:
  * Acts ONLY on candidates whose `rejections` list is empty. Any rejection at all --
    sample, not-an-upgrade, unknown series -- is left for the arr or the sample
    unsticker to deal with. This script never overrides a stated objection.
  * Only imports files >= MIN_SIZE, so a stray small file is never dragged in.
  * Only imports candidates matched to a movie (radarr) or series+episodes (sonarr).
  * MIN_AGE_MIN skips anything that only just landed, so a normal in-flight import is
    never raced. Mirrors the ">= 1 cycle" guard in unstick_stuck_queue.py.

Pacing (load-bearing -- see [[decypharr-504-link-cache]]):
  Each /manualimport query makes the arr read the file for mediainfo, which costs one
  TorBox download-link request through decypharr, and decypharr is throttled to
  download_rate_limit=10/minute. Querying a large backlog unpaced trips that limit and
  makes healthy files look broken. So this sleeps QUERY_DELAY between probes and stops
  after MAX_PER_RUN items; the keeper drains the rest on later runs.

Env overrides: MAX_PER_RUN, QUERY_DELAY, MIN_AGE_MIN, MIN_SIZE_MB.

Exit 0 if it imported >=1 file (signals the keeper a change happened), else 2.
Arr keys are derived from the gitignored decypharr config (no secrets committed).
"""
import json, os, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARRS = {
    "sonarr": "http://localhost:8989",
    "radarr": "http://localhost:7878",
}
# Stay well under decypharr's download_rate_limit (10/minute): ~8 probes/minute.
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "12"))
QUERY_DELAY = float(os.environ.get("QUERY_DELAY", "7"))
MIN_AGE_MIN = int(os.environ.get("MIN_AGE_MIN", "30"))
MIN_SIZE = int(os.environ.get("MIN_SIZE_MB", "300")) * 1024 * 1024


def _tokens():
    cfg = json.load(open(os.path.join(REPO, "config/decypharr/config.json")))
    return {a["name"]: a.get("token", "") for a in cfg.get("arrs", [])}


def _req(url, key, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"X-Api-Key": key}
    if body is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=h, method=method), timeout=120)
    t = r.read().decode()
    return json.loads(t) if t.strip() else None


def _age_minutes(added):
    """Minutes since the queue item was added, or None if unparseable (treated as old)."""
    if not added:
        return None
    try:
        ts = datetime.fromisoformat(added.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
    except Exception:
        return None


def process(name, host, key, budget):
    """Force-import up to `budget` clean-but-parked items. Returns (imported, spent)."""
    try:
        recs = _req(f"{host}/api/v3/queue?page=1&pageSize=500"
                    f"&includeUnknownSeriesItems=true&includeUnknownMovieItems=true",
                    key).get("records", [])
    except Exception as e:
        print(f"  {name}: queue query failed ({e})")
        return 0, 0

    dlids, skipped_young = [], 0
    for r in recs:
        if r.get("trackedDownloadState") != "importPending":
            continue
        if not r.get("downloadId"):
            continue
        # Items carrying a stated rejection belong to the arr or the sample unsticker.
        if any(m.get("messages") for m in r.get("statusMessages", [])):
            continue
        age = _age_minutes(r.get("added"))
        if age is not None and age < MIN_AGE_MIN:
            skipped_young += 1
            continue
        if r["downloadId"] not in dlids:
            dlids.append(r["downloadId"])

    if skipped_young:
        print(f"  {name}: {skipped_young} item(s) too fresh to touch (<{MIN_AGE_MIN}m)")
    if not dlids:
        return 0, 0

    remaining = len(dlids)
    dlids = dlids[:budget]
    if remaining > len(dlids):
        print(f"  {name}: {remaining} parked; probing {len(dlids)} this run "
              f"(paced for decypharr's 10/min link limit), {remaining - len(dlids)} left for next run")

    files, picked, spent = [], [], 0
    for i, dlid in enumerate(dlids):
        if i:
            time.sleep(QUERY_DELAY)
        spent += 1
        try:
            cands = _req(
                f"{host}/api/v3/manualimport?downloadId={urllib.parse.quote(dlid)}"
                f"&filterExistingFiles=false", key) or []
        except Exception as e:
            print(f"  {name}: manualimport probe failed for {dlid[:12]} ({e})")
            continue
        for c in cands:
            if c.get("rejections"):
                continue                      # never override a stated objection
            size = c.get("size") or 0
            if size < MIN_SIZE:
                print(f"  {name}: skip small file ({size // (1024 * 1024)}MB) "
                      f"{c.get('relativePath') or c.get('path')}")
                continue
            f = {
                "path": c["path"],
                "quality": c["quality"],
                "languages": c.get("languages", []),
                "releaseGroup": c.get("releaseGroup", ""),
                "indexerFlags": c.get("indexerFlags", 0),
                "downloadId": dlid,
            }
            if name == "radarr":
                if not c.get("movie"):
                    continue
                f["movieId"] = c["movie"]["id"]
            else:
                if not c.get("series") or not c.get("episodes"):
                    continue
                f["seriesId"] = c["series"]["id"]
                f["episodeIds"] = [e["id"] for e in c["episodes"]]
            files.append(f)
            picked.append((c.get("relativePath") or c.get("path"), size // (1024 * 1024)))

    if not files:
        return 0, spent
    try:
        _req(f"{host}/api/v3/command", key, "POST",
             {"name": "ManualImport", "files": files, "importMode": "auto"})
    except Exception as e:
        print(f"  {name}: ManualImport failed ({e})")
        return 0, spent
    print(f"  {name}: force-imported {len(files)} parked file(s)")
    for path, mb in picked:
        print(f"    {mb}MB {path}")
    return len(files), spent


def main():
    try:
        tokens = _tokens()
    except Exception as e:
        print(f"clean-import: cannot read decypharr config ({e})")
        return 2
    total, budget = 0, MAX_PER_RUN
    for name, host in ARRS.items():
        key = tokens.get(name)
        if not key or budget <= 0:
            continue
        imported, spent = process(name, host, key, budget)
        total += imported
        budget -= spent
    if total:
        print(f"clean-import: force-imported {total} file(s)")
        return 0
    print("clean-import: nothing parked without a rejection")
    return 2


if __name__ == "__main__":
    sys.exit(main())
