#!/usr/bin/env bash
set -euo pipefail

# Read-only preflight. Does not stop or change any host process/container.
api_port="${API_HOST_PORT:-8001}"
if [[ ! "$api_port" =~ ^[0-9]+$ ]] || (( api_port < 1 || api_port > 65535 )); then
  echo "Invalid API_HOST_PORT: expected a TCP port from 1 to 65535." >&2
  exit 2
fi

if ! command -v ss >/dev/null 2>&1; then
  echo "Cannot verify ports: install/use iproute2 so the ss command is available." >&2
  exit 2
fi

check_free() {
  local port="$1" label="$2"
  if ss -H -ltn "sport = :${port}" | grep -q .; then
    echo "Port ${port} (${label}) is already listening; refusing to continue." >&2
    ss -ltn "sport = :${port}" >&2 || true
    exit 1
  fi
  echo "Port ${port} (${label}) appears free."
}

check_free "$api_port" "MythosLive loopback API binding"

# Use this only when introducing a new public reverse-proxy listener. If a proxy
# already owns these ports, integrate its existing vhost instead of running this.
if [[ "${1:-}" == "--new-proxy" ]]; then
  check_free 80 "new reverse proxy HTTP listener"
  check_free 443 "new reverse proxy HTTPS listener"
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--new-proxy]" >&2
  exit 2
fi
