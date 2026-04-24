#!/usr/bin/env bash
# Starts the dev stack and prints the LAN URLs other devices on the
# network can connect to. Works in Git Bash / WSL / Linux / macOS.
#
# Run from repo root:
#   bash scripts/dev-up.sh
# Extra flags pass through to docker compose:
#   bash scripts/dev-up.sh --force-recreate

set -euo pipefail

echo
echo "=== Local + LAN URLs to share ==="
echo "  http://localhost:8000                 (this machine only)"

ips=""
if command -v ip >/dev/null 2>&1; then
    ips=$(ip -o -4 addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
elif command -v ifconfig >/dev/null 2>&1; then
    ips=$(ifconfig 2>/dev/null | awk '/inet / {print $2}' | grep -vE '^(127\.|169\.254\.)' || true)
elif command -v ipconfig.exe >/dev/null 2>&1; then
    # Git Bash on Windows — shell out to Windows ipconfig
    ips=$(ipconfig.exe //all | tr -d '\r' | awk -F': *' '/IPv4 Address/ {print $2}' | sed 's/(Preferred)//' | awk '{print $1}')
fi

if [ -z "$ips" ]; then
    echo "  (no LAN adapter detected)"
else
    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        echo "  http://$ip:8000"
    done <<< "$ips"
fi

echo
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build "$@"
