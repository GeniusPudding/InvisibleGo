#!/usr/bin/env bash
# One-shot installer for a fresh Ubuntu 22.04 / 24.04 VM (AWS EC2, Oracle
# Cloud, Contabo, etc.). Run from inside a cloned copy of the repo:
#
#   git clone <repo-url> ~/InvisibleGo
#   cd ~/InvisibleGo
#   sudo bash deploy/setup.sh
#
# Creates a dedicated `invisiblego` system user, installs the app to
# /opt/invisiblego inside its own Python venv, installs Caddy for TLS,
# and enables both services at boot.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    exec sudo bash "$0" "$@"
fi

REPO_DIR="$(cd "$(dirname "$0")/.."; pwd)"
APP_DIR=/opt/invisiblego
USER_NAME=invisiblego

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip curl gnupg rsync \
    debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null; then
    echo "==> Installing Caddy"
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    echo 'deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update
    apt-get install -y caddy
fi

echo "==> Creating service user"
id "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$USER_NAME"

echo "==> Copying app to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete --exclude='.git' --exclude='venv' --exclude='__pycache__' \
    --exclude='tests' --exclude='dist' --exclude='build' \
    "$REPO_DIR/core" "$REPO_DIR/protocol" "$REPO_DIR/transport" "$REPO_DIR/frontend" \
    "$REPO_DIR/pyproject.toml" "$APP_DIR/"
chown -R "$USER_NAME:$USER_NAME" "$APP_DIR"

echo "==> Creating Python venv and installing web deps"
sudo -u "$USER_NAME" python3 -m venv "$APP_DIR/venv"
sudo -u "$USER_NAME" "$APP_DIR/venv/bin/pip" install --upgrade pip --quiet
sudo -u "$USER_NAME" "$APP_DIR/venv/bin/pip" install --quiet -e "$APP_DIR[web]"

echo "==> Installing systemd unit and Caddyfile"
install -m 644 "$REPO_DIR/deploy/invisiblego.service" /etc/systemd/system/invisiblego.service
if [ -f /etc/caddy/Caddyfile ] && [ ! -f /etc/caddy/Caddyfile.bak ]; then
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak
fi
install -m 644 "$REPO_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile

echo "==> Starting services"
systemctl daemon-reload
systemctl enable --now invisiblego
systemctl enable --now caddy

echo ""
echo "Install complete. Service states:"
systemctl is-active invisiblego || true
systemctl is-active caddy || true

cat <<'EOF'

Next steps:
  1. If you have a domain:
       - Point an A record at this VM's public IP
       - Edit /etc/caddy/Caddyfile: replace game.example.com with your domain
       - sudo systemctl reload caddy
  2. If no domain yet (testing):
       - Edit /etc/caddy/Caddyfile, comment the domain block, uncomment the :80 block
       - sudo systemctl reload caddy
       - Open AWS Security Group for port 80 (and 443 if using TLS)
       - Visit http://<public-ip>/ in two browsers
  3. Logs:
       journalctl -u invisiblego -f
       journalctl -u caddy -f
  4. To redeploy after pulling new code: sudo bash deploy/setup.sh
EOF
