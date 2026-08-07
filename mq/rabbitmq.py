"""RabbitMQ topology, publishers, and consumers for DreamEscapes events."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import pika

from mq.config import (
    ADMIN_EXCHANGE,
    AUTH_ERROR_QUEUE,
    AUTH_ERROR_ROUTING_KEY,
    AUTH_EXCHANGE,
    AUTH_REQUEST_QUEUE,
    AUTH_REQUEST_TYPES,
    BAD_MESSAGE_LOG_FILE,
    CENTRAL_LOG_FILE,
    CENTRAL_LOG_QUEUE,
    BUCKETLIST_EXCHANGE,
    CACHE_EXCHANGE,
    ERROR_EXCHANGE,
    ERROR_QUEUE,
    ERROR_ROUTING_KEY,
    EVENT_EXCHANGES,
    EXCHANGE_TYPES,
    QUEUE_BINDINGS,
    RABBITMQ_BLOCKED_TIMEOUT,
    RABBITMQ_HEARTBEAT,
    RABBITMQ_URL,
)
from mq.validation import (
    parse_and_validate_event,
    sanitize_for_error,
    sanitize_sensitive,
    validate_event,
)


# ---------------------------------------------------------------------------
# Shared time and broker connection helpers
#
# All publishers/consumers use the same URL, heartbeat, and blocked timeout so
# behavior stays consistent across the App, API, DB, and MQ VMs.
def utc_timestamp() -> str:
    """Return a compact, timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _connection() -> pika.BlockingConnection:
    """Create a RabbitMQ connection from the uncommitted environment config."""
    if not RABBITMQ_URL:
        raise RuntimeError(
            "RABBITMQ_URL is not configured. Set it in the environment or .env."
        )
    parameters = pika.URLParameters(RABBITMQ_URL)
    parameters.heartbeat = RABBITMQ_HEARTBEAT
    parameters.blocked_connection_timeout = RABBITMQ_BLOCKED_TIMEOUT
    return pika.BlockingConnection(parameters)


def _dead_letter_arguments() -> dict[str, str]:
    """Arguments attached to application queues to quarantine rejected bodies."""
    return {
        "x-dead-letter-exchange": ERROR_EXCHANGE,
        "x-dead-letter-routing-key": ERROR_ROUTING_KEY,
    }


# ---------------------------------------------------------------------------
# Topology declaration
#
# These functions receive a channel so setup commands, consumers, and tests can
# share one idempotent topology implementation.
def declare_exchanges(channel: Any) -> None:
    """Idempotently declare every project and error exchange."""
    for exchange, exchange_type in EXCHANGE_TYPES.items():
        channel.exchange_declare(
            exchange=exchange,
            exchange_type=exchange_type,
            durable=True,
        )


def declare_queues(channel: Any, include_auth_commands: bool = True) -> None:
    """Idempotently declare queues, DLQ settings, and bindings."""
    channel.queue_declare(queue=ERROR_QUEUE, durable=True)
    channel.queue_bind(
        exchange=ERROR_EXCHANGE,
        queue=ERROR_QUEUE,
        routing_key=ERROR_ROUTING_KEY,
    )

    # Canonical queues share the same DLX but retain their domain bindings.
    for queue_name, binding in QUEUE_BINDINGS.items():
        channel.queue_declare(
            queue=queue_name,
            durable=True,
            arguments=_dead_letter_arguments(),
        )
        for routing_key in binding.routing_keys:
            channel.queue_bind(
                exchange=binding.exchange,
                queue=queue_name,
                routing_key=routing_key,
            )

    # Tests or monitoring-only deployments may request only domain queues.
    if not include_auth_commands:
        return

    # Auth commands use a durable DB request queue and error queue. Each App
    # request creates its own exclusive response queue at runtime.
    auth_rpc_arguments = {
        "x-dead-letter-exchange": AUTH_EXCHANGE,
        "x-dead-letter-routing-key": AUTH_ERROR_ROUTING_KEY,
    }
    channel.queue_declare(
        queue=AUTH_REQUEST_QUEUE,
        durable=True,
        arguments=auth_rpc_arguments,
    )
    channel.queue_declare(queue=AUTH_ERROR_QUEUE, durable=True)
    for routing_key in AUTH_REQUEST_TYPES.values():
        channel.queue_bind(
            exchange=AUTH_EXCHANGE,
            queue=AUTH_REQUEST_QUEUE,
            routing_key=routing_key,
        )
    channel.queue_bind(
        exchange=AUTH_EXCHANGE,
        queue=AUTH_ERROR_QUEUE,
        routing_key=AUTH_ERROR_ROUTING_KEY,
    )


