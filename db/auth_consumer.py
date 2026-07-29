"""DB-VM RabbitMQ consumer for registration and login commands.

This process is the production authentication boundary: plaintext passwords
exist only for the duration of one request, are hashed/checked with bcrypt, and
are never included in responses, logs, or domain events.
"""

import json
import os
from pathlib import Path

import bcrypt
import MySQLdb
import pika
from dotenv import load_dotenv
from MySQLdb.cursors import DictCursor

from mq.config import (
    AUTH_REQUEST_QUEUE,
    RABBITMQ_BLOCKED_TIMEOUT,
    RABBITMQ_HEARTBEAT,
    RABBITMQ_URL,
)
from mq.rabbitmq import (
    declare_auth_topology,
    publish_auth_error,
    publish_auth_response,
    publish_event_type,
    validate_auth_message,
)

# ---------------------------------------------------------------------------
# Environment configuration
#
# The DB role can keep its credentials in db/.env. The repository-level .env
# remains a fallback for single-VM development. Neither file is committed.
load_dotenv(Path(__file__).with_name(".env"))
load_dotenv()


# ---------------------------------------------------------------------------
# MySQL connection handling
def _database_connection():
    """Open one mysqlclient connection using uncommitted environment secrets."""
    connection = MySQLdb.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "dream_app"),
        passwd=os.getenv("DB_PASSWORD", ""),
        db=os.getenv("DB_NAME", "DreamEscapes"),
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
    # Authentication commands must commit as one unit. Explicit transaction
    # control also ensures failed commands can always be rolled back safely.
    connection.autocommit(False)
    return connection


# ---------------------------------------------------------------------------
# Safe response serialization
def _safe_user(row):
    """Return only user fields permitted in MQ responses and sessions."""
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "account_status": row["account_status"],
        "travel_preferences": row.get("travel_preferences", ""),
    }


