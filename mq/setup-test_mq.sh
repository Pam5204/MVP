#!/usr/bin/env bash
# Complete RabbitMQ VM installer, topology creator, and optional smoke tester.
set -euo pipefail

# Resolve the repository root so the script works from any current directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ask_yes_no() {
    # Read a reusable yes/no choice. Enter and non-interactive calls default Y.
    local prompt="$1"
    local answer=""

    if [ -t 0 ]; then
        read -r -p "${prompt} [Y/n]: " answer || answer=""
    fi

    # Pressing Enter, or running non-interactively without an override, means Y.
    answer="${answer:-Y}"
    case "$answer" in
        y|Y|yes|YES|Yes)
            return 0
            ;;
        n|N|no|NO|No)
            return 1
            ;;
        *)
            echo "Please answer yes or no." >&2
            ask_yes_no "$prompt"
            ;;
    esac
}

warn_yellow() {
    # Optional smoke-test failures must remain visible but non-fatal.
    printf '\033[33mWARNING: %s\033[0m\n' "$1"
}

should_run_test() {
    # An environment override supports automation; otherwise ask interactively.
    local variable_name="$1"
    local prompt="$2"
    local configured_value="${!variable_name:-}"

    if [ -n "$configured_value" ]; then
        case "$configured_value" in
            y|Y|yes|YES|Yes|1|true|TRUE|True)
                return 0
                ;;
            n|N|no|NO|No|0|false|FALSE|False)
                return 1
                ;;
            *)
                echo "ERROR: ${variable_name} must be yes/no, true/false, or 1/0." >&2
                exit 1
                ;;
        esac
    fi

    ask_yes_no "$prompt"
}

# ---------------------------------------------------------------------------
# 1. Platform check and RabbitMQ installation
if ! command -v apt-get >/dev/null 2>&1; then
    echo "ERROR: setup-test_mq.sh currently supports Ubuntu/Debian MQ VMs." >&2
    exit 1
fi

echo "Installing and starting RabbitMQ..."
sudo apt-get update
sudo apt-get install -y rabbitmq-server python3 python3-pip python3-venv
sudo systemctl enable --now rabbitmq-server

MQ_VHOST="${MQ_VHOST:-/}"
MQ_BIND_ADDRESS="${MQ_BIND_ADDRESS:-0.0.0.0}"
MQ_PORT="${MQ_PORT:-5672}"

# ---------------------------------------------------------------------------
# 2. Application credentials
#
# Credentials have no committed default. Interactive passwords are hidden;
# automated runs must supply MQ_USER and MQ_PASSWORD in the environment.
if [ -z "${MQ_USER:-}" ]; then
    if [ -t 0 ]; then
        read -r -p "RabbitMQ application username: " MQ_USER
    else
        echo "ERROR: set MQ_USER for non-interactive setup." >&2
        exit 1
    fi
fi

if [ -z "${MQ_PASSWORD:-}" ]; then
    if [ -t 0 ]; then
        read -r -s -p "RabbitMQ application password: " MQ_PASSWORD
        echo
    else
        echo "ERROR: set MQ_PASSWORD for non-interactive setup." >&2
        exit 1
    fi
fi

if [ -z "$MQ_USER" ] || [ -z "$MQ_PASSWORD" ]; then
    echo "ERROR: RabbitMQ username and password cannot be empty." >&2
    exit 1
fi

echo "Creating the RabbitMQ vhost, application user, and permissions..."
# ---------------------------------------------------------------------------
# 3. Vhost, user, and least-privilege vhost permissions
if ! sudo rabbitmqctl list_vhosts | grep -Fxq "$MQ_VHOST"; then
    sudo rabbitmqctl add_vhost "$MQ_VHOST"
fi

if sudo rabbitmqctl list_users | awk '{print $1}' | grep -Fxq "$MQ_USER"; then
    sudo rabbitmqctl change_password "$MQ_USER" "$MQ_PASSWORD"
else
    sudo rabbitmqctl add_user "$MQ_USER" "$MQ_PASSWORD"
fi

# Least privilege for the selected vhost; no administrator tag is granted.
sudo rabbitmqctl set_permissions -p "$MQ_VHOST" "$MQ_USER" ".*" ".*" ".*"

# ---------------------------------------------------------------------------
# 4. Broker network listener
#
# Bind to the requested MQ/ZeroTier address. Restrict port 5672 at the firewall
# to trusted application, API, and DB VM addresses.
sudo install -d -m 0755 /etc/rabbitmq
sudo touch /etc/rabbitmq/rabbitmq-env.conf
if sudo grep -q '^NODE_IP_ADDRESS=' /etc/rabbitmq/rabbitmq-env.conf; then
    sudo sed -i "s/^NODE_IP_ADDRESS=.*/NODE_IP_ADDRESS=${MQ_BIND_ADDRESS}/" /etc/rabbitmq/rabbitmq-env.conf
