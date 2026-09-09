# Jellyfin *arr Media Stack (native Linux + Docker)

**An all-in-one, zero-storage solution for perfect media streaming from the cloud.**
No NAS, no hard drives, no disk arrays — and no capacity limits, ever. Your entire
library lives in the cloud (TorBox debrid) and streams on demand, so you're never
bottlenecked by local space. Just **request a movie or show in Seerr, and moments
later watch it in Jellyfin** — discovery, grab, organize, transcode, and serve, with
the whole pipeline running (and self-healing) on its own.

A debrid-backed media automation stack: **decypharr** owns a FUSE cloud mount and
mocks qBittorrent + SABnzbd for the *arrs, which symlink grabbed content from
**TorBox** (torrent + usenet) into a Jellyfin library.

```
decypharr (mount engine, mocks qBit/SAB)  ──┐
prowlarr  (indexer hub)                      │  Sonarr/Radarr grab → decypharr →
radarr / sonarr (automation)                 │  symlink into /data/media → Jellyfin
byparr    (Cloudflare bypass)                │
jellyfin / jellyseerr (serve / request)      │
recyclarr (TRaSH profiles)  onepace-maintenance (keeps One Pace alive)
```

Runs on a native Linux host (developed on an Intel N305 mini PC) with Docker
Engine. Jellyfin transcodes via **Intel Quick Sync (QSV)** through `/dev/dri`.

## What's in this repo vs. what stays local

**Committed (the reproducible scaffold):**
- `docker-compose.yml` — full architecture (secrets pulled from `.env`)
- `.env.example` — the two keys you need to fill in
- `examples/` — sanitized config templates with placeholder secrets
- `rebuild/` — the stack keeper (self-healing) + one-off recovery scripts
- `onepace/` — the One Pace keeper scripts

**Never committed (see `.gitignore`):** `.env`, `config/` (live app DBs + real
secrets, incl. Jellyfin's QSV tuning), `data/` + `mount/` (the media/symlink farm
+ FUSE point). These are per-machine / account-specific and/or hold credentials.

> The `examples/` configs are trimmed templates for reproduction. Your live
> `config/` (with full settings + history) stays on the machine and is rebuilt
> per-host — see "Migrating" below.

## Set up on a new Linux PC

**Prereqs:**
- A Linux host with Docker Engine + the Compose plugin (`docker compose`).
- The invoking user in the `docker` group (`sudo usermod -aG docker $USER`,
  then log out/in). PUID/PGID in the compose file assume UID/GID `1000` — adjust
  if yours differ (`id -u` / `id -g`).
- For Jellyfin hardware transcoding: an Intel iGPU with Quick Sync, and
  `/dev/dri` present on the host. (No NVIDIA/NVENC — this stack uses QSV.)

**1. Clone + secrets**
   ```bash
   git clone <your-repo-url> ~/jellyfin-stack && cd ~/jellyfin-stack
   cp .env.example .env            # set TORBOX_KEY now; JELLYFIN_API_KEY comes in step 3
   mkdir -p config/decypharr config/recyclarr
   cp examples/decypharr/config.json config/decypharr/config.json
   cp examples/recyclarr/recyclarr.yml config/recyclarr/recyclarr.yml
   ```
   Edit `config/decypharr/config.json` (TorBox key, usenet providers) and
   `config/recyclarr/recyclarr.yml` (Radarr/Sonarr API keys — you'll get these in
   the next step).

   > **Size `mount.rclone.vfs_cache_max_size` to your disk.** The template ships
   > `20G`, which suits this box's 98G root. rclone's VFS cache lives in
   > `config/decypharr/cache` — the *same* filesystem as the Docker images and the
   > usenet NZB store — and rclone treats the value as a hard ceiling it will grow
   > to, so setting it near the disk size fills the disk. When that happens rclone
   > dies *inside* a container that still reports healthy, the mount empties, and
   > every library symlink dangles until decypharr is restarted. Leave room for the
   > rest of the stack (here: ~13G images + ~6G NZB store).

**2. First boot**
   ```bash
   docker compose up -d
   ```
   The *arrs generate their own `config.xml` (with fresh API keys) on first run.
   Copy those keys into `config/decypharr/config.json` (`arrs[].token`) and
   `config/recyclarr/recyclarr.yml`, then:
   ```bash
   docker compose restart decypharr recyclarr
   ```

**3. Wire it up in the UIs** (Prowlarr 9696, Sonarr 8989, Radarr 7878,
   Jellyfin 8096, Jellyseerr 5055):
   - **Prowlarr** — add your indexers + connect the Sonarr/Radarr apps.
   - **Sonarr/Radarr** — add the qBittorrent download client (host `decypharr`,
     port `8282`) and the SABnzbd client (URL base `/sabnzbd`); set root folders
     `/data/media/{movies,tv,anime}`. recyclarr pushes the quality profiles.
   - **Jellyfin** — add libraries pointing at `/data/media/{movies,tv,anime}`;
     under Dashboard → Playback, enable **Intel QuickSync (QSV)** hardware
     acceleration. Then Dashboard → API Keys → **+**, and put the generated key
     into `.env` as `JELLYFIN_API_KEY=` (the keeper uses it for rescans).
   - **Jellyseerr** — point it at Jellyfin + Sonarr/Radarr.

