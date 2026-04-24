#!/usr/bin/env bash
# Install Docker on a fresh Ubuntu 24.04 VM, then bring up the InvisibleGo
# stack. Run once after provisioning the VM and cloning the repo:
#
#   git clone https://github.com/GeniusPudding/InvisibleGo.git
#   cd InvisibleGo
#   sudo bash deploy/setup-docker.sh
#
# Idempotent: re-running is safe, it skips installation if Docker is
# already present.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    exec sudo bash "$0" "$@"
fi

REPO_DIR="$(cd "$(dirname "$0")/.."; pwd)"
INVOKER=${SUDO_USER:-ubuntu}

if ! command -v docker >/dev/null; then
    echo "==> Installing Docker Engine + compose plugin"
    curl -fsSL https://get.docker.com | sh
fi

# Let the non-root user run `docker` without sudo after next login.
if ! id -nG "$INVOKER" | grep -qw docker; then
    usermod -aG docker "$INVOKER"
    echo "==> Added $INVOKER to docker group (log out + back in to take effect)"
fi

echo "==> Starting stack with docker compose"
cd "$REPO_DIR"
docker compose up -d --build

cat <<EOF

=============================================================
 Stack is up.

 Verify:
   docker compose ps
   docker compose logs -f invisiblego
   docker compose logs -f caddy

 Before going public:
   1. Point your domain's A record at this VM's public IP
   2. Edit deploy/Caddyfile — replace game.example.com with your domain
   3. docker compose restart caddy

 For first-time testing without a domain:
   1. Edit deploy/Caddyfile — comment the domain block, uncomment :80
   2. docker compose restart caddy
   3. Open http://<public-ip>/ in two browsers

 Redeploy after git pull:
   docker compose up -d --build

 Stop / tear down:
   docker compose down           # keep volumes (TLS certs persist)
   docker compose down --volumes # also drop certs (will re-obtain)
EOF
