#!/usr/bin/env python3
"""Generate Jellyfin NFO metadata + local posters for the One Pace library.

Why this exists: the One Pace Jellyfin plugin depends on api.onepace.net's GraphQL
API, which is frequently unreachable (Cloudflare 525). When it fails, Jellyfin falls
back to AniDB and mis-identifies the series. This script writes local NFO metadata
(keyed by the CRC-32 in each filename) + arc posters, with <lockdata>true</lockdata>
so online agents never touch One Pace again. Fully offline-resilient.

Data source: github.com/ladyisatis/one-pace-metadata (static files, no live API).
"""
import json, os, re, sys, urllib.request, html

UA = "Mozilla/5.0 (onepace-nfo)"
META_URL = "https://raw.githubusercontent.com/ladyisatis/one-pace-metadata/main/data.min.json"
# The data.min.json base_url (v2 branch) serves 0-byte LFS stubs for posters, so we
# pull images from the committed PNGs on main: posters/<arcnumber>/poster.png + posters/tvshow.png
POSTER_BASE = "https://raw.githubusercontent.com/ladyisatis/one-pace-metadata/main/posters"
LIB = os.environ.get("OP_LIB", "/home/jrbaprz/torbox-stack/data/media/anime/One Pace")
META_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "op_metadata.json")
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v")

def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def load_meta():
    try:
        data = fetch(META_URL)
        meta = json.loads(data)
        try:                       # cache is best-effort (/work may be read-only in the sidecar)
            with open(META_CACHE, "wb") as f:
                f.write(data)
        except OSError:
            pass
        print(f"fetched metadata ({len(data)} bytes)")
        return meta
    except Exception as e:
        print(f"fetch failed ({e}); using cache {META_CACHE}")
        return json.load(open(META_CACHE))

def x(tag, val):
    if val is None or val == "":
        return ""
    return f"<{tag}>{html.escape(str(val), quote=False)}</{tag}>"

def crc_of(name):
    m = re.search(r"\[([0-9A-Fa-f]{8})\]\.[A-Za-z0-9]+$", name)
    return m.group(1).upper() if m else None

def download(url, dest):
    if os.path.exists(dest):
        return True
    try:
        data = fetch(url, timeout=60)
        if len(data) < 200:  # not a real image
            return False
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False