def declare_project_topology(channel: Any) -> None:
    """Declare canonical domain topology and private auth command routes."""
    declare_exchanges(channel)
    declare_queues(channel)


def declare_auth_topology(channel: Any) -> None:
    """Declare the complete topology required by authentication commands."""
    declare_project_topology(channel)


# ---------------------------------------------------------------------------
# Standard event construction and routing
def exchange_for_event(event_type: str) -> str:
    """Return the exchange that owns an event routing key."""
    try:
        return EVENT_EXCHANGES[event_type]
    except KeyError as error:
        raise ValueError(f"Unsupported event_type: {event_type}") from error


def build_event(
    event_type: str,
    source: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    **optional_fields: Any,
) -> dict[str, Any]:
    """Build and validate the single shared JSON event envelope."""
    event = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "source": source,
        "timestamp": utc_timestamp(),
        "correlation_id": correlation_id or str(uuid4()),
        "payload": payload,
    }
    event.update(
        {key: value for key, value in optional_fields.items() if value is not None}
    )
    validate_event(event)
    return event


def _event_properties(event: dict[str, Any]) -> pika.BasicProperties:
    """Create persistent AMQP metadata used for tracing and diagnostics."""
    return pika.BasicProperties(
        content_type="application/json",
        content_encoding="utf-8",
        delivery_mode=2,
        message_id=event["event_id"],
        correlation_id=event["correlation_id"],
        timestamp=int(datetime.now(timezone.utc).timestamp()),
        type=event["event_type"],
        app_id=event["source"],
    )


# ---------------------------------------------------------------------------
# Safe rejection/error publication
def _safe_error_reason(reason: Any) -> str:
    """Remove common inline credential forms and cap error detail length."""
    text = str(reason)
    text = re.sub(
        r"(?i)(password|secret|api[_-]?key|token|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)amqps?://[^@\s]+@", "amqp://[REDACTED]@", text)
    return text[:500]


def publish_error_message(
    original_payload: Any,
    reason: Any,
    queue_name: str = "publisher",
) -> dict[str, str]:
    """Publish a sanitized rejection record to the project error queue."""
    correlation_id = None
    if isinstance(original_payload, dict):
        correlation_id = original_payload.get("correlation_id")
    # Error events use their own internal type because they bypass the normal
    # domain event catalog and route directly to error.exchange.
    error_event = {
        "event_id": str(uuid4()),
        "event_type": "mq.message.rejected",
        "source": "rabbitmq",
        "timestamp": utc_timestamp(),
        "correlation_id": str(correlation_id or uuid4()),
        "payload": {
            "reason": _safe_error_reason(reason),
            "queue_name": queue_name,
            "original_payload": sanitize_for_error(original_payload),
        },
    }
    # Declare only the error path here so a validation failure can be recorded
    # even if the rest of the project topology has not been created yet.
    with _connection() as connection:
        channel = connection.channel()
        declare_exchanges(channel)
        channel.queue_declare(queue=ERROR_QUEUE, durable=True)
        channel.queue_bind(
            exchange=ERROR_EXCHANGE,
            queue=ERROR_QUEUE,
            routing_key=ERROR_ROUTING_KEY,
        )
        channel.confirm_delivery()
        published = channel.basic_publish(
            exchange=ERROR_EXCHANGE,
            routing_key=ERROR_ROUTING_KEY,
            body=json.dumps(error_event).encode("utf-8"),
            properties=_event_properties(error_event),
            mandatory=True,
        )
        if published is False:
            raise RuntimeError("RabbitMQ did not confirm the error message")
    return {
        "exchange": ERROR_EXCHANGE,
        "routing_key": ERROR_ROUTING_KEY,
        "event_id": error_event["event_id"],
    }


# ---------------------------------------------------------------------------
# Canonical domain publishers
def publish_event(event: dict[str, Any]) -> dict[str, str]:
    """Validate and persist one event with publisher confirmation enabled."""
    try:
        validate_event(event)
        exchange = exchange_for_event(event["event_type"])
    except ValueError as validation_error:
        # A validation failure is never silent.  If the broker is unavailable,
        # preserve the original validation error rather than masking it.
        try:
            publish_error_message(event, validation_error, "publisher")
        except Exception:
            pass
        raise

    # Publisher confirms plus mandatory routing detect broker rejection and
    # unroutable messages instead of reporting a false success.
    with _connection() as connection:
        channel = connection.channel()
        declare_project_topology(channel)
        channel.confirm_delivery()
        published = channel.basic_publish(
            exchange=exchange,
            routing_key=event["event_type"],
            body=json.dumps(event).encode("utf-8"),
            properties=_event_properties(event),
            mandatory=True,
        )
        if published is False:
            raise RuntimeError(
                f"RabbitMQ did not confirm event {event['event_id']}"
            )
    return {
        "exchange": exchange,
        "routing_key": event["event_type"],
        "event_id": event["event_id"],
        "correlation_id": event["correlation_id"],
    }


