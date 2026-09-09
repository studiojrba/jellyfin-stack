# AGENTS.md

## Cursor Cloud specific instructions

This repo is a **Docker Compose–only** self-hosted media stack (the "TorBox *arr stack").
There is **no application source to build and no lint/test/build pipeline or package
manager** — the Python `op_*.py`/`onepace/*.py` scripts are stdlib-only and run inside
containers. "Running the app" means bringing up the Compose stack. See `README.md` for
the architecture and the canonical (native-Linux) setup steps; the notes below are the
non-obvious things that differ in the Cursor Cloud Linux VM.

### Starting the stack (in order)

1. **Start the Docker daemon manually** — this VM has no systemd, so `dockerd` is not
   auto-started and `systemctl` does not work. Run it backgrounded (e.g. in a tmux
   session) and use `sudo` for all docker commands:
   `sudo dockerd > /tmp/dockerd.log 2>&1 &` then wait until `sudo docker info` succeeds.
   Docker is configured with the `fuse-overlayfs` storage driver (`/etc/docker/daemon.json`).
2. **`.env` is required for every compose command.** `docker-compose.yml` interpolates
   `${TORBOX_KEY:?...}`, so *any* `docker compose` invocation aborts if `TORBOX_KEY` is
   unset — even when targeting unrelated services. `.env` is gitignored; create it with a
   placeholder to run everything except real TorBox/usenet content:
   `printf 'TORBOX_KEY=placeholder\n' > .env`.
3. **Seed `config/` from `examples/`** (gitignored) per `README.md`:
   `mkdir -p config/decypharr config/recyclarr && cp examples/decypharr/config.json config/decypharr/ && cp examples/recyclarr/recyclarr.yml config/recyclarr/`.
4. **`./mount` must have shared/slave mount propagation**, or `sonarr`/`radarr`/`jellyfin`/
   `decypharr` fail to start with `path ... is not a shared or slave mount`. The README
   targets a native Linux host where systemd/decypharr handle this; in the bare VM set it
   up by hand:
   `mkdir -p mount && sudo mount --bind mount mount && sudo mount --make-rshared mount`.
5. **Fix bind-mount ownership.** Compose creates `./data` and `./mount` as root; the
   linuxserver images run as `PUID/PGID=1000`, so chown them or the *arrs can't write:
   `sudo chown -R 1000:1000 data mount` (also create `data/media/{movies,tv,anime}` and
   `data/downloads`).
6. Bring services up: `sudo docker compose up -d prowlarr radarr sonarr byparr jellyseerr recyclarr decypharr`.

### Service-specific caveats

- **jellyfin does NOT run here.** It maps `/dev/dri` for Intel QuickSync (QSV) hardware
  transcoding, which the VM lacks. To run it locally you must temporarily drop the
  `devices: /dev/dri` mapping (Jellyfin falls back to software transcoding) — do **not**
  commit that change. See the throwaway CPU-only container recipe below for inspecting
  Jellyfin behavior.
- **decypharr runs fine** (FUSE `/dev/fuse` is available) and mounts its rclone VFS at
  `/mnt/remote`, but logs `torbox API error: Status: 403` with a placeholder key. Real
  content/streaming requires a paid **TorBox** account key in
  `config/decypharr/config.json` + `.env`.
- **onepace-maintenance** loops a script that hits the TorBox API; it stays up but does
  nothing useful without a real key.
- **Mount ordering matters.** The rslave consumers (`radarr`/`sonarr`/`jellyfin`/
  `onepace-maintenance`) only see decypharr's content if they start *after* decypharr has
  established its rclone FUSE mount. If you restart/recreate `decypharr`, restart those
  consumers afterward so the new mount propagates. Also note `docker compose restart
  decypharr` can fail with a bind-mount error after an rclone unmount left
  `/workspace/mount` as a dead FUSE endpoint (`transport endpoint is not connected`); fix
  by unmounting it (`sudo umount -lf /workspace/mount`), then redo step 4's
  bind+`make-rshared`, then `docker compose up -d decypharr`.
- **recyclarr** runs on `CRON_SCHEDULE=@daily` and only syncs once the placeholder
  Radarr/Sonarr `api_key`s in `config/recyclarr/recyclarr.yml` are replaced with the real
  auto-generated keys.

### One Pace metadata in Jellyfin (common "it's broken" report)

If One Pace episodes show the raw filename (e.g. `[One Pace…`) and/or no episode
numbers in Jellyfin, the data pipeline is almost certainly fine — it's a Jellyfin
metadata-cache problem. Key facts learned from debugging:
- `op_nfo.py` generates per-episode NFOs (`<videostem>.nfo`, CRC-keyed) + season/series
  NFOs and posters. It does **not** generate per-episode thumbnails, so every episode in
  an arc correctly falls back to the arc/season poster — identical episode images are
  expected, not a bug.
