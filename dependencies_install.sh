#!/bin/bash

# Stop the networking setup immediately if any command fails.
set -e

# This script can install/join ZeroTier first, select exactly which of the four
# VM roles to configure, and write only the secrets required by that role.

ENV_FILE=".env"
DB_ENV_FILE="db/.env"
FRONTEND_CONFIG_FILE="app/frontend/config.js"
MYSQL_CONFIG_FILE="/etc/mysql/mysql.conf.d/mysqld.cnf"
RABBITMQ_ENV_FILE="/etc/rabbitmq/rabbitmq-env.conf"
DEFAULT_RABBITMQ_USER="dream_app"

# Return success when a command exists on this VM.
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Return success when systemd knows about a service unit.
service_exists() {
    command_exists systemctl && systemctl list-unit-files "$1" --no-legend 2>/dev/null | grep -q "$1"
}

# Ask a yes/no question and return success for yes.
ask_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
    local answer

    read -r -p "$prompt [${default}]: " answer
    answer="${answer:-$default}"

    case "$answer" in
        y|Y|yes|YES|Yes)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Print a visible warning without converting an optional connectivity check
# into an installation failure.
warn_yellow() {
    printf '\033[33mWARNING: %s\033[0m\n' "$1"
}

# Ask for a value while showing a default, then echo the chosen value.
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local value

    read -r -p "$prompt [$default]: " value
    echo "${value:-$default}"
}

# Ask for a password without displaying it in the terminal.
prompt_password_with_default() {
    local prompt="$1"
    local default="$2"
    local value

    read -r -s -p "$prompt [default hidden]: " value
    printf '\n' >&2
    value="${value//$'\r'/}"
    value="${value//$'\n'/}"
    echo "${value:-$default}"
}

