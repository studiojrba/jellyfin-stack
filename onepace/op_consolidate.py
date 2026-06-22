#!/usr/bin/env python3
"""One-time: move One Pace 'special' arc folders (those without a [chapter-range])
into a single 'Specials' folder so Jellyfin shows one Season 0. Safe: moves symlinks
(absolute targets) and deletes only the emptied wrapper folders + their .nfo/.jpg."""
import os, shutil
LIB = os.environ.get("OP_LIB", "/home/jrbaprz/torbox-stack/data/media/anime/One Pace")
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v")

specials = os.path.join(LIB, "Specials")
os.makedirs(specials, exist_ok=True)

moved = 0
for d in sorted(os.listdir(LIB)):
    p = os.path.join(LIB, d)
    if not os.path.isdir(p) or d == "Specials":
        continue
    # real arc folders look like "[One Pace][1-7] Romance Dawn" (double bracket)
    if d.startswith("[One Pace]["):
        continue
    if not d.startswith("[One Pace]"):
        continue
    # this is a special wrapper folder -> move its videos into Specials
    for f in sorted(os.listdir(p)):
        src = os.path.join(p, f)
        if f.lower().endswith(VIDEO_EXT) and (os.path.islink(src) or os.path.isfile(src)):
            dst = os.path.join(specials, f)
            if not os.path.exists(dst):
                shutil.move(src, dst)
                moved += 1
    # remove leftover metadata + empty dir
    for f in os.listdir(p):
        fp = os.path.join(p, f)
        if os.path.isfile(fp) or os.path.islink(fp):
            os.unlink(fp)
    try:
        os.rmdir(p)
        print(f"consolidated + removed: {d}")
    except OSError as e:
        print(f"could not remove {d}: {e}")

print(f"\nmoved {moved} special episode links into Specials/")
print("Specials now contains:")
for f in sorted(os.listdir(specials)):
    if f.lower().endswith(VIDEO_EXT):
        print("   ", f)