def publish_event_type(
    event_type: str,
    source: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    **optional_fields: Any,
) -> dict[str, str]:
    """Convenience producer for backend/API call sites."""
    return publish_event(
        build_event(
            event_type,
            source,
            payload,
            correlation_id=correlation_id,
            **optional_fields,
        )
    )


def _publish_family(
    prefix: str | tuple[str, ...],
    event_type: str,
    source: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    **optional_fields: Any,
) -> dict[str, str]:
    # Family checks stop a convenience function from publishing to the wrong
    # exchange because of a caller typo.
    if not event_type.startswith(prefix):
        raise ValueError(f"Expected an {prefix} event, got {event_type}")
    return publish_event_type(
        event_type,
        source,
        payload,
        correlation_id=correlation_id,
        **optional_fields,
    )


def publish_auth_event(event_type: str, source: str, payload: dict[str, Any], **fields: Any) -> dict[str, str]:
    return _publish_family(("auth.", "profile."), event_type, source, payload, **fields)


def publish_bucketlist_event(event_type: str, source: str, payload: dict[str, Any], **fields: Any) -> dict[str, str]:
    return _publish_family("bucketlist.", event_type, source, payload, **fields)


def publish_cache_event(event_type: str, source: str, payload: dict[str, Any], **fields: Any) -> dict[str, str]:
    if not event_type.startswith(("cache.", "api.")):
        raise ValueError(f"Expected a cache/api event, got {event_type}")
    return publish_event_type(event_type, source, payload, **fields)


def publish_admin_event(event_type: str, source: str, payload: dict[str, Any], **fields: Any) -> dict[str, str]:
    return _publish_family("admin.", event_type, source, payload, **fields)


# ---------------------------------------------------------------------------
# Canonical event consumer
def consume_event_queue(
    queue_name: str,
    handle_event: Callable[[dict[str, Any]], None],
) -> None:
    """Consume validated events; poison messages are quarantined once."""
    if queue_name not in QUEUE_BINDINGS:
        raise ValueError(f"Unknown event queue: {queue_name}")
    connection = _connection()
    channel = connection.channel()
    declare_project_topology(channel)
    channel.basic_qos(prefetch_count=1)

    def callback(channel: Any, method: Any, properties: Any, body: bytes) -> None:
        # Acknowledge only after validation and the application handler finish.
        try:
            event = parse_and_validate_event(body)
            handle_event(event)
        except Exception as error:
            # Prefer a sanitized rejection record. If that route is unavailable,
            # reject once so RabbitMQ's configured DLX handles the original.
            try:
                publish_error_message(
                    body.decode("utf-8", errors="replace"),
                    error,
                    queue_name,
                )
                channel.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                # Requeue=False invokes this queue's DLX and avoids poison loops.
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        channel.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue=queue_name, on_message_callback=callback)
    print(f"Listening for validated events on {queue_name}")
    try:
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()


def append_line(path: str, line: str) -> None:
    """Append exactly one line, creating only the configured parent directory."""
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(line + "\n")


def consume_central_logs() -> None:
    """Persist validated final-feature events as append-only JSON Lines."""

    def write_event(event: dict[str, Any]) -> None:
        append_line(
            CENTRAL_LOG_FILE,
            json.dumps(event, sort_keys=True, separators=(",", ":")),
        )

    print(
        f"Listening on {CENTRAL_LOG_QUEUE}; appending validated events to "
        f"{CENTRAL_LOG_FILE}"
    )
    consume_event_queue(CENTRAL_LOG_QUEUE, write_event)


def consume_bad_messages() -> None:
    """Consume error records without writing the rejected body or secrets."""
    connection = _connection()
    channel = connection.channel()
    declare_project_topology(channel)
    channel.basic_qos(prefetch_count=1)

    def callback(channel: Any, method: Any, properties: Any, body: bytes) -> None:
        received_at = utc_timestamp()
        digest = hashlib.sha256(body).hexdigest()
        append_line(
            BAD_MESSAGE_LOG_FILE,
            f"[{received_at}] BAD_MQ_MESSAGE sha256={digest} bytes={len(body)}",
        )
        channel.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue=ERROR_QUEUE, on_message_callback=callback)
    print(f"Listening on {ERROR_QUEUE}; writing safe metadata to {BAD_MESSAGE_LOG_FILE}")
    try:
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()