# Create or update KEY=value in the repo .env file.
set_env_value() {
    local key="$1"
    local value="$2"
    local temp_file

    touch "$ENV_FILE"
    chmod 600 "$ENV_FILE" 2>/dev/null || true

    if grep -q "^${key}=" "$ENV_FILE"; then
        temp_file="$(mktemp)"
        awk -v key="$key" -v value="$value" '
            BEGIN { prefix = key "=" }
            index($0, prefix) == 1 { print prefix value; next }
            { print }
        ' "$ENV_FILE" > "$temp_file"
        chmod 600 "$temp_file" 2>/dev/null || true
        mv "$temp_file" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

# URL-encode values before placing them inside an amqp:// URL.
url_encode() {
    MQ_VALUE="$1" python -c 'import os; from urllib.parse import quote; print(quote(os.environ["MQ_VALUE"].replace("\r", "").replace("\n", ""), safe=""))'
}

# Create and activate a local Python virtual environment when scripts need Python packages.
activate_python_venv() {
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi

    source venv/bin/activate
}

# Install ZeroTier if zerotier-cli is not already available.
install_zerotier_if_missing() {
    if command_exists zerotier-cli; then
        echo "ZeroTier is already installed."
        return
    fi

    echo "Installing ZeroTier..."
    # Install curl when needed because the ZeroTier installer is fetched over HTTPS.
    if ! command_exists curl; then
        sudo apt update
        sudo apt install -y curl
    fi

    # Use ZeroTier's official Linux install script.
    curl -s https://install.zerotier.com | sudo bash
}

# Join the ZeroTier network requested by the operator.
join_zerotier_network() {
    local network_id="$1"

    echo "Starting ZeroTier service..."
    sudo systemctl enable zerotier-one
    sudo systemctl start zerotier-one

    echo "Joining ZeroTier network ${network_id}..."
    sudo zerotier-cli join "$network_id"

    echo "Authorize this VM in the ZeroTier dashboard if it is not already authorized."
}

# Update repo-level environment values used by App/API/DB/MQ Python code.
update_project_env() {
    local mq_ip="$1"
    local rabbitmq_port="$2"
    local rabbitmq_user="$3"
    local rabbitmq_password="$4"
    local encoded_rabbitmq_user
    local encoded_rabbitmq_password
    local rabbitmq_url

    encoded_rabbitmq_user="$(url_encode "$rabbitmq_user")"
    encoded_rabbitmq_password="$(url_encode "$rabbitmq_password")"
    rabbitmq_url="amqp://${encoded_rabbitmq_user}:${encoded_rabbitmq_password}@${mq_ip}:${rabbitmq_port}/"

    echo "Updating ${ENV_FILE} with RabbitMQ/auth settings only..."
    set_env_value "RABBITMQ_URL" "$rabbitmq_url"
    set_env_value "LOG_EXCHANGE" "log.exchange"
    set_env_value "CENTRAL_LOG_QUEUE" "central.log.queue"
    set_env_value "CENTRAL_LOG_FILE" "/var/log/dreamescapes/final_features.jsonl"
    set_env_value "ERROR_EXCHANGE" "error.exchange"
    set_env_value "ERROR_QUEUE" "project.error.queue"
    set_env_value "AUTH_EXCHANGE" "auth.exchange"
    set_env_value "BUCKETLIST_EXCHANGE" "bucketlist.exchange"
    set_env_value "CACHE_EXCHANGE" "cache.exchange"
    set_env_value "ADMIN_EXCHANGE" "admin.exchange"
    set_env_value "AUTH_EVENTS_QUEUE" "auth.events.queue"
    set_env_value "PROFILE_EVENTS_QUEUE" "profile.events.queue"
    set_env_value "BUCKETLIST_EVENTS_QUEUE" "bucketlist.events.queue"
    set_env_value "CACHE_REFRESH_QUEUE" "cache.refresh.queue"
    set_env_value "API_FAILURE_QUEUE" "api.failure.queue"
    set_env_value "ADMIN_AUDIT_QUEUE" "admin.audit.queue"
    set_env_value "AUTH_REQUEST_QUEUE" "auth.request.db.queue"
    set_env_value "AUTH_ERROR_QUEUE" "auth.error.queue"
    set_env_value "AUTH_REGISTER_ROUTING_KEY" "auth.register.request"
    set_env_value "AUTH_LOGIN_ROUTING_KEY" "auth.login.request"

    if ! grep -q "^DJANGO_SECRET_KEY=" "$ENV_FILE"; then
        set_env_value "DJANGO_SECRET_KEY" "$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    fi
}

# Configure MySQL for a checkout running the Django API or DB consumer.
write_database_env_if_requested() {
    local db_host="$1"
    local mysql_port="$2"
    local mq_ip="$3"
    local rabbitmq_port="$4"
    local rabbitmq_user="$5"
    local rabbitmq_password="$6"
    local write_db_role_env="${7:-no}"
    local db_name
    local db_user
    local db_password
    local encoded_rabbitmq_user
    local encoded_rabbitmq_password
    local rabbitmq_url

    if [ ! -d "db" ]; then
        echo "db folder not found; skipping database environment setup."
        return
    fi

    if ! ask_yes_no "Configure this API/DB VM to use the DreamEscapes MySQL database?" "y"; then
        echo "Skipping MySQL environment configuration."
        return
    fi

    db_name="DreamEscapes"
    echo "Using database name: ${db_name}"
    db_user="$(prompt_with_default "Enter application database user" "dream_app")"
    db_password="$(prompt_password_with_default "Enter application database password" "")"
    if [ -z "$db_password" ]; then
        echo "ERROR: Database password cannot be empty."
        exit 1
    fi

    encoded_rabbitmq_user="$(url_encode "$rabbitmq_user")"
    encoded_rabbitmq_password="$(url_encode "$rabbitmq_password")"
    rabbitmq_url="amqp://${encoded_rabbitmq_user}:${encoded_rabbitmq_password}@${mq_ip}:${rabbitmq_port}/"

    set_env_value "DB_HOST" "$db_host"
    set_env_value "DB_PORT" "$mysql_port"
    set_env_value "DB_NAME" "$db_name"
    set_env_value "DB_USER" "$db_user"
    set_env_value "DB_PASSWORD" "$db_password"

    # Only the DB VM needs the second private file consumed by
    # db.auth_consumer. The API VM reads the repository-level .env.
    if [ "$write_db_role_env" = "yes" ]; then
        mkdir -p "$(dirname "$DB_ENV_FILE")"
        cat > "$DB_ENV_FILE" <<EOF
# The DB consumer runs beside MySQL and uses its local socket/account. The API
# VM keeps the DB VM's network address in the repository-level .env above.
DB_HOST=localhost
DB_PORT=${mysql_port}
DB_NAME=${db_name}
DB_USER=${db_user}
DB_PASSWORD=${db_password}

RABBITMQ_URL=${rabbitmq_url}
AUTH_EXCHANGE=auth.exchange
AUTH_REQUEST_QUEUE=auth.request.db.queue
AUTH_ERROR_QUEUE=auth.error.queue
AUTH_REGISTER_ROUTING_KEY=auth.register.request
AUTH_LOGIN_ROUTING_KEY=auth.login.request
EOF

        chmod 600 "$DB_ENV_FILE" 2>/dev/null || true
    fi
    export DB_NAME="$db_name"
    export DB_USER="$db_user"
    export DB_PASSWORD="$db_password"
    if [ "$write_db_role_env" = "yes" ]; then
        echo "Wrote database settings to ${ENV_FILE} and ${DB_ENV_FILE}."
    else
        echo "Wrote API database settings to ${ENV_FILE}."
    fi
}

# Keep the browser API URL on the APP origin. app_setup.sh installs Nginx to
# proxy /api to the separate API VM, which avoids cross-site session cookies.
update_frontend_config_if_present() {
    if [ ! -f "$FRONTEND_CONFIG_FILE" ]; then
        echo "Frontend config not found; skipping same-origin update."
        return
    fi

    echo "Updating frontend to use the APP VM same-origin API proxy..."
    cat > "$FRONTEND_CONFIG_FILE" <<EOF
// Keep browser requests on the APP VM origin. Nginx forwards /api requests to
// the separate API VM without turning its session cookie into a cross-site one.
window.BACKEND_BASE_URL = window.location.origin;
EOF
}

# Run only the role setup scripts selected near the start of this installer.
run_script_if_selected() {
    local label="$1"
    local script_path="$2"
    local selected="$3"

    if [ "$selected" != "yes" ]; then
        echo "Skipping ${label} setup on this VM."
        return
    fi

    if [ ! -f "$script_path" ]; then
        echo "ERROR: ${label} setup script not found at ${script_path}." >&2
        exit 1
    fi

    echo "Running ${script_path}..."
    bash "$script_path"
}

# Allow MySQL to listen on the ZeroTier interface when MySQL is installed here.
update_mysql_if_installed() {
    local db_bind_ip="$1"

    if ! command_exists mysql && ! service_exists mysql.service && ! service_exists mariadb.service; then
        echo "MySQL is not detected on this VM; skipping MySQL bind-address update."
        return
    fi

    if [ ! -f "$MYSQL_CONFIG_FILE" ]; then
        echo "MySQL config ${MYSQL_CONFIG_FILE} not found; skipping MySQL bind-address update."
        return
    fi

    echo "Updating MySQL bind-address to ${db_bind_ip}..."
    sudo cp "$MYSQL_CONFIG_FILE" "${MYSQL_CONFIG_FILE}.bak.$(date +%Y%m%d%H%M%S)"

    if sudo grep -q "^[[:space:]]*bind-address" "$MYSQL_CONFIG_FILE"; then
        sudo sed -i "s|^[[:space:]]*bind-address[[:space:]]*=.*|bind-address = ${db_bind_ip}|" "$MYSQL_CONFIG_FILE"
    else
        echo "bind-address = ${db_bind_ip}" | sudo tee -a "$MYSQL_CONFIG_FILE" >/dev/null
    fi

    echo "Restarting MySQL so the bind-address change takes effect..."
    if service_exists mysql.service; then
        sudo systemctl restart mysql
    elif service_exists mariadb.service; then
        sudo systemctl restart mariadb
    fi
}

# Make RabbitMQ listen on all interfaces when RabbitMQ is installed here.
update_rabbitmq_if_installed() {
    local rabbitmq_user="$1"
    local rabbitmq_password="$2"

    if ! command_exists rabbitmqctl && ! service_exists rabbitmq-server.service; then
        echo "RabbitMQ is not detected on this VM; skipping RabbitMQ listener update."
        return
    fi

    echo "Updating RabbitMQ listener IP to all interfaces..."
    sudo mkdir -p /etc/rabbitmq
    sudo cp "$RABBITMQ_ENV_FILE" "${RABBITMQ_ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true

    # 0.0.0.0 lets other ZeroTier VMs connect to RabbitMQ on this VM.
    if sudo grep -q "^NODE_IP_ADDRESS=" "$RABBITMQ_ENV_FILE" 2>/dev/null; then
        sudo sed -i "s|^NODE_IP_ADDRESS=.*|NODE_IP_ADDRESS=0.0.0.0|" "$RABBITMQ_ENV_FILE"
    else
        echo "NODE_IP_ADDRESS=0.0.0.0" | sudo tee -a "$RABBITMQ_ENV_FILE" >/dev/null
    fi

    echo "Restarting RabbitMQ so listener changes take effect..."
    sudo systemctl restart rabbitmq-server

    echo "Creating or updating RabbitMQ logging user ${rabbitmq_user}..."
    if sudo rabbitmqctl list_users | awk '{print $1}' | grep -qx "$rabbitmq_user"; then
        sudo rabbitmqctl change_password "$rabbitmq_user" "$rabbitmq_password"
    else
        sudo rabbitmqctl add_user "$rabbitmq_user" "$rabbitmq_password"
    fi

    # Give the application user permissions needed to publish, consume, and declare topology.
    sudo rabbitmqctl set_permissions -p / "$rabbitmq_user" ".*" ".*" ".*"
}

# Print which role-related services/files were detected on this VM.
print_detection_summary() {
    echo "Detected local role hints:"

    if command_exists mysql || service_exists mysql.service || service_exists mariadb.service; then
        echo "  - DB role: MySQL/MariaDB detected"
    else
        echo "  - DB role: not detected"
    fi

    if command_exists rabbitmqctl || service_exists rabbitmq-server.service; then
        echo "  - MQ role: RabbitMQ detected"
    else
        echo "  - MQ role: not detected"
    fi

    if [ -f "manage.py" ] && python3 -c "import django" >/dev/null 2>&1; then
        echo "  - API role: Django project detected"
    else
        echo "  - API role: not detected"
    fi

    if [ -f "$FRONTEND_CONFIG_FILE" ]; then
        echo "  - Frontend role: frontend config detected"
    else
        echo "  - Frontend role: not detected"
    fi
}

# Final non-fatal RabbitMQ check. This proves the RABBITMQ_URL written to .env
# can authenticate and reach the broker from the current VM.
test_rabbitmq_url_at_end() {
    if [ ! -f "$ENV_FILE" ]; then
        echo "WARNING: ${ENV_FILE} not found; cannot test RABBITMQ_URL."
        return
    fi

    echo "Testing RabbitMQ URL from ${ENV_FILE}..."
    if python - <<'PY'
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    import pika
except Exception as error:
    print(f"\033[33mWARNING: RabbitMQ URL test skipped because Python dependency is missing: {error}\033[0m")
    raise SystemExit(0)

def warn(message):
    print(f"\033[33m{message}\033[0m")

env_path = Path(".env")
load_dotenv(env_path)
rabbitmq_url = os.getenv("RABBITMQ_URL", "")

if not rabbitmq_url:
    warn("WARNING: RABBITMQ_URL is missing from .env.")
    raise SystemExit(0)

parsed = urlparse(rabbitmq_url)
host = parsed.hostname or "unknown-host"
port = parsed.port or 5672
user = parsed.username or "unknown-user"

try:
    parameters = pika.URLParameters(rabbitmq_url)
    parameters.heartbeat = 10
    parameters.blocked_connection_timeout = 10
    with pika.BlockingConnection(parameters) as connection:
        channel = connection.channel()
        channel.queue_declare(queue="", exclusive=True)
    print(f"RabbitMQ URL check OK: connected to host={host} port={port} user={user}.")
except Exception as error:
    warn(
        "WARNING: RabbitMQ URL check failed. "
        f"Tried host={host} port={port} user={user}. "
        "Check RABBITMQ_URL, RabbitMQ user/password, permissions, port 5672, "
        f"and ZeroTier/firewall connectivity. Error: {error}"
    )
PY
    then
        return 0
    fi

    # Catch unexpected interpreter/configuration failures outside the Python
    # check so `set -e` never terminates the installer for connectivity alone.
    warn_yellow \
        "RabbitMQ connectivity test could not run. Setup will continue; verify RABBITMQ_URL, credentials, port 5672, and firewall access later."
    return 0
}

echo "DreamEscapes dependency and networking setup"

# Phase 1: make sure the VM can reach the other role VMs. On the real
# deployment, these addresses are usually ZeroTier IPs.
# Ask first because ZeroTier networking should be ready before remote services are configured.
if ask_yes_no "Install/join ZeroTier before dependency setup?" "y"; then
    # Ask for the ZeroTier network ID that this VM should join.
    read -r -p "Enter the ZeroTier network ID to join: " ZEROTIER_NETWORK_ID

    if [ -z "$ZEROTIER_NETWORK_ID" ]; then
        echo "ERROR: ZeroTier network ID is required when ZeroTier setup is selected."
        exit 1
    fi

    install_zerotier_if_missing
    join_zerotier_network "$ZEROTIER_NETWORK_ID"
else
    echo "Skipping ZeroTier install/join. Existing networking will be used."
fi

# Ask for the ZeroTier IPs for each role VM.
APP_IP="$(prompt_with_default "Enter APP/frontend VM ZeroTier IP" "localhost")"
API_IP="$(prompt_with_default "Enter API/Django VM ZeroTier IP" "$APP_IP")"
DB_IP="$(prompt_with_default "Enter DB/MySQL VM ZeroTier IP" "localhost")"
MQ_IP="$(prompt_with_default "Enter MQ/RabbitMQ VM ZeroTier IP" "localhost")"

# Ask for distinct APP and API ports. They may both use 8000 because they run
# on different VMs.
APP_PORT="$(prompt_with_default "Enter APP/frontend port" "8000")"
API_PORT="$(prompt_with_default "Enter Django/API port" "8000")"
MYSQL_PORT="$(prompt_with_default "Enter MySQL port" "3306")"
RABBITMQ_PORT="$(prompt_with_default "Enter RabbitMQ AMQP port" "5672")"

# Select this VM's one intended role before requesting or storing role secrets.
# Separate prompts make the same script usable on all four clean VMs.
RUN_APP_ROLE="no"
RUN_API_ROLE="no"
RUN_DB_ROLE="no"
RUN_MQ_ROLE="no"
if ask_yes_no "Configure this VM as the APP/frontend role?" "n"; then
    RUN_APP_ROLE="yes"
fi
if ask_yes_no "Configure this VM as the API/Django role?" "n"; then
    RUN_API_ROLE="yes"
fi
if ask_yes_no "Configure this VM as the DB/MySQL role?" "n"; then
    RUN_DB_ROLE="yes"
fi
if ask_yes_no "Configure this VM as the MQ/RabbitMQ role?" "n"; then
    RUN_MQ_ROLE="yes"
fi

# A four-VM deployment assigns one responsibility to each machine. Refuse an
# empty or combined selection so credentials and services cannot accidentally
# leak into the wrong role VM.
ROLE_COUNT=0
for role_value in "$RUN_APP_ROLE" "$RUN_API_ROLE" "$RUN_DB_ROLE" "$RUN_MQ_ROLE"; do
    if [ "$role_value" = "yes" ]; then
        ROLE_COUNT=$((ROLE_COUNT + 1))
    fi
done
if [ "$ROLE_COUNT" -ne 1 ]; then
    echo "ERROR: Select yes for exactly one of APP, API, DB, or MQ on this VM." >&2
    exit 1
fi

# APP-only VMs never request or store RabbitMQ credentials. API, DB, and MQ
# roles require the same broker account to connect across the trusted network.
RABBITMQ_USER=""
RABBITMQ_PASSWORD=""
if [ "$RUN_API_ROLE" = "yes" ] || [ "$RUN_DB_ROLE" = "yes" ] \
  || [ "$RUN_MQ_ROLE" = "yes" ]; then
    RABBITMQ_USER="$(prompt_with_default "Enter RabbitMQ username" "$DEFAULT_RABBITMQ_USER")"
    RABBITMQ_PASSWORD="$(prompt_password_with_default "Enter RabbitMQ password" "")"
    if [ -z "$RABBITMQ_PASSWORD" ]; then
        echo "ERROR: RabbitMQ password cannot be empty and has no committed default."
        exit 1
    fi
    export MQ_USER="$RABBITMQ_USER"
    export MQ_PASSWORD="$RABBITMQ_PASSWORD"
fi

# Child role scripts use these non-secret network values. The APP setup builds
# its Nginx proxy and the API setup builds its Gunicorn listener from them.
export APP_LISTEN_PORT="$APP_PORT"
export API_HOST="$API_IP"
export API_PORT
export API_BIND_ADDRESS="0.0.0.0"

# MySQL setup grants the API VM and the local DB consumer separately instead
# of exposing the application account from every possible source address.
if [ "$RUN_DB_ROLE" = "yes" ]; then
    export DB_APP_HOST="$API_IP"
    export DB_CONSUMER_HOST="localhost"
fi

# Phase 2: API and DB roles need Python before private URLs and Django settings
# can be written. The MQ setup owns its own Python environment preparation.
if [ "$RUN_API_ROLE" = "yes" ] || [ "$RUN_DB_ROLE" = "yes" ]; then
    # Role scripts install packages into this venv without global pip installs.
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv
    activate_python_venv

    update_project_env "$MQ_IP" "$RABBITMQ_PORT" "$RABBITMQ_USER" "$RABBITMQ_PASSWORD"
    if [ "$RUN_API_ROLE" = "yes" ]; then
        set_env_value "DJANGO_ALLOWED_HOSTS" "${API_IP},localhost,127.0.0.1"
        set_env_value "CORS_ALLOWED_ORIGINS" "http://${APP_IP},http://${APP_IP}:${APP_PORT}"
        set_env_value "CSRF_TRUSTED_ORIGINS" "http://${APP_IP},http://${APP_IP}:${APP_PORT}"
    fi
fi

# Phase 3: configure MySQL on checkouts that run the API backend or DB consumer.
if [ "$RUN_API_ROLE" = "yes" ] || [ "$RUN_DB_ROLE" = "yes" ]; then
    write_database_env_if_requested \
        "$DB_IP" "$MYSQL_PORT" "$MQ_IP" "$RABBITMQ_PORT" \
        "$RABBITMQ_USER" "$RABBITMQ_PASSWORD" "$RUN_DB_ROLE"
fi

# Update frontend runtime config only when frontend files are present. The
# Geoapify key prompt belongs only to api/setup_api.sh on the API VM.
if [ "$RUN_APP_ROLE" = "yes" ]; then
    update_frontend_config_if_present
fi

# Phase 4: run role-specific setup scripts. In a multi-VM deployment, each VM
# normally runs only the setup script for its role.
# Run role-specific setup scripts after ZeroTier is ready and .env has service IPs.
run_script_if_selected "APP frontend/Nginx proxy" "app/app_setup.sh" "$RUN_APP_ROLE"
run_script_if_selected "API/Django service" "api/setup_api.sh" "$RUN_API_ROLE"
run_script_if_selected "RabbitMQ/MQ setup and tests" "mq/setup-test_mq.sh" "$RUN_MQ_ROLE"
run_script_if_selected "MySQL schema and application user" "db/setup_mysql.sh" "$RUN_DB_ROLE"

# Ask what MySQL should bind to only on the selected DB VM.
if [ "$RUN_DB_ROLE" = "yes" ]; then
    MYSQL_BIND_IP="$(prompt_with_default "Enter MySQL bind-address for the DB VM" "$DB_IP")"
fi

print_detection_summary

# Phase 5: if this VM actually hosts MySQL or RabbitMQ, open those services to
# the ZeroTier interface so the other VMs can connect.
# Update service listener configs after optional installs so detection sees new services.
if [ "$RUN_DB_ROLE" = "yes" ]; then
    update_mysql_if_installed "$MYSQL_BIND_IP"
    # MySQL has just changed listeners; reconnect the supervised local auth
    # consumer immediately instead of waiting for its restart backoff.
    if service_exists dreamescapes-db-consumer.service; then
        sudo systemctl restart dreamescapes-db-consumer.service
        if ! sudo systemctl is-active --quiet dreamescapes-db-consumer.service; then
            warn_yellow \
                "DB consumer is installed but not active. Verify db/.env, RabbitMQ connectivity, and MySQL credentials."
        fi
    fi
fi
if [ "$RUN_MQ_ROLE" = "yes" ]; then
    update_rabbitmq_if_installed "$RABBITMQ_USER" "$RABBITMQ_PASSWORD"
fi

echo "ZeroTier network status:"
if command_exists zerotier-cli; then
    sudo zerotier-cli listnetworks
else
    echo "ZeroTier CLI is not installed; skipping network status."
fi

if [ "$RUN_API_ROLE" = "yes" ] || [ "$RUN_DB_ROLE" = "yes" ]; then
    test_rabbitmq_url_at_end
fi

echo "Dependency and networking setup complete."
