#!/usr/bin/env bash
# Install and run the dedicated API VM's Django/backend process.
set -euo pipefail

# Resolve repository resources without depending on the caller's directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
SERVICE_TEMPLATE="${SCRIPT_DIR}/systemd/dreamescapes-api.service.template"
SERVICE_NAME="dreamescapes-api.service"

# The API listens on the trusted VM network. Nginx on the APP VM is the public
# browser endpoint and forwards /api requests to this address and port.
API_BIND_ADDRESS="${API_BIND_ADDRESS:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
API_WORKERS="${API_WORKERS:-3}"

# Create or replace one KEY=value entry without disturbing other private
# settings already stored in the repository-level .env file.
set_env_value() {
  local key="$1"
  local value="$2"
  local temp_file

  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true

  if grep -q "^${key}=" "$ENV_FILE"; then
    temp_file="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
    awk -v key="$key" -v value="$value" '
      BEGIN { prefix = key "=" }
      index($0, prefix) == 1 { print prefix value; next }
      { print }
    ' "$ENV_FILE" > "$temp_file"
    chmod 600 "$temp_file" 2>/dev/null || true
    mv "$temp_file" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

# Optionally collect the external destination-service key without displaying
# it in the terminal or writing it to a tracked example file.
configure_geoapify_key() {
  local answer
  local api_key

  # End-of-file means the script is running unattended, so retain the safe
  # default and do not turn an optional prompt into an installation failure.
  if ! read -r -p "Do You Want To Configure a Geoapify API key? [n]: " answer; then
    echo "No interactive input available; skipping Geoapify API key configuration."
    return
  fi
  case "${answer:-n}" in
    y|Y|yes|YES|Yes)
      if ! read -r -s -p "Enter Geoapify API key: " api_key; then
        printf '\n'
        echo "Geoapify API key was not read; existing configuration was not changed."
        return
      fi
      printf '\n'
      api_key="${api_key//$'\r'/}"
      api_key="${api_key//$'\n'/}"
      if [[ -z "$api_key" ]]; then
        echo "Geoapify API key was empty; existing configuration was not changed."
        return
      fi

      set_env_value "GEOAPIFY_API_KEY" "$api_key"
      unset api_key
      echo "Geoapify API key saved to the .env file."
      ;;
    *)
      echo "Skipping Geoapify API key configuration."
      ;;
  esac
}

# Reject unsafe service-template substitutions before using administrative
# privileges to install the unit.
if [[ ! "$API_BIND_ADDRESS" =~ ^[A-Za-z0-9.:-]+$ ]]; then
  echo "ERROR: API_BIND_ADDRESS contains unsupported characters." >&2
  exit 1
fi
for number_value in "$API_PORT" "$API_WORKERS"; do
  if [[ ! "$number_value" =~ ^[0-9]+$ ]] || (( number_value < 1 )); then
    echo "ERROR: API_PORT and API_WORKERS must be positive integers." >&2
    exit 1
  fi
done
if (( API_PORT > 65535 )); then
  echo "ERROR: API_PORT must be a valid TCP port." >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: setup_api.sh currently supports Ubuntu/Debian API VMs." >&2
  exit 1
fi
if [[ ! -f "${REPO_ROOT}/requirements.txt" || ! -f "$SERVICE_TEMPLATE" ]]; then
  echo "ERROR: API requirements or systemd service template is missing." >&2
  exit 1
fi

# mysqlclient compiles against the distribution's MySQL/MariaDB development
# headers. No MySQL server is installed on the API VM.
echo "Installing API system dependencies..."
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  curl \
  default-libmysqlclient-dev \
  pkg-config \
  python3 \
  python3-pip \
  python3-venv

# Keep all Python packages inside the checkout's virtual environment.
if [[ ! -d "${REPO_ROOT}/venv" ]]; then
  python3 -m venv "${REPO_ROOT}/venv"
fi
# shellcheck disable=SC1091
source "${REPO_ROOT}/venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${REPO_ROOT}/requirements.txt"

configure_geoapify_key

# Validate imports and Django configuration before replacing the running API.
echo "Checking the Django API configuration..."
cd "$REPO_ROOT"
python manage.py check

# Run Gunicorn as the checkout owner rather than root. PYTHONPATH contains both
# the repository root (api and mq packages) and app/ (backend package).
SERVICE_USER="${SUDO_USER:-$(id -un)}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
temporary_service="$(mktemp)"
trap 'rm -f "$temporary_service"' EXIT
sed \
  -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
  -e "s|__SERVICE_GROUP__|${SERVICE_GROUP}|g" \
  -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
  -e "s/__API_BIND_ADDRESS__/${API_BIND_ADDRESS}/g" \
  -e "s/__API_PORT__/${API_PORT}/g" \
  -e "s/__API_WORKERS__/${API_WORKERS}/g" \
  "$SERVICE_TEMPLATE" > "$temporary_service"

sudo install -m 0644 "$temporary_service" "/etc/systemd/system/${SERVICE_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# Confirm the process responds locally. This endpoint intentionally avoids DB,
# RabbitMQ, and Geoapify calls so it isolates API process startup failures.
api_ready="no"
for _attempt in {1..10}; do
  if curl --fail --silent "http://127.0.0.1:${API_PORT}/api/health" >/dev/null; then
    api_ready="yes"
    break
  fi
  sleep 1
done
if [[ "$api_ready" != "yes" ]]; then
  echo "ERROR: The API service did not pass its local health check." >&2
  echo "Inspect it with: sudo journalctl -u ${SERVICE_NAME} -n 100 --no-pager" >&2
  exit 1
fi

echo "API VM setup complete."
echo "API listener: http://${API_BIND_ADDRESS}:${API_PORT}"
echo "Health check: http://127.0.0.1:${API_PORT}/api/health"
