#!/usr/bin/env python3
"""Symlink One Pace episodes from the decypharr mount into the Jellyfin Anime library.

Arc/season is derived from the *torrent (top-level folder) name*, which always carries
the arc (e.g. "[One Pace][700-800] Dressrosa [720p]" or
"[One Pace][1093-1094] Egghead 21 Extended [1080p][2C16CBB5].mkv"). Individual files
inside batch torrents are sometimes named only by chapter, so we never trust the file
name for the arc. Idempotent. Set OP_CLEAN=1 to wipe & rebuild the library folder.
"""
import os, re, sys
from collections import defaultdict

HOST_MOUNT = os.environ.get("OP_MOUNT", "/home/jrbaprz/torbox-stack/mount")
CONT_MOUNT = os.environ.get("OP_CONT_MOUNT", "/mnt/remote")
LIB        = os.environ.get("OP_LIB", "/home/jrbaprz/torbox-stack/data/media/anime/One Pace")
VIDEO_EXT  = (".mkv", ".mp4", ".avi", ".m4v")
SCAN_SUBDIRS = ["torbox", "__all__"]

def derive_arc(torrent_name):
    """Return (arc_name, [chap_numbers]) parsed from a torrent/folder name."""
    name = torrent_name
    for e in VIDEO_EXT:
        if name.lower().endswith(e):
            name = name[: -len(e)]
            break
    chap_nums = []
    m = re.match(r'^\[One Pace\]\s*\[(?P<chap>[^\]]*)\]\s*(?P<mid>.*)$', name)
    if m:
        chap_nums = [int(x) for x in re.findall(r'\d+', m.group('chap'))]
        mid = m.group('mid')
    else:
        m = re.match(r'^\[One Pace\]\s*(?P<mid>.*)$', name)
        mid = m.group('mid') if m else name
    mid = re.sub(r'\[[^\]]*\]', '', mid)          # drop [1080p], [CRC], etc.
    mid = re.sub(r'\s+', ' ', mid).strip()
    mid = re.sub(r'\s+(Extended|Alternate.*)$', '', mid, flags=re.I).strip()
    mid = re.sub(r'\s+\d{1,3}$', '', mid).strip() # drop trailing episode number
    mid = re.sub(r'\s+v\d+$', '', mid, flags=re.I).strip()  # group "Romance Dawn v2"
    # All 36 real arcs carry a [chapter-range]; releases without one (Fan Letter,
    # Straw Hat Theatre, Warship Island April Fools, Tournament of Power, ...) are
    # side-projects -> consolidate into a single "Specials" season for Jellyfin.
    if not chap_nums:
        return "Specials", []
    arc = mid or "Specials"
    return arc, chap_nums

def is_video(f):
    return f.lower().endswith(VIDEO_EXT)

def main():
    if os.environ.get("OP_CLEAN") == "1" and os.path.isdir(LIB):
        for d in os.listdir(LIB):
            p = os.path.join(LIB, d)
            if os.path.isdir(p):
                for root, dirs, files in os.walk(p, topdown=False):
                    for f in files: os.unlink(os.path.join(root, f))
                    for dd in dirs: os.rmdir(os.path.join(root, dd))
                os.rmdir(p)
        print("cleaned existing library folder")

    found = {}  # filename -> (host_path, cont_path, arc, chap_nums)
    for sub in SCAN_SUBDIRS:
        base = os.path.join(HOST_MOUNT, sub)
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            if "One Pace" not in entry:
                continue
            arc, chap_nums = derive_arc(entry)
            top = os.path.join(base, entry)
            vids = []
            if os.path.isfile(top):
                if is_video(entry): vids.append((base, entry))
            else:
                for root, dirs, files in os.walk(top):
                    for f in files:
                        if is_video(f): vids.append((root, f))
            for root, f in vids:
                if f in found:
                    continue
                host_path = os.path.join(root, f)
                cont_path = CONT_MOUNT + host_path[len(HOST_MOUNT):]
                found[f] = (host_path, cont_path, arc, chap_nums)

    if not found:
        print("No One Pace video files found in the mount yet.")
        return

    arc_nums = defaultdict(list)
    for f,(hp,cp,arc,nums) in found.items():
        arc_nums[arc].extend(nums)
    arc_folder = {}
    for arc, nums in arc_nums.items():
        if arc == "Specials":
            arc_folder[arc] = "Specials"
        elif nums:
            arc_folder[arc] = f"[One Pace][{min(nums)}-{max(nums)}] {arc}"
        else:
            arc_folder[arc] = f"[One Pace] {arc}"

    # Episodes already linked anywhere under LIB (e.g. op_nfo.py migrated arc folders to the
    # canonical "Season NN" layout). Skip them so we never create a duplicate arc-named folder.
    already = set()
    if os.path.isdir(LIB):
        for root, dirs, files in os.walk(LIB):
            for f in files:
                if is_video(f):
                    already.add(f)

    created=existed=0; per_arc=defaultdict(int)
    for f,(hp,cp,arc,nums) in sorted(found.items()):
        if f in already:
            existed += 1; continue
        folder = os.path.join(LIB, arc_folder[arc])
        os.makedirs(folder, exist_ok=True)
        per_arc[arc_folder[arc]] += 1
        link = os.path.join(folder, f)
        if os.path.islink(link) or os.path.exists(link):
            existed += 1; continue
        os.symlink(cp, link); created += 1

    print(f"\nArcs: {len(per_arc)} | linked now: {created} | already linked: {existed} | total files: {len(found)}")
    for a in sorted(per_arc):
        print(f"   {a}  ({per_arc[a]} eps)")

if __name__ == "__main__":
    main()
