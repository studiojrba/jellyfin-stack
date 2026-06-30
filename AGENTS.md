# AGENTS.md

## Cursor Cloud specific instructions

This repo is a **Docker Compose–only** self-hosted media stack (the "TorBox *arr stack").
There is **no application source to build and no lint/test/build pipeline or package
manager** — the Python `op_*.py`/`onepace/*.py` scripts are stdlib-only and run inside
containers. "Running the app" means bringing up the Compose stack. See `README.md` for
the architecture and the canonical (WSL2-oriented) setup steps; the notes below are the
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
   `decypharr` fail to start with `path ... is not a shared or slave mount` (this is the
   cloud equivalent of the README's WSL `mount --make-rshared /`):
   `mkdir -p mount && sudo mount --bind mount mount && sudo mount --make-rshared mount`.
5. **Fix bind-mount ownership.** Compose creates `./data` and `./mount` as root; the
   linuxserver images run as `PUID/PGID=1000`, so chown them or the *arrs can't write:
   `sudo chown -R 1000:1000 data mount` (also create `data/media/{movies,tv,anime}` and
   `data/downloads`).
6. Bring services up: `sudo docker compose up -d prowlarr radarr sonarr byparr jellyseerr recyclarr decypharr`.

### Service-specific caveats

- **jellyfin does NOT run here.** Its `deploy.resources.reservations.devices: nvidia`
  requires an NVIDIA GPU/runtime, which the VM lacks (`could not select device driver
  "nvidia"`). To run it locally you must temporarily drop the GPU `deploy` block — do
  **not** commit that change.
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
  files" (and even a `replaceAllMetadata` refresh) will **not** pick up the NFOs. The
  reliable fix is a fresh scan: remove + re-add the library (or delete the One Pace series
  and rescan). A clean scan with all NFOs present resolves all episodes from the NFOs.
- Jellyfin can't run via Compose in the cloud VM (no GPU). To reproduce/inspect Jellyfin
  behavior, run a throwaway CPU-only container and drive it via the REST API, e.g.
  `docker run -d --name jellyfin-test -p 8096:8096 -v $PWD/config/jellyfin-test:/config -v $PWD/data:/data -v $PWD/mount:/mnt/remote:rslave jellyfin/jellyfin:latest`
  (start it after decypharr's mount is up).

### Verifying / interacting

- The *arr apps auto-generate an API key in `config/<app>/config.xml` (`<ApiKey>`). Use it
  for API calls, e.g. `curl -H "X-Api-Key: <key>" http://localhost:7878/api/v3/system/status`.
- Default ports: prowlarr 9696, radarr 7878, sonarr 8989, jellyseerr 5055, byparr 8191,
  decypharr 8282, jellyfin 8096.
- There are no unit/lint/build commands. The closest "health check" tooling is
  `bash op_status.sh` and `python3 op_audit.py`, but note these root-level `op_*` scripts
  contain hardcoded API keys/host values from the original operator's machine and target
  `localhost`; they are not generic test harnesses.
