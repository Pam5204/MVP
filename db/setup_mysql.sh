#!/usr/bin/env bash
set -euo pipefail

# Install MySQL and the DB-consumer Python runtime, create the database and
# application user, load the schema, and optionally install demo data.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: setup_mysql.sh currently supports Ubuntu/Debian DB VMs." >&2
  exit 1
fi

echo "Installing and starting MySQL..."
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential \
  default-libmysqlclient-dev \
  mysql-server \
  pkg-config \
  python3 \
  python3-pip \
  python3-venv
sudo systemctl enable --now mysql

# Wait briefly for a newly installed server to create its socket and accept
# administrative connections before attempting database setup.
mysql_ready="no"
for _attempt in {1..30}; do
  if [[ -n "${MYSQL_ROOT_PASSWORD:-}" ]]; then
    if mysqladmin --user=root "--password=${MYSQL_ROOT_PASSWORD}" ping --silent \
      >/dev/null 2>&1; then
      mysql_ready="yes"
      break
    fi
  elif sudo mysqladmin ping --silent >/dev/null 2>&1; then
    mysql_ready="yes"
    break
  fi
  sleep 1
done

if [[ "$mysql_ready" != "yes" ]]; then
  echo "ERROR: MySQL did not become ready within 30 seconds." >&2
  exit 1
fi

# Use the repository venv shared by all role setup scripts. In addition to the
# DB consumer packages, Django and DRF provide the migration runner required to
# create framework tables and record the existing application schema.
echo "Preparing the DB consumer Python environment..."
if [[ ! -d "${REPO_ROOT}/venv" ]]; then
  python3 -m venv "${REPO_ROOT}/venv"
fi
# shellcheck disable=SC1091
source "${REPO_ROOT}/venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install \
  bcrypt==5.0.0 \
  Django==6.0.6 \
  djangorestframework==3.17.1 \
  mysqlclient==2.2.8 \
  pika==1.4.1 \
  python-dotenv==1.2.2

DB_NAME="${DB_NAME:-DreamEscapes}"
DB_USER="${DB_USER:-dream_app}"
DB_APP_HOST="${DB_APP_HOST:-%}"
LOAD_SEED_DATA="${LOAD_SEED_DATA:-no}"

if [[ "$DB_NAME" != "DreamEscapes" ]]; then
  echo "DB_NAME must be DreamEscapes to match DreamEscapes.sql." >&2
  exit 1
fi
if [[ ! "$DB_USER" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "DB_USER may contain only letters, numbers, and underscores." >&2
  exit 1
fi
if [[ ! "$DB_APP_HOST" =~ ^[A-Za-z0-9_.:%-]+$ ]]; then
  echo "DB_APP_HOST contains unsupported characters." >&2
  exit 1
fi

if [[ -z "${DB_PASSWORD:-}" ]]; then
  read -r -s -p "Password for MySQL user ${DB_USER}: " DB_PASSWORD
  echo
fi
if [[ -z "$DB_PASSWORD" ]]; then
  echo "DB_PASSWORD is required." >&2
  exit 1
fi

if [[ -n "${MYSQL_ROOT_PASSWORD:-}" ]]; then
  MYSQL_ADMIN=(mysql --user=root "--password=${MYSQL_ROOT_PASSWORD}")
elif command -v sudo >/dev/null 2>&1; then
  MYSQL_ADMIN=(sudo mysql)
else
  MYSQL_ADMIN=(mysql --user=root --password)
fi

escaped_password="${DB_PASSWORD//\'/\'\'}"
"${MYSQL_ADMIN[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'${DB_APP_HOST}'
  IDENTIFIED BY '${escaped_password}';
ALTER USER '${DB_USER}'@'${DB_APP_HOST}'
  IDENTIFIED BY '${escaped_password}';
# The application needs normal row access and permission to call the schema's
# stored procedures. CREATE ROUTINE and ALTER ROUTINE additionally allow the
# repeatable db/test_schema.sql assertions to create and remove their temporary
# test procedure without granting global database-administration privileges.
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, CREATE ROUTINE, ALTER ROUTINE
  ON \`${DB_NAME}\`.* TO '${DB_USER}'@'${DB_APP_HOST}';
FLUSH PRIVILEGES;
SQL

"${MYSQL_ADMIN[@]}" < "${SCRIPT_DIR}/DreamEscapes.sql"

case "${LOAD_SEED_DATA,,}" in
  1|true|yes|y)
    "${MYSQL_ADMIN[@]}" < "${SCRIPT_DIR}/seed_data.sql"
    ;;
esac

# The SQL schema owns the five DreamEscapes application tables. When the App
# runtime is ready, apply Django's framework migrations and fake only the
# matching initial backend migration. This creates Django's
# admin/auth/content-type tables and records the existing application schema,
# preventing runserver from reporting unapplied migrations. --skip-checks
# avoids importing App/API URL handlers that are not needed on a dedicated DB
# VM; the App setup and normal manage.py check still validate those handlers.
DJANGO_PYTHON="${REPO_ROOT}/venv/bin/python"
if [[ -x "$DJANGO_PYTHON" ]] \
  && "$DJANGO_PYTHON" -c "import django, rest_framework" >/dev/null 2>&1; then
  echo "Synchronizing Django migration history with the MySQL schema..."
  if [[ -n "${MYSQL_ROOT_PASSWORD:-}" ]]; then
    env \
      DB_HOST=127.0.0.1 \
      DB_PORT="${DB_PORT:-3306}" \
      DB_NAME="$DB_NAME" \
      DB_USER=root \
      DB_PASSWORD="$MYSQL_ROOT_PASSWORD" \
      "$DJANGO_PYTHON" "${REPO_ROOT}/manage.py" \
      migrate --fake-initial --noinput --skip-checks
  else
    # Ubuntu's default MySQL root account authenticates through the local Unix
    # socket, so execute the migration command as root with host=localhost.
    sudo env \
      DB_HOST=localhost \
      DB_PORT="${DB_PORT:-3306}" \
      DB_NAME="$DB_NAME" \
      DB_USER=root \
      DB_PASSWORD= \
      "$DJANGO_PYTHON" "${REPO_ROOT}/manage.py" \
      migrate --fake-initial --noinput --skip-checks
  fi
else
  echo "ERROR: Django migration dependencies were not installed." >&2
  exit 1
fi

echo "DreamEscapes MySQL setup complete."
echo "Run database assertions with:"
echo "  mysql --user=${DB_USER} --password ${DB_NAME} < ${SCRIPT_DIR}/test_schema.sql"
