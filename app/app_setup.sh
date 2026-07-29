#!/usr/bin/env bash
# Install the shared Django application/backend Python runtime.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: app_setup.sh currently supports Ubuntu/Debian App VMs." >&2
  exit 1
fi

echo "Installing App/Django system dependencies..."
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  default-libmysqlclient-dev \
  pkg-config \
  python3 \
  python3-pip \
  python3-venv

# Every role script shares the repository venv so running more than one role
# setup remains idempotent and does not create competing environments.
if [[ ! -d "${REPO_ROOT}/venv" ]]; then
  python3 -m venv "${REPO_ROOT}/venv"
fi
# shellcheck disable=SC1091
source "${REPO_ROOT}/venv/bin/activate"

echo "Installing Django and App backend Python dependencies..."
python -m pip install --upgrade pip
python -m pip install \
  asgiref==3.11.1 \
  bcrypt==5.0.0 \
  certifi==2026.6.17 \
  charset-normalizer==3.4.7 \
  Django==6.0.6 \
  djangorestframework==3.17.1 \
  idna==3.18 \
  mysqlclient==2.2.8 \
  pika==1.4.1 \
  python-dotenv==1.2.2 \
  requests==2.34.2 \
  sqlparse==0.5.5 \
  urllib3==2.7.0

echo "App/Django dependency setup complete."
