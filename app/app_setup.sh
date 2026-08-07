#!/usr/bin/env bash
# Install the dedicated APP VM's static frontend and same-origin API proxy.
set -euo pipefail

# Resolve every file relative to this script so setup works from any directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"
NGINX_TEMPLATE="${FRONTEND_DIR}/nginx/dreamescapes.conf.template"
WEB_ROOT="${APP_WEB_ROOT:-/var/www/dreamescapes}"
SITE_NAME="dreamescapes"

# dependencies_install.sh exports these values. Direct script execution can
# provide the same variables explicitly, for example API_HOST=10.0.0.12.
APP_LISTEN_PORT="${APP_LISTEN_PORT:-8000}"
API_HOST="${API_HOST:-}"
API_PORT="${API_PORT:-8000}"

# The APP VM must know where to proxy API requests. Ask only during an
# interactive direct run; automation must supply API_HOST explicitly.
if [[ -z "$API_HOST" ]]; then
  if [[ -t 0 ]]; then
    read -r -p "Enter API VM ZeroTier IP or hostname: " API_HOST
  else
    echo "ERROR: Set API_HOST to the API VM ZeroTier IP or hostname." >&2
    exit 1
  fi
fi

# Restrict substituted values to safe hostname and TCP-port characters before
# placing them in an Nginx configuration file.
if [[ ! "$API_HOST" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "ERROR: API_HOST must be an IPv4 address or DNS hostname." >&2
  exit 1
fi
for port_value in "$APP_LISTEN_PORT" "$API_PORT"; do
  if [[ ! "$port_value" =~ ^[0-9]+$ ]] \
    || (( port_value < 1 || port_value > 65535 )); then
    echo "ERROR: APP_LISTEN_PORT and API_PORT must be valid TCP ports." >&2
    exit 1
  fi
done

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: app_setup.sh currently supports Ubuntu/Debian APP VMs." >&2
  exit 1
fi
if [[ ! -f "$NGINX_TEMPLATE" || ! -f "${FRONTEND_DIR}/index.html" ]]; then
  echo "ERROR: APP frontend or Nginx template is missing from the checkout." >&2
  exit 1
fi

# Nginx owns only static delivery and reverse proxying on the APP VM. Django,
# MySQL client libraries, Geoapify credentials, and RabbitMQ credentials are
# intentionally not installed or stored on this role.
echo "Installing the APP frontend web server..."
sudo apt-get update
sudo apt-get install -y curl nginx

# Copy the tracked frontend into a system web root so Nginx does not depend on
# the checkout user's home-directory permissions.
echo "Deploying frontend assets to ${WEB_ROOT}..."
sudo install -d -m 0755 "$WEB_ROOT"
for asset in index.html styles.css config.js logic.js app.js; do
  sudo install -m 0644 "${FRONTEND_DIR}/${asset}" "${WEB_ROOT}/${asset}"
done

# Materialize the Nginx template using validated values. A temporary file lets
# nginx -t reject an invalid configuration before the live service restarts.
temporary_config="$(mktemp)"
trap 'rm -f "$temporary_config"' EXIT
sed \
  -e "s/__APP_PORT__/${APP_LISTEN_PORT}/g" \
  -e "s/__API_HOST__/${API_HOST}/g" \
  -e "s/__API_PORT__/${API_PORT}/g" \
  -e "s|__WEB_ROOT__|${WEB_ROOT}|g" \
  "$NGINX_TEMPLATE" > "$temporary_config"

sudo install -m 0644 "$temporary_config" "/etc/nginx/sites-available/${SITE_NAME}"
sudo ln -sfn "/etc/nginx/sites-available/${SITE_NAME}" \
  "/etc/nginx/sites-enabled/${SITE_NAME}"

# Ubuntu's default site would otherwise win requests when APP_LISTEN_PORT=80.
if [[ -L /etc/nginx/sites-enabled/default ]]; then
  sudo unlink /etc/nginx/sites-enabled/default
fi

sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl restart nginx

# Verify the complete APP-to-API path without making temporary proxy failure
# destructive to the successfully installed frontend.
if ! curl --fail --silent \
  "http://127.0.0.1:${APP_LISTEN_PORT}/api/health" >/dev/null; then
  printf '\033[33mWARNING: APP frontend is installed, but the API proxy health check failed. Verify the API VM address, API service, ZeroTier path, and port.\033[0m\n'
fi

echo "APP VM setup complete."
echo "Open: http://APP_VM_IP:${APP_LISTEN_PORT}"
echo "API proxy target: http://${API_HOST}:${API_PORT}"
echo "Open the APP VM port only to intended users and keep the API port on the trusted VM network."
