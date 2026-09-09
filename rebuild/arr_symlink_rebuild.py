#!/usr/bin/env python3
"""Rebuild Sonarr/Radarr library symlinks from cached decypharr mount content.

Post-migration the data/media/{tv,movies} symlinks were lost (only One Pace was
rebuilt). The arr DBs still hold every file's intended library path + release
(sceneName); the content is still present in the debrid mount under __all__. This
reconstructs each symlink locally from that mapping -- no TorBox re-adds.

Matching (proven against this library):
  - sceneName (release, no ext) == mount folder name for single-file releases.
  - For season packs, the episode file lives inside the pack folder, keyed by SxxExx.
Link name = the arr's library basename; target = the actual mount inner file
(container-absolute /mnt/remote/... so it resolves inside containers, like One Pace).

Dry-run by default (writes nothing). Pass --apply to create symlinks.
Host-side paths for reading/writing; targets stay container-absolute.
"""
import os, re, sys, json, urllib.request
from collections import defaultdict

SONARR = os.environ.get("SONARR_URL", "http://localhost:8989")
RADARR = os.environ.get("RADARR_URL", "http://localhost:7878")

def _arr_token(name):
    """Env override, else derive from the gitignored decypharr config so no key is
    committed to the repo."""
    env = os.environ.get(name.upper() + "_KEY")
    if env:
        return env
    try:
        cfg = json.load(open(os.environ.get("DECYPHARR_CONFIG", "config/decypharr/config.json")))
        for a in cfg.get("arrs", []):
            if a.get("name") == name:
                return a.get("token", "")
    except Exception:
        pass
    return ""

SON_KEY = _arr_token("sonarr")
RAD_KEY = _arr_token("radarr")

# Host-side view of the container paths:
HOST_MOUNT = os.environ.get("HOST_MOUNT", "./mount")          # container /mnt/remote
CONT_MOUNT = os.environ.get("CONT_MOUNT", "/mnt/remote")      # symlink target root
HOST_DATA  = os.environ.get("HOST_DATA", "./data")            # container /data
CONT_DATA  = os.environ.get("CONT_DATA", "/data")             # arr `path` prefix
MERGED = "__all__"                                            # debrid-agnostic view
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov")