else
    echo "NODE_IP_ADDRESS=${MQ_BIND_ADDRESS}" | sudo tee -a /etc/rabbitmq/rabbitmq-env.conf >/dev/null
fi
if sudo grep -q '^NODE_PORT=' /etc/rabbitmq/rabbitmq-env.conf; then
    sudo sed -i "s/^NODE_PORT=.*/NODE_PORT=${MQ_PORT}/" /etc/rabbitmq/rabbitmq-env.conf
else
    echo "NODE_PORT=${MQ_PORT}" | sudo tee -a /etc/rabbitmq/rabbitmq-env.conf >/dev/null
fi
sudo systemctl restart rabbitmq-server

# ---------------------------------------------------------------------------
# 5. Python environment used by topology and test modules
echo "Preparing the Python environment..."
if [ ! -d "$REPO_ROOT/venv" ]; then
    python3 -m venv "$REPO_ROOT/venv"
fi
# shellcheck disable=SC1091
source "$REPO_ROOT/venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install pika==1.4.1 python-dotenv==1.2.2

# Build a URL for this script's local broker connection without printing the
# password. Service VMs still need their own private RABBITMQ_URL configuration.
ENCODED_USER="$(MQ_VALUE="$MQ_USER" python -c 'import os; from urllib.parse import quote; print(quote(os.environ["MQ_VALUE"], safe=""))')"
ENCODED_PASSWORD="$(MQ_VALUE="$MQ_PASSWORD" python -c 'import os; from urllib.parse import quote; print(quote(os.environ["MQ_VALUE"], safe=""))')"
if [ "$MQ_VHOST" = "/" ]; then
    VHOST_PATH="/"
else
    ENCODED_VHOST="$(MQ_VALUE="$MQ_VHOST" python -c 'import os; from urllib.parse import quote; print(quote(os.environ["MQ_VALUE"].lstrip("/"), safe=""))')"
    VHOST_PATH="/${ENCODED_VHOST}"
fi
export RABBITMQ_URL="amqp://${ENCODED_USER}:${ENCODED_PASSWORD}@127.0.0.1:${MQ_PORT}${VHOST_PATH}"

# ---------------------------------------------------------------------------
# 6. Remove the retired shared auth response queue during upgrades
#
# Current authentication responses use request-specific exclusive queues. A
# durable queue created by an older checkout survives normal redeclarations,
# so remove that exact unused queue before creating the MVP topology.
RETIRED_AUTH_RESPONSE_QUEUE="auth.response.app.queue"
if sudo rabbitmqctl list_queues -p "$MQ_VHOST" name --no-table-headers \
    | grep -Fxq "$RETIRED_AUTH_RESPONSE_QUEUE"; then
    echo "Removing retired RabbitMQ queue: ${RETIRED_AUTH_RESPONSE_QUEUE}"
    sudo rabbitmqctl delete_queue -p "$MQ_VHOST" \
        "$RETIRED_AUTH_RESPONSE_QUEUE"
fi
unset RETIRED_AUTH_RESPONSE_QUEUE

# ---------------------------------------------------------------------------
# 7. Durable exchanges, queues, bindings, and dead-letter configuration
echo "Creating exchanges, queues, bindings, and dead-letter topology..."
python -m mq.setup_topology

# ---------------------------------------------------------------------------
# 8. Optional smoke tests
#
# Each test is selected independently and defaults to yes.
if should_run_test RUN_PUBLISH_EVENT_TEST "Run the publish-event test?"; then
    echo "Running the publish-event test..."
    if ! python -m mq.smoke_test publish; then
        warn_yellow \
            "Publish-event test could not connect to RabbitMQ or did not complete. Setup will continue; verify the broker address, credentials, permissions, port 5672, and firewall access."
    fi
else
    echo "Skipping the publish-event test."
fi

if should_run_test RUN_BAD_MESSAGE_TEST "Run the bad-message/DLQ test?"; then
    echo "Running the bad-message/DLQ test..."
    if ! python -m mq.smoke_test bad; then
        warn_yellow \
            "Bad-message/DLQ test could not connect to RabbitMQ or did not complete. Setup will continue; verify the broker address, credentials, permissions, port 5672, and firewall access."
    fi
else
    echo "Skipping the bad-message/DLQ test."
fi

# ---------------------------------------------------------------------------
# 9. Safe completion summary (never echo the broker password or full URL)
echo "RabbitMQ setup is complete."
echo "Store RABBITMQ_URL only in each service VM's environment or uncommitted .env file."
echo "Set its host to the MQ VM's trusted network address; the password was not printed."