# ---------------------------------------------------------------------------
# Registration command
def _register(payload):
    """Validate, hash, and insert one user in a short MySQL transaction."""
    # Normalize only the values the DB boundary is responsible for handling.
    username = str(payload.get("username", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if not username or not email or len(password) < 8:
        return {"success": False, "error": "Invalid registration information."}

    # Hash before opening the DB connection so plaintext password handling is
    # short-lived and no slow bcrypt work holds a database transaction open.
    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    connection = None
    try:
        connection = _database_connection()
        cursor = connection.cursor()
        try:
            # Parameter placeholders keep all user input outside the SQL text.
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES (%s, %s, %s)
                """,
                (username, email, password_hash),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                """
                SELECT user_id, username, email, role, account_status,
                       travel_preferences
                FROM users WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
        connection.commit()
    except MySQLdb.IntegrityError:
        # Duplicate email is an expected conflict, not an internal DB failure.
        if connection is not None:
            connection.rollback()
        return {
            "success": False,
            "error": "An account with that email already exists.",
        }
    except Exception:
        # Any unexpected DB error must leave no partial registration behind.
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()

    return {"success": True, "payload": _safe_user(row)}


# ---------------------------------------------------------------------------
# Login command
def _login(payload):
    """Check one bcrypt password and update the successful login timestamp."""
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    connection = _database_connection()
    try:
        cursor = connection.cursor()
        try:
            # Fetch at most one account because users.email is unique.
            cursor.execute(
                """
                SELECT user_id, username, email, password_hash, role,
                       account_status, travel_preferences
                FROM users WHERE email = %s LIMIT 1
                """,
                (email,),
            )
            row = cursor.fetchone()

            # Always return the same public failure for missing users, invalid
            # hashes/passwords, and disabled accounts.
            password_matches = False
            if row:
                try:
                    password_matches = bcrypt.checkpw(
                        password.encode("utf-8"),
                        row["password_hash"].encode("utf-8"),
                    )
                except ValueError:
                    password_matches = False
            if (
                not row
                or not password_matches
                or row["account_status"] != "enabled"
            ):
                connection.rollback()
                return {"success": False, "error": "Invalid email or password."}

            # Record successful authentication inside the same transaction.
            cursor.execute(
                "UPDATE users SET last_login_at = CURRENT_TIMESTAMP(6) "
                "WHERE user_id = %s",
                (row["user_id"],),
            )
        finally:
            cursor.close()
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return {"success": True, "payload": _safe_user(row)}


# ---------------------------------------------------------------------------
# Auth-command dispatch
def process_auth_message(message):
    """Execute one validated auth command and return a correlated safe response."""
    # MQ envelope validation happens before any payload reaches the database.
    validate_auth_message(message)
    message_type = message["type"]
    if message_type == "auth.register.request":
        result = _register(message["payload"])
    elif message_type == "auth.login.request":
        result = _login(message["payload"])
    else:
        raise ValueError("Unsupported authentication request.")
    result["correlation_id"] = message["correlation_id"]
    return result


# ---------------------------------------------------------------------------
# Secret-free domain/audit events
def _publish_domain_result(message, response):
    """Publish a secret-free audit event for the authentication outcome."""
    payload = response.get("payload") or {}
    fields = {
        "correlation_id": message["correlation_id"],
        "user_id": payload.get("user_id"),
    }
    if message["type"] == "auth.register.request" and response["success"]:
        event_type = "auth.account.created"
        text = "Account created"
    elif message["type"] == "auth.login.request" and response["success"]:
        event_type = "auth.login.success"
        text = "Login succeeded"
    elif message["type"] == "auth.login.request":
        event_type = "auth.login.failure"
        text = "Login failed"
    else:
        return
    try:
        publish_event_type(event_type, source="db", payload={"message": text}, **fields)
    except Exception:
        # The command response must still reach the App when event monitoring is
        # temporarily unavailable.
        pass


# ---------------------------------------------------------------------------
# RabbitMQ consumer lifecycle
def run_consumer():
    """Consume authentication commands with one-at-a-time acknowledgements."""
    # Refuse to start without explicit broker credentials.
    if not RABBITMQ_URL or "REPLACE_WITH" in RABBITMQ_URL:
        raise RuntimeError("Configure RABBITMQ_URL before starting the DB consumer.")

    # Create the long-lived broker connection and ensure all required queues
    # and exchanges exist before consuming commands.
    parameters = pika.URLParameters(RABBITMQ_URL)
    parameters.heartbeat = RABBITMQ_HEARTBEAT
    parameters.blocked_connection_timeout = RABBITMQ_BLOCKED_TIMEOUT
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    declare_auth_topology(channel)
    channel.basic_qos(prefetch_count=1)

    def callback(current_channel, method, properties, body):
        """Process one delivery, acknowledge success, and quarantine failures."""
        message = None
        try:
            # Decode the body and require a private reply queue before any
            # database operation can execute.
            message = json.loads(body.decode("utf-8"))
            reply_to = getattr(properties, "reply_to", None)
            if not isinstance(reply_to, str) or not reply_to.strip():
                raise ValueError("Authentication request requires reply_to")

            # Envelope and payload validation occur inside the dispatcher.
            response = process_auth_message(message)

            # Publish to the private reply queue before acknowledging the
            # command, preventing a successful DB change without a response.
            publish_auth_response(
                current_channel,
                response,
                reply_to=reply_to,
            )
            current_channel.basic_ack(delivery_tag=method.delivery_tag)
            _publish_domain_result(message, response)
        except Exception as error:
            # Invalid or failed commands are reported without plaintext secrets
            # and rejected once so they cannot create an endless poison loop.
            try:
                publish_auth_error(message or "[UNPARSEABLE PAYLOAD]", str(error))
            finally:
                current_channel.basic_nack(
                    delivery_tag=method.delivery_tag,
                    requeue=False,
                )

    channel.basic_consume(
        queue=AUTH_REQUEST_QUEUE,
        on_message_callback=callback,
    )
    print(f"DB auth consumer listening on {AUTH_REQUEST_QUEUE}")
    try:
        # Block until the service is stopped by its process manager.
        channel.start_consuming()
    finally:
        # Close cleanly on shutdown so RabbitMQ can release the consumer.
        if connection.is_open:
            connection.close()


# Start the service only when invoked as a module/script, never during imports.
if __name__ == "__main__":
    run_consumer()
