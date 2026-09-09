# Mini PC Migration Notes

Status/handoff notes for migrating this stack off a Windows+WSL2+Docker Desktop
gaming PC onto a dedicated always-on mini PC ("jerba-server"). Written for whichever
agent/human picks this up next (Claude Code, Cursor, or future-you) so context isn't
lost between sessions or tools.

## Hardware & OS

- Mini PC: QAZIPO N305 (Intel i3-N305, 8C/8T, 16GB RAM, 512GB NVMe, dual 2.5GbE),
  hostname `jerba-server`.
- OS: Ubuntu Server 26.04 LTS, "minimized" install variant — expect common utilities
  (nano, rfkill, rsync, jq, etc.) to be missing and need `apt install`.
- Access: `ssh jrbaprz@100.114.205.82` (Tailscale IP, preferred) or
  `ssh jrbaprz@192.168.2.53` (LAN ethernet). WiFi is a configured backup
  (`/etc/netplan/60-wifi.yaml`, interface `wlo1`).
- Tailscale is installed and working; `jerba-server` is visible on the tailnet.
- Root filesystem propagation is natively "shared" — the WSL2 stale-bind-mount
  problem class documented in `AGENTS.md` (for the Cursor Cloud VM) does **not**
  apply here.
- `/dev/fuse` exists with correct permissions (decypharr FUSE mount).
- `/dev/dri` exists (`card0` + `renderD128`, Intel N305 iGPU) for Jellyfin Quick
  Sync hardware transcoding — not yet enabled/tested (see Remaining Work).
- Docker Engine + Compose plugin installed via `get.docker.com` (not snap). User
  `jrbaprz` is in the `docker` group.

## Repo

- Canonical remote: `https://github.com/studiojrba/jellyfin-stack` (went through
  two transfers before landing here permanently; all hardcoded old-name path
  references across README/scripts have been fixed and pushed).
- `docker-compose.yml`: Jellyfin's GPU reservation was swapped from the NVIDIA
  `deploy.resources.reservations.devices` block to Intel QSV via a plain
  `devices: - /dev/dri:/dev/dri` passthrough (no discrete GPU on the mini PC).
- Gaming PC's WSL clone lives at `~/torbox-stack` (folder name is stale/cosmetic
  only; its git remote already points at `jellyfin-stack.git`). Mini PC's clone is
  at `~/jellyfin-stack`.
- Workflow: edit on gaming PC's WSL checkout → commit/push → `git pull origin main`
  on the mini PC.

## Fixes applied during first boot on the mini PC (2026-07-15)

Symptom: all 9 containers came up "Up"/"(healthy)" on first `docker compose up -d`,
but `docker exec <container> sh -c 'ls /mnt/remote | wc -l'` showed `0` across
decypharr/radarr/sonarr/jellyfin — the FUSE mount wasn't populating.

Two independent, unrelated root causes, both now fixed:

1. **Stale pre-rotation TorBox key in `config/decypharr/config.json`.**
   decypharr's compose service has **no `TORBOX_KEY` env var** — it only reads
   `api_key`/`download_api_keys` from `config.json`, which still had the old key
   from before rotation. Caused a constant `torbox API error: Status: 403` in
   `docker logs decypharr`. The `.env` `TORBOX_KEY` is unrelated to decypharr; it's
   only consumed by `onepace-maintenance`'s scripts and compose's
   `${TORBOX_KEY:?...}` interpolation guard. Fixed by writing the current `.env`
   key into `config.json`'s `debrids[0].api_key` and `download_api_keys[0]`
   (original backed up to `config/decypharr/config.json.bak-migration-<timestamp>`).

2. **`./data` and `./mount` owned by `root:root`.** Compose creates both as root on
   first `up`; decypharr/radarr/sonarr run as uid 1000. rclone's `rcd` process
   (which itself runs as uid 1000 inside decypharr) hit
   `fusermount3: user has no write access to mountpoint /mnt/remote` and silently
   gave up after 4 retries — this is why every container saw `0` entries; the mount
   never actually got established, not just returned empty. Fixed via
   `sudo chown -R 1000:1000 data mount` (matches the existing `AGENTS.md` note for
   the Cursor Cloud VM, which turns out to apply here too since Compose always
   creates bind-mount directories as root).

   Also had to `mkdir -p data/media/{movies,tv,anime} data/downloads` — the rsync
   restore of `config/` from the old box never created these, since it only copied
   `config/`, not `data/`.

After both fixes + `docker compose restart decypharr`: `Successfully mounted rclone
filesystem`, real content visible identically across decypharr/radarr/sonarr/jellyfin,
and a manually-triggered `onepace-maintenance` run completed cleanly: 463 symlinks
across 37 arcs, NFOs written for 461/463 episodes, series poster written, **zero**
TorBox errors (nothing was missing from the account — `missing=0` — so no mass-add
storm risk).

Also renamed the Jellyfin server identity from the stale `jerba-pc` (leftover from
the old box) to `jerba-jellyfin` by editing `<ServerName>` in
`config/jellyfin/config/system.xml` and restarting the container.

## Known history / context worth remembering

- On the old box, TorBox rate-limiting (429s) was suspected to come from the One
  Pace side specifically (hundreds of episodes) rather than decypharr itself —
  decypharr's own config already has conservative limits
  (`rate_limit: 200/hour`, `download_rate_limit: 10/minute`, `max_downloads: 10`).
  Not yet root-caused; see Remaining Work.
- See `AGENTS.md`'s "One Pace metadata in Jellyfin" section for the full history of
  the NFO/symlink race condition and the two-pass `op_maint.sh` fix that closes it.

## Remaining work (as of 2026-07-15)

1. Enable Intel QSV hardware transcoding in Jellyfin's Playback settings; verify
   One Pace plays back without the "fatal playback error" seen on the old box.
2. ~~Revisit `onepace-maintenance`'s 6-hour re-add cycle / TorBox rate-limit
   safeguards.~~ **Done (2026-07-15):** split into a modulo loop — cheap idempotent
   `op_readd.py` runs hourly (`OP_READD_INTERVAL`, default 3600s), the full
   `op_maint.sh` pass runs every 6th iteration (`OP_FULL_EVERY`, default 6 ≈ 6h),
   and a full pass fires immediately on (re)start. Tightens the purge-decay
   recovery window 6h→1h without increasing the heavy symlink/NFO/metadata load,
   so no added rate-limit exposure. Both knobs are overridable in `.env`.
3. Install/adapt an autoheal systemd service (`rebuild/jellyfin-autoheal.service`)
   on the mini PC — lower priority now that the WSL2 stale-mount bug class is gone,
   but still worth having as a safety net.
