# TorBox *arr Media Stack (WSL2 + Docker Desktop)

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

## What's in this repo vs. what stays local

**Committed (the reproducible scaffold):**
- `docker-compose.yml` — full architecture (secrets pulled from `.env`)
- `recyclarr` settings stub, `onepace/` scripts, `rebuild/` recovery + auto-heal
- `examples/` — sanitized config templates with placeholder secrets
- `.env.example`

**Never committed (see `.gitignore`):** `.env`, `config/` (live app DBs + real
secrets), `data/` + `mount/` (the media/symlink farm + FUSE point). These are
per-machine / account-specific and/or contain credentials.

> The `examples/` configs are trimmed templates for reproduction. Your live
> `config/` (with full settings + history) stays on the machine and is rebuilt
> per-host.

## Set up on a new Windows PC

Prereqs: Windows + Docker Desktop with WSL2 integration, an Ubuntu WSL distro,
and an NVIDIA GPU (for Jellyfin NVENC).

1. **WSL prerequisite** — the cloud mount needs a shared root. In `/etc/wsl.conf`:
   ```ini
   [boot]
   systemd=true
   command=mount --make-rshared /
   ```
   Then `wsl --shutdown` from Windows and reopen the distro.

2. **Clone + secrets**
   ```bash
   git clone <your-repo-url> ~/torbox-stack && cd ~/torbox-stack
   cp .env.example .env            # set TORBOX_KEY
   mkdir -p config/decypharr config/recyclarr
   cp examples/decypharr/config.json config/decypharr/config.json
   cp examples/recyclarr/recyclarr.yml config/recyclarr/recyclarr.yml
   ```
   Edit `config/decypharr/config.json` (TorBox key, usenet providers) and
   `config/recyclarr/recyclarr.yml` (Radarr/Sonarr API keys).

3. **First boot**
   ```bash
   docker compose up -d
   ```
   The *arrs generate their own `config.xml` (note the new API keys) on first
   run. Put those keys into `config/decypharr/config.json` (`arrs[].token`) and
   `config/recyclarr/recyclarr.yml`, then `docker compose restart decypharr recyclarr`.

4. **Wire it up in the UIs** (Prowlarr 9696, Sonarr 8989, Radarr 7878, Jellyfin 8096):
   add the 4 indexers in Prowlarr + connect Sonarr/Radarr apps; add the qBittorrent
   (host `decypharr` port `8282`) and SABnzbd (URL base `/sabnzbd`) download clients;
   set root folders `/data/media/{movies,tv,anime}`. recyclarr pushes quality profiles.

5. **Install the auto-heal service** (prevents the stale-mount issue below):
   ```bash
   chmod +x rebuild/autoheal.sh rebuild/04_recreate.sh
   sudo cp rebuild/torbox-autoheal.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now torbox-autoheal.service
   ```

## The stale-bind-mount gotcha (important)

On WSL2 + Docker Desktop, containers with `restart: unless-stopped` can auto-start
**before the WSL filesystem is mounted** after a reboot. Docker then binds empty
snapshot dirs, so apps look "blank/unconfigured" and decypharr's rclone mount is
empty — even though your real `config/` is fine.

**Fix:** recreate the containers so they re-bind the real configs:
```bash
bash rebuild/04_recreate.sh      # manual one-shot
```
`rebuild/autoheal.sh` (installed as the systemd service above) does this
automatically on boot, only when it detects the stale signature.

## Migrating your *existing* library to a new PC

Git is for the scaffold, not the live state. To carry over your actual Sonarr/
Radarr/Jellyfin library, restore from the apps' own backups (Settings → General →
Backups) on the new instance, or just let the fresh instance re-add content — the
media itself lives on your TorBox account and re-caches on demand.

## Security

The credentials that were previously committed in plaintext (TorBox key, usenet
passwords, *arr API keys, OpenSubtitles password) should be rotated if this repo
was ever pushed, and are kept out of Git going forward via `.gitignore`.