- Jellyfin **cannot parse One Pace's bracketed filenames into episodes without the NFOs**
  (verified: removing an episode's NFO makes Jellyfin drop the episode entirely). So
  correct One Pace display depends entirely on `op_nfo.py` having run successfully — which
  requires the FUSE mount to be visible to `onepace-maintenance` (see the mount-ordering
  caveat above). A run that logs `library not found` / `op_nfo.py failed` means no episode
  NFOs were written.
- The NFOs use `<lockdata>true</lockdata>`. If Jellyfin first scanned the files before the
  NFOs existed, those items are cached/stuck and an incremental "Scan for new and updated
  files" (and even a per-item or per-series `replaceAllMetadata` refresh) will **not** pick
  up the NFOs — verified against a real 10.11.x server (see reproduction method below). The
  only fix for an *already-stuck* item is a fresh scan: remove + re-add the library, or
  delete the One Pace series and rescan (`onepace/op_dbclean.py` does this surgically at the
  SQLite level — Jellyfin stopped, DB rows only — so it doesn't nuke files the way the
  `DELETE /Items/{id}` REST endpoint does; on this stack the "files" are symlinks anyway, so
  `op_symlink.py`/`op_nfo.py` recreate them + their NFOs on the next maintenance cycle).
- **Expected fallout of the fresh-scan remedy: TorBox 429 rate-limiting.** Deleting the One
  Pace series and rescanning makes Jellyfin probe every episode (~460 files); each probe makes
  decypharr request a fresh TorBox download link, and that burst reliably trips TorBox's rate
  limit. Symptom: playback fails with "Unable to find a valid media source", reads inside the
  jellyfin container fail with `Input/output error`, and `docker compose logs decypharr` shows
  `failed to get download link: 429: HTTP 429 Too Many Requests`. This is *not* a mount or
  metadata problem — the fix is to stop triggering scans/reads and wait (~30–60 min) for the
  limit to reset, then test playback of a single episode. `rebuild/13_onepace_repair.sh`'s
  media-read test distinguishes this case: symlink/NFO counts healthy + `dd` I/O errors +
  429s in decypharr logs = rate-limited, not broken.
- **Root cause of *new* episodes getting stuck (fixed):** the race above isn't rare — it's
  the network round-trip. `op_nfo.py` fetches `data.min.json` from GitHub before it can write
  any NFO, and that fetch (or a Cloudflare/GitHub hiccup, per the script's own docstring) can
  take anywhere from ~100ms to tens of seconds. If Jellyfin's own (independently-scheduled)
  library scan fires in the gap between `op_symlink.py` creating a new symlink and
  `op_nfo.py` finishing that fetch, the new episode is poisoned forever. `op_maint.sh` now
  runs `op_nfo.py` in two passes to close this: `OP_NFO_FETCH_ONLY=1` warms a hot cache
  (`OP_NFO_CACHE`, default `/data/.op_nfo_metadata_cache.json`) *before* `op_symlink.py` runs,
  then `OP_NFO_OFFLINE=1` writes NFOs immediately after using that cache — no network call in
  between symlinking and writing, so the window shrinks from a network round-trip to a local
  directory listing (verified: reproduced the stuck-forever state with a symlink-then-slow-fetch
  race against a real Jellyfin container, then reran the same race with the two-pass flow and
  the episode came in with correct metadata on the first scan). This doesn't retroactively fix
  already-stuck items (still needs the manual remedy above), and a truly simultaneous scan is
  still theoretically possible (the window is milliseconds, not zero), but it turns "network
  latency reliably wins the race" into "requires exact-millisecond coincidence."
- Jellyfin can't run via Compose in the cloud VM (no GPU). To reproduce/inspect Jellyfin
  behavior, run a throwaway CPU-only container and drive it via the REST API, e.g.
  `docker run -d --name jellyfin-test -p 8096:8096 -v $PWD/config/jellyfin-test:/config -v $PWD/data:/data -v $PWD/mount:/mnt/remote:rslave jellyfin/jellyfin:latest`
  (start it after decypharr's mount is up). This image auto-completes the setup wizard and
  creates a default admin on first API touch *without* exposing the generated password; get a
  usable token via `POST /Startup/User {"Name":"admin","Password":"..."}` immediately after
  the container is healthy (before anything else hits `/Startup/*`), or reset via
  `POST /Users/ForgotPassword` and read the pin file it reports. `DELETE /Items/{id}` deletes
  the underlying file, not just the DB entry — expected/safe for symlinked libraries here
  (self-heals next maintenance cycle) but destructive against real test fixtures.

### Verifying / interacting

- The *arr apps auto-generate an API key in `config/<app>/config.xml` (`<ApiKey>`). Use it
  for API calls, e.g. `curl -H "X-Api-Key: <key>" http://localhost:7878/api/v3/system/status`.
- Default ports: prowlarr 9696, radarr 7878, sonarr 8989, jellyseerr 5055, byparr 8191,
  decypharr 8282, jellyfin 8096.
- There are no unit/lint/build commands. The closest "health check" tooling is
  `bash op_status.sh` and `python3 op_audit.py`, but note these root-level `op_*` scripts
  contain hardcoded API keys/host values from the original operator's machine and target
  `localhost`; they are not generic test harnesses.