def main():
    clean = os.environ.get("OP_NFO_CLEAN") == "1"
    meta = load_meta()
    base = meta["base_url"].rstrip("/")
    tv = meta["tvshow"]
    arcs = {int(a["part"]): a for a in meta["arcs"]}
    eps = {k.upper(): v for k, v in meta["episodes"].items()}

    if not os.path.isdir(LIB):
        print(f"ERROR: library not found: {LIB}", file=sys.stderr)
        sys.exit(1)

    # ---- series tvshow.nfo ----
    genres = "".join(x("genre", g) for g in tv.get("genre", []))
    tvshow_nfo = (
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<tvshow>\n'
        + x("title", "One Pace")
        + x("originaltitle", "One Pace")
        + x("sorttitle", "One Pace")
        + x("plot", tv.get("plot"))
        + x("premiered", tv.get("premiered"))
        + x("year", tv.get("year"))
        + x("status", tv.get("status"))
        + x("studio", "One Pace Team")
        + genres
        + x("lockdata", "true")
        + "\n</tvshow>\n"
    )
    with open(os.path.join(LIB, "tvshow.nfo"), "w", encoding="utf-8") as f:
        f.write(tvshow_nfo)
    print("wrote tvshow.nfo")

    # ---- series poster (try a few candidates, else fall back to arc 1) ----
    series_poster = os.path.join(LIB, "poster.jpg")
    if clean and os.path.exists(series_poster):
        os.remove(series_poster)
    got = False
    for cand in (f"{POSTER_BASE}/tvshow.png", f"{POSTER_BASE}/1/poster.png"):
        if download(cand, series_poster):
            got = True; break
    print("series poster:", "ok" if got else "MISSING")

    def clean_name(d):
        n = re.sub(r"^\[One Pace\]\s*", "", d)
        n = re.sub(r"\[[^\]]*\]", "", n)            # drop [chapters], [720p], etc.
        n = re.sub(r"\s+", " ", n).strip()
        return n or d

    import shutil

    def migrate(src_name, dst_name):
        """Rename src folder -> dst (canonical 'Season NN'/'Specials'); merge if dst exists.
        This makes Jellyfin parse the season number from the folder name to match the NFO,
        instead of inventing phantom seasons from chapter ranges like '[8-21]' -> 821."""
        if src_name == dst_name:
            return dst_name
        src = os.path.join(LIB, src_name); dst = os.path.join(LIB, dst_name)
        if not os.path.exists(dst):
            os.rename(src, dst)
        else:
            for f in os.listdir(src):
                s = os.path.join(src, f); d2 = os.path.join(dst, f)
                if not os.path.exists(d2):
                    shutil.move(s, d2)
                elif os.path.islink(s) or os.path.isfile(s):
                    os.unlink(s)
            try: os.rmdir(src)
            except OSError: pass
        return dst_name

    # ---- pass 1: decide season number per folder, then migrate to canonical layout ----
    arc_dirs = [d for d in sorted(os.listdir(LIB)) if os.path.isdir(os.path.join(LIB, d))]
    plan = []   # (folder_name, season_no, meta_arc_or_None, file_meta)
    for d in arc_dirs:
        folder = os.path.join(LIB, d)
        files = [f for f in sorted(os.listdir(folder)) if f.lower().endswith(VIDEO_EXT)]
        if not files:
            continue
        votes = {}
        file_meta = []
        for fn in files:
            crc = crc_of(fn)
            e = eps.get(crc) if crc else None
            file_meta.append((fn, e))
            if e:
                votes[int(e["arc"])] = votes.get(int(e["arc"]), 0) + 1
        meta_arc = max(votes, key=votes.get) if votes else None
        if d == "Specials" or meta_arc in (None, 0):   # extras / unmatched -> single Season 0
            season_no = 0; meta_arc = 0
            target = "Specials"
        else:
            season_no = meta_arc
            target = f"Season {season_no:02d}"
        target = migrate(d, target)
        plan.append((target, season_no, meta_arc, file_meta))

    # ---- pass 2: write season + episode NFOs (each episode forced into its folder's season) ----
    ep_written = season_written = unmatched = 0
    for d, season_no, meta_arc, file_meta in plan:
        folder = os.path.join(LIB, d)
        arc = arcs.get(meta_arc, {}) if meta_arc else {}
        is_specials = (season_no == 0)
        title = "Specials" if is_specials else (arc.get("title") or clean_name(d))
        plot = None if is_specials else arc.get("description")

        with open(os.path.join(folder, "season.nfo"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<season>\n'
                    + x("title", title) + x("seasonnumber", season_no)
                    + x("plot", plot) + x("lockdata", "true") + "\n</season>\n")
        season_written += 1

        # arc poster (only real arcs have art in the repo)
        if meta_arc:
            ap = os.path.join(folder, "poster.jpg")
            if clean and os.path.exists(ap):
                os.remove(ap)
            if download(f"{POSTER_BASE}/{meta_arc}/poster.png", ap):
                fj = os.path.join(folder, "folder.jpg")
                if clean and os.path.exists(fj):
                    os.remove(fj)
                if not os.path.exists(fj):
                    try:
                        import shutil; shutil.copyfile(ap, fj)
                    except Exception:
                        pass

        seq = 0
        for fn, e in file_meta:
            seq += 1
            stem = os.path.splitext(fn)[0]
            if e:
                ep_title = e.get("title")
                ep_no = seq if is_specials else int(e["episode"])  # specials get clean 1..N
                ep_plot = e.get("description"); aired = e.get("released")
                ep_written += 1
            else:
                ep_title = clean_name(stem); ep_no = seq
                ep_plot = None; aired = None
                unmatched += 1
            with open(os.path.join(folder, stem + ".nfo"), "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<episodedetails>\n'
                        + x("title", ep_title) + x("showtitle", "One Pace")
                        + x("season", season_no) + x("episode", ep_no)
                        + x("plot", ep_plot) + x("aired", aired)
                        + x("lockdata", "true") + "\n</episodedetails>\n")

    print(f"done: seasons={season_written} episodes={ep_written} unmatched_files={unmatched}")

if __name__ == "__main__":
    main()