# ---------------------------------------------------------------------------
# Private App-to-DB authentication command helpers
#
# Registration/login commands are correlated over RabbitMQ. Audit/domain
# events continue to use the standard validated envelope above.

def _redacted_auth_message(message: dict[str, Any]) -> dict[str, Any]:
    return sanitize_sensitive(message)


def validate_auth_message(message: dict[str, Any]) -> None:
    """Validate the private auth command envelope used by the DB consumer."""
    missing = [
        field
        for field in ("type", "correlation_id", "timestamp")
        if not message.get(field)
    ]
    # An empty object is valid for commands such as logout; only absence is an
    # envelope error.
    if "payload" not in message:
        missing.append("payload")
    if missing:
        raise ValueError(f"Missing auth message fields: {', '.join(missing)}")
    message_type = message["type"]
    if message_type not in AUTH_REQUEST_TYPES:
        raise ValueError(f"Unsupported auth message type: {message_type}")
    payload = message["payload"]
    if not isinstance(payload, dict):
        raise ValueError("Auth payload must be a JSON object")
    if message_type in {"auth.register.request", "auth.login.request"}:
        for field in ("email", "password"):
            if not payload.get(field):
                raise ValueError(f"Missing auth payload field: {field}")


def publish_auth_error(original_payload: Any, reason: str) -> None:
    error_message = {
        "type": "auth.error",
        "received_at": utc_timestamp(),
        "reason": _safe_error_reason(reason),
        "original_payload": _redacted_auth_message(original_payload)
        if isinstance(original_payload, dict)
        else "[UNPARSEABLE PAYLOAD]",
    }
    with _connection() as connection:
        channel = connection.channel()
        declare_auth_topology(channel)
        channel.basic_publish(
            exchange=AUTH_EXCHANGE,
            routing_key=AUTH_ERROR_ROUTING_KEY,
            body=json.dumps(error_message).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json", delivery_mode=2
            ),
        )


def publish_auth_response(
    channel: Any,
    response: dict[str, Any],
    reply_to: str,
) -> None:
    """Publish an auth result only to the requester's private reply queue."""
    if not isinstance(reply_to, str) or not reply_to.strip():
        raise ValueError("Auth responses require a private reply queue")
    channel.basic_publish(
        exchange="",
        routing_key=reply_to,
        body=json.dumps(response, default=str).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
            correlation_id=response.get("correlation_id"),
        ),
    )


def request_auth_response(
    message: dict[str, Any], timeout_seconds: int = 15
) -> dict[str, Any]:
    """Send an auth command and wait on a new private response queue."""
    validate_auth_message(message)
    routing_key = AUTH_REQUEST_TYPES[message["type"]]
    deadline = time.monotonic() + timeout_seconds
    with _connection() as connection:
        channel = connection.channel()
        declare_auth_topology(channel)

        # RabbitMQ generates a unique queue name and deletes the queue when
        # this connection closes, including timeout and exception paths.
        declared_reply_queue = channel.queue_declare(
            queue="",
            exclusive=True,
            auto_delete=True,
        )
        reply_queue = declared_reply_queue.method.queue
        if not reply_queue:
            raise RuntimeError("RabbitMQ did not create a private auth reply queue")

        channel.basic_publish(
            exchange=AUTH_EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(message).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                correlation_id=message["correlation_id"],
                reply_to=reply_queue,
            ),
        )
        while time.monotonic() < deadline:
            method, properties, body = channel.basic_get(
                queue=reply_queue, auto_ack=False
            )
            if method is None:
                time.sleep(0.2)
                continue
            try:
                response = json.loads(body.decode("utf-8"))
            except Exception as error:
                publish_auth_error("[UNPARSEABLE PAYLOAD]", str(error))
                channel.basic_ack(delivery_tag=method.delivery_tag)
                continue
            response_correlation_id = response.get("correlation_id") or getattr(
                properties, "correlation_id", None
            )
            if response_correlation_id == message["correlation_id"]:
                channel.basic_ack(delivery_tag=method.delivery_tag)
                return response
            # Nothing else consumes this exclusive queue. A mismatched result
            # is invalid for this request, so acknowledge it instead of
            # creating another stale-response loop.
            channel.basic_ack(delivery_tag=method.delivery_tag)
    raise TimeoutError(
        f"Timed out waiting for auth response {message['correlation_id']}"
    )