def api(base, key, path):
    req = urllib.request.Request(base + path, headers={"X-Api-Key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def norm(s): return re.sub(r'[^a-z0-9]', '', (s or '').lower())

def ep_token(s):
    m = re.search(r'[sS](\d{1,2})[eE](\d{1,3})', s or '')
    return (int(m.group(1)), int(m.group(2))) if m else None

def is_video(f): return f.lower().endswith(VIDEO_EXT)

# ---- index the merged mount view once (host-side, one readdir) ----
BASE = os.path.join(HOST_MOUNT, MERGED)
folders = sorted(os.listdir(BASE)) if os.path.isdir(BASE) else []
folder_norm = defaultdict(list)   # normalized folder name -> [folder,...]
for f in folders:
    folder_norm[norm(f)].append(f)

_listing_cache = {}
def list_videos(folder):
    if folder not in _listing_cache:
        p = os.path.join(BASE, folder)
        vids = []
        try:
            if os.path.isfile(p) and is_video(folder):
                vids = [(os.path.dirname(folder) or "", os.path.basename(folder))]
            else:
                for root, _dirs, files in os.walk(p):
                    for fn in files:
                        if is_video(fn):
                            rel = os.path.relpath(os.path.join(root, fn), BASE)
                            vids.append(rel)
        except OSError:
            pass
        _listing_cache[folder] = vids
    return _listing_cache[folder]

def resolve_target(scene, rel, want_ep):
    """Return container-absolute target path for this arr file, or None."""
    scene = scene or (os.path.splitext(rel)[0] if rel else "")
    # candidate folders: exact scene folder first, then any folder whose
    # normalized name contains the release/show signature.
    cands = []
    if scene in folders:
        cands.append(scene)
    for f in folder_norm.get(norm(scene), []):
        if f not in cands: cands.append(f)
    if want_ep:
        # season-pack / alt-release candidates: normalized folder contains show+season
        s, e = want_ep
        show_sig = norm(re.split(r'[sS]\d{1,2}[eE]\d{1,3}', scene)[0]) if scene else ""
        seas = f"s{s:02d}"
        if show_sig:
            for f in folders:
                nf = norm(f)
                if show_sig and show_sig[:12] in nf and seas in nf and f not in cands:
                    cands.append(f)
    for folder in cands:
        vids = list_videos(folder)
        if not vids:
            continue
        if want_ep:
            for rp in vids:
                if ep_token(rp) == want_ep:
                    return f"{CONT_MOUNT}/{MERGED}/{rp}"
        else:
            # movie: single video, else largest by name heuristic (pick first)
            if len(vids) == 1:
                return f"{CONT_MOUNT}/{MERGED}/{vids[0]}"
            # prefer a file whose norm matches the scene
            for rp in vids:
                if norm(os.path.splitext(os.path.basename(rp))[0]) == norm(scene):
                    return f"{CONT_MOUNT}/{MERGED}/{rp}"
            return f"{CONT_MOUNT}/{MERGED}/{sorted(vids)[0]}"
    return None

def host_link_path(arr_path):
    # arr_path is container-absolute (/data/media/...) -> host-side ./data/media/...
    assert arr_path.startswith(CONT_DATA), arr_path
    return HOST_DATA + arr_path[len(CONT_DATA):]

def collect():
    files = []  # (kind, arr_path, scene, rel, want_ep)
    for sid in [s["id"] for s in api(SONARR, SON_KEY, "/api/v3/series")]:
        for ef in api(SONARR, SON_KEY, f"/api/v3/episodefile?seriesId={sid}"):
            rel = ef.get("relativePath") or ""
            scene = ef.get("sceneName") or ""
            files.append(("tv", ef["path"], scene, rel, ep_token(scene) or ep_token(rel) or ep_token(ef["path"])))
    for mv in api(RADARR, RAD_KEY, "/api/v3/movie"):
        mf = mv.get("movieFile")
        if mf:
            files.append(("movie", mf["path"], mf.get("sceneName") or "", mf.get("relativePath") or "", None))
    return files

def main():
    apply = "--apply" in sys.argv
    files = collect()
    plan, unresolved = [], []
    for kind, arr_path, scene, rel, want_ep in files:
        tgt = resolve_target(scene, rel, want_ep)
        if tgt:
            plan.append((kind, host_link_path(arr_path), tgt))
        else:
            unresolved.append((kind, arr_path, scene or rel))

    print(f"arr files: {len(files)}  resolvable: {len(plan)}  UNRESOLVED: {len(unresolved)}")
    by_kind = defaultdict(int)
    for k, _, _ in plan: by_kind[k] += 1
    print(f"  resolvable by kind: {dict(by_kind)}")
    print("\nsample plan (first 6):")
    for k, link, tgt in plan[:6]:
        print(f"  [{k}] {link}\n       -> {tgt}")
    if unresolved:
        print(f"\nUNRESOLVED ({len(unresolved)}):")
        for k, p, s in unresolved[:30]:
            print(f"  [{k}] {s}")

    if not apply:
        print(f"\nDRY-RUN. Would create {len(plan)} symlinks. Re-run with --apply to write.")
        return 0

    created = existed = failed = 0
    for k, link, tgt in plan:
        try:
            os.makedirs(os.path.dirname(link), exist_ok=True)
            if os.path.islink(link):
                if os.readlink(link) == tgt:
                    existed += 1; continue
                os.unlink(link)
            elif os.path.exists(link):
                existed += 1; continue
            os.symlink(tgt, link); created += 1
        except OSError as e:
            failed += 1; print(f"  FAIL {link}: {e}")
    print(f"\nAPPLIED: created={created} existed={existed} failed={failed}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
