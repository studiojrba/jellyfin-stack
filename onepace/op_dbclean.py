#!/usr/bin/env python3
"""Surgically remove all One Pace items from jellyfin.db + clear orphaned UserData rows
(left by earlier API deletes) that cause 'UNIQUE constraint failed: UserData' on rescan.
Run with Jellyfin STOPPED, as root (root-owned db). Makes a backup first."""
import sqlite3, shutil, os, time
DB = "/db/jellyfin.db"
SERIES = "E562BE9E-37AD-3DEF-A537-2AA5E3C318CF"

bak = f"{DB}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
shutil.copyfile(DB, bak)
print("backup:", bak)

con = sqlite3.connect(DB); c = con.cursor()
con.execute("PRAGMA foreign_keys=OFF")

# 1) collect every One Pace item id (series + seasons + episodes, incl stale old-path ones)
ids = set([SERIES])
for r in c.execute("SELECT Id FROM BaseItems WHERE Path LIKE '%/One Pace%'"):
    ids.add(r[0])
for col in ("SeriesId", "ParentId", "SeasonId", "TopParentId"):
    try:
        for r in c.execute(f"SELECT Id FROM BaseItems WHERE {col}=?", (SERIES,)):
            ids.add(r[0])
    except sqlite3.OperationalError:
        pass
ids = list(ids)
print("One Pace items to remove:", len(ids))

tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
def cols(t): return [x[1] for x in c.execute(f"PRAGMA table_info('{t}')")]
def chunks(l, n=400):
    for i in range(0, len(l), n): yield l[i:i+n]

removed = {}
for t in tabs:
    if t == "BaseItems": continue
    tcols = cols(t)
    for col in ("ItemId", "ParentItemId"):
        if col in tcols:
            tot = 0
            for ch in chunks(ids):
                c.execute(f"DELETE FROM {t} WHERE {col} IN ({','.join('?'*len(ch))})", ch)
                tot += c.rowcount if c.rowcount and c.rowcount > 0 else 0
            if tot: removed[f"{t}.{col}"] = tot

for ch in chunks(ids):
    c.execute(f"DELETE FROM BaseItems WHERE Id IN ({','.join('?'*len(ch))})", ch)

# 2) clear orphaned UserData (guarded: only if id formats match, so we never nuke valid rows)
sample = c.execute("SELECT ItemId FROM UserData LIMIT 1").fetchone()
if sample:
    match = c.execute("SELECT COUNT(*) FROM UserData WHERE ItemId IN (SELECT Id FROM BaseItems)").fetchone()[0]
    if match > 0:   # formats are compatible -> safe to delete true orphans
        c.execute("DELETE FROM UserData WHERE ItemId NOT IN (SELECT Id FROM BaseItems)")
        print("orphaned UserData rows removed:", c.rowcount)
    else:
        print("WARNING: UserData/BaseItems id formats look incompatible; skipped orphan cleanup")

con.commit()
print("deleted from:", removed)
print("remaining One Pace BaseItems:",
      c.execute("SELECT COUNT(*) FROM BaseItems WHERE Path LIKE '%/One Pace%'").fetchone()[0])
con.execute("VACUUM"); con.close()
print("done")
