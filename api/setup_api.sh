#!/usr/bin/env bash
# Install the Python runtime required by the DreamEscapes API role.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
APP_SETUP_SCRIPT="${REPO_ROOT}/app/app_setup.sh"
ENV_FILE="${REPO_ROOT}/.env"

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

# The API imports app/backend models and services and runs inside the same
# Django project. Reuse its installer so an API VM receives the complete,
# compatible runtime instead of maintaining a second duplicate package list.
if [[ ! -f "$APP_SETUP_SCRIPT" ]]; then
  echo "ERROR: App dependency installer not found at ${APP_SETUP_SCRIPT}." >&2
  exit 1
fi

echo "Installing API and shared backend dependencies..."
bash "$APP_SETUP_SCRIPT"
configure_geoapify_key
echo "API dependency setup complete."