**4. Install the stack keeper** (the self-healing timer — see below):
   ```bash
   bash rebuild/install-keeper.sh
   ```
   This generates the systemd units for your user/path, installs them, and enables
   the timer. Re-run it any time you pull changes to the keeper.

## The stack keeper (self-healing)

`rebuild/stack_keeper.sh`, installed as the `stack-keeper` systemd timer (fires
~3 min after boot, then every 15 min). It's the standing safety net that keeps the
stack healthy without manual intervention. Each run:

1. **Mount health** — detects decypharr's rclone FUSE mount going stale (e.g.
   after a decypharr restart/crash: consumers see 0 entries, or the host
   mountpoint is a disconnected transport endpoint), unmounts, brings decypharr
   back, and re-propagates to the consumer containers.
2. **Symlink health** — idempotently rebuilds any missing Sonarr/Radarr library
   symlinks from cached mount content (`arr_symlink_rebuild.py`). No-op when
   nothing's missing.
3. **Queue health** — clears decypharr SAB (usenet) downloads stuck at 100% that
   never fired their completion transition (`unstick_stuck_queue.py`), guarded to
   only touch items stuck across ≥1 cycle.
4. **Import health** — force-imports downloads stuck at `importPending` because
   the analyzer couldn't read a runtime off the FUSE symlink ("Unable to determine
   if file is a sample" — `unstick_sample_imports.py`).
5. **Rescan** — triggers a Jellyfin library refresh only if something above
   actually changed (needs `JELLYFIN_API_KEY` in `.env`; skipped if unset).

Useful commands:
```bash
systemctl list-timers stack-keeper.timer        # when it next runs
journalctl -u stack-keeper.service -f           # live run output
tail -f rebuild/stack_keeper.log                # the script's own log
sudo systemctl start stack-keeper.service       # run a heal pass right now
```

## One Pace — the parallel pipeline

[One Pace](https://onepace.net) is a **community fan-edit** that re-cuts the *One
Piece* anime to follow the manga's pacing, trimming filler and padding into tight,
arc-based episodes. Because it's an unofficial fan project, it lives completely
outside the normal automation and needs its own handling:

- **No metadata provider knows it exists.** One Pace isn't on TVDB, AniDB, or TMDb,
  and its files are named by story arc + a CRC-32 hash, not the `SxxEyy` that
  scrapers expect. Point Jellyfin at it raw and you get bare filenames — or worse,
  it gets mis-identified as the full *One Piece* series. There's an official One Pace
  Jellyfin plugin, but it depends on `api.onepace.net` (frequently down with
  Cloudflare 525s); when that fails, Jellyfin silently falls back to AniDB and
  mislabels everything.
- **The *arrs can't grab it.** There's no indexer release to search for — the
  canonical set is a hand-curated list of specific torrents. So it bypasses Prowlarr/
  Sonarr/Radarr entirely: `onepace/onepace_final.json` is the manifest, and its
  episodes are added straight to TorBox.

That's why One Pace runs as its own sidecar, `onepace-maintenance`, on its own loop
(a cheap re-add hourly, the full pipeline ~every 6h). Each full pass:

1. **Re-add** (`op_readd.py`) — TorBox Standard purges idle torrents, so debrid
   content goes cold. Re-adding the manifest keeps One Pace warm and instantly
   streamable. This is the core anti-decay step (and the cheap thing the hourly run
   does on its own).
2. **Metadata** (`op_nfo.py`) — writes **local** Jellyfin NFO files + arc posters,
   keyed by each file's CRC-32, sourced from the static
   [`one-pace-metadata`](https://github.com/ladyisatis/one-pace-metadata) GitHub repo
   (no live API). Every entry gets `<lockdata>true</lockdata>` so Jellyfin's online
   agents never touch — and never re-mangle — One Pace again.
3. **Symlinks** (`op_symlink.py`) — links the re-added mount content into the
   `data/media/anime/One Pace` library.

Ordering matters: the metadata cache is warmed *before* new symlinks go live, because
if Jellyfin scans a new episode before its NFO exists, it permanently caches the raw
filename — no rescan or forced refresh fixes it, only removing and re-adding the item.
The loop keeps that window down to a filesystem write.

Knobs (override in `.env`): `OP_READD_INTERVAL` (re-add cadence, default `3600`s) and
`OP_FULL_EVERY` (full pipeline every Nth run, default `6`).

## Migrating your *existing* library to a new PC

Git carries the scaffold, not the live state. To carry over your actual Sonarr/
Radarr/Jellyfin setup, restore from each app's own backup (Settings → General →
Backups) on the new instance, or just let the fresh instance re-add content — the
media itself lives on your TorBox account and re-caches on demand. Jellyfin's QSV
transcoding tuning lives in the (gitignored) `config/jellyfin` — re-enable it in
the UI per step 3.

## Security

Any credentials that were ever committed in plaintext (TorBox key, usenet
passwords, *arr API keys, OpenSubtitles password) should be rotated if this repo
was pushed. Live secrets are kept out of Git via `.gitignore`; only the
placeholder `examples/` templates and `.env.example` are tracked.
