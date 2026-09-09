#!/usr/bin/env python3
"""Force-import decypharr downloads stuck at importPending solely because the
media analyzer couldn't read a runtime off the FUSE symlink.

Modern Radarr/Sonarr ship NO ffprobe; they use a bundled analyzer to read a
runtime and reject actual sample clips. On decypharr's fuse.rclone symlinks
(/data/downloads/<arr>/<rel>/*.mkv -> /mnt/remote/__all__/...) that analyzer
intermittently can't read a runtime, so a 100%-complete, correctly-matched
release is rejected on the sample check and never imports. Raw reads of the
file still succeed -- it's the seek-heavy metadata read that fails.

The bad runtime read surfaces as TWO different rejections, and both are handled:
  * "Unable to determine if file is a sample" -- the analyzer gave up outright.
  * "Sample" -- the analyzer returned a bogus/zero runtime and the arr positively
    concluded the file IS a sample. Seen on large Bluray remuxes (7-9GB) whose
    runtime reads short over FUSE. Handled since 2026-07-26; before that these
    sat at importPending forever while the keeper reported "nothing stuck".

This is DISTINCT from unstick_stuck_queue.py: there the SAB slot is stuck at
"Downloading 100%" (completion transition never fired); here the download DID
complete and only the import stalls.

Fix = a ManualImport, exactly what clicking "Import" in the UI does (it overrides
the soft sample rejection). Re-running ProcessMonitoredDownloads does NOT help --
it just re-runs the same failing heuristic.

Safety guards (so this can never import junk):
  * Only acts on candidates whose rejections are *all* sample ones. Any other
    rejection (not an upgrade, unknown movie, etc.) is left untouched.
  * Only imports files >= MIN_SIZE, so an actual small sample clip that legitimately
    tripped the check is never force-imported (real content is far larger; samples
    are typically < 200MB). Sub-threshold matches are logged and skipped.
    NOTE: for the bare "Sample" verdict, size is the ONLY discriminator -- a real
    sample produces the identical rejection, so MIN_SIZE is load-bearing there.
    Keep it low enough for 1080p anime (~300-500MB/ep) but above sample size.
  * Every force-import is logged with its filename and which rule matched, so a
    real sample slipping through is traceable in stack_keeper.log.
  * Only imports candidates matched to a movie (radarr) or series+episodes (sonarr).

Exit 0 if it imported >=1 file (signals the keeper a change happened), else 2.
Arr keys are derived from the gitignored decypharr config (no secrets committed).
"""
import json, os, sys, urllib.request, urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARRS = {
    "sonarr": "http://localhost:8989",
    "radarr": "http://localhost:7878",
}
SAMPLE_REJ_UNDETERMINED = "unable to determine if file is a sample"
SAMPLE_REJ_POSITIVE = "sample"   # exact match only; see _sample_rule
MIN_SIZE = 300 * 1024 * 1024     # 300 MB floor; below this could be a real sample clip


def _tokens():
    cfg = json.load(open(os.path.join(REPO, "config/decypharr/config.json")))
    return {a["name"]: a.get("token", "") for a in cfg.get("arrs", [])}


def _req(url, key, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"X-Api-Key": key}
    if body is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=h, method=method), timeout=60)
    t = r.read().decode()
    return json.loads(t) if t.strip() else None


def _sample_rule(reason):
    """Classify one rejection reason, or None if it isn't a sample rejection.

    "sample" is matched EXACTLY (not as a substring) so an unrelated rejection that
    merely mentions the word can never be mistaken for the positive-sample verdict.
    """
    r = (reason or "").strip().lower()
    if SAMPLE_REJ_UNDETERMINED in r:
        return "undetermined"
    if r == SAMPLE_REJ_POSITIVE:
        return "positive"
    return None


def _sample_rules(cand):
    """Set of sample rules matched, or None if the candidate has a non-sample rejection
    (or no rejections at all -- nothing to override)."""
    rejections = cand.get("rejections") or []
    if not rejections:
        return None
    rules = set()
    for rj in rejections:
        rule = _sample_rule(rj.get("reason"))
        if rule is None:
            return None
        rules.add(rule)
    return rules


def process(name, host, key):
    try:
        recs = _req(f"{host}/api/v3/queue?page=1&pageSize=500", key).get("records", [])
    except Exception as e:
        print(f"  {name}: queue query failed ({e})")
        return 0

    dlids = set()
    for r in recs:
        if r.get("trackedDownloadState") != "importPending":
            continue
        blob = " ".join(
            (m.get("title", "") + " " + " ".join(m.get("messages", [])))
            for m in r.get("statusMessages", [])
        ).lower()
        # Cheap prefilter only -- catches both "Sample" and the longer wording (which
        # also contains it). The per-candidate _sample_rules() check below is the real
        # gate, so a release whose *title* happens to say "sample" costs one extra query.
        if SAMPLE_REJ_POSITIVE in blob and r.get("downloadId"):
            dlids.add(r["downloadId"])

    files, picked = [], []
    for dlid in dlids:
        try:
            cands = _req(
                f"{host}/api/v3/manualimport?downloadId={urllib.parse.quote(dlid)}"
                f"&filterExistingFiles=false", key) or []
        except Exception:
            continue
        for c in cands:
            rules = _sample_rules(c)
            if rules is None:
                continue
            if (c.get("size") or 0) < MIN_SIZE:
                print(f"  {name}: skip small file ({(c.get('size') or 0)//(1024*1024)}MB) "
                      f"{c.get('relativePath') or c.get('path')} -- could be a real sample")
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
            picked.append((c.get("relativePath") or c.get("path"),
                           "+".join(sorted(rules)),
                           (c.get("size") or 0) // (1024 * 1024)))

    if not files:
        return 0
    try:
        _req(f"{host}/api/v3/command", key, "POST",
             {"name": "ManualImport", "files": files, "importMode": "auto"})
    except Exception as e:
        print(f"  {name}: ManualImport failed ({e})")
        return 0
    print(f"  {name}: force-imported {len(files)} sample-stuck file(s)")
    for path, rule, mb in picked:
        print(f"    [{rule}] {mb}MB {path}")
    return len(files)


def main():
    try:
        tokens = _tokens()
    except Exception as e:
        print(f"sample-import: cannot read decypharr config ({e})")
        return 2
    total = 0
    for name, host in ARRS.items():
        key = tokens.get(name)
        if not key:
            continue
        total += process(name, host, key)
    if total:
        print(f"sample-import: force-imported {total} file(s)")
        return 0
    print("sample-import: nothing stuck on sample check")
    return 2


if __name__ == "__main__":
    sys.exit(main())
