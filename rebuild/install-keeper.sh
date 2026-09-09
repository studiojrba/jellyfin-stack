#!/usr/bin/env bash
# Install (or refresh) the jellyfin-stack keeper as a systemd timer.
#
# Generates the unit files from the templates in this dir, substituting the
# current user and repo path, installs them to /etc/systemd/system, and enables
# the timer (fires ~3min after boot, then every 15min). Idempotent — safe to
# re-run after pulling changes to stack_keeper.sh or the unit templates.
#
# Requires: sudo, systemd, and the invoking user in the `docker` group.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"

echo "Installing keeper for user '$USER_NAME' at repo '$REPO'"

if ! id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx docker; then
  echo "WARNING: '$USER_NAME' is not in the 'docker' group — the keeper runs" >&2
  echo "         docker commands as this user and will fail without it." >&2
  echo "         Fix with: sudo usermod -aG docker $USER_NAME && newgrp docker" >&2
fi

for unit in stack-keeper.service stack-keeper.timer; do
  sed -e "s|__USER__|$USER_NAME|g" -e "s|__REPO__|$REPO|g" \
    "$REPO/rebuild/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
  echo "  wrote /etc/systemd/system/$unit"
done

sudo systemctl daemon-reload
sudo systemctl enable --now stack-keeper.timer

echo
echo "Keeper installed. Timer status:"
systemctl list-timers stack-keeper.timer --no-pager || true
echo
echo "Tail live keeper logs with:  journalctl -u stack-keeper.service -f"
echo "Or the script's own log:     tail -f $REPO/rebuild/stack_keeper.log"
