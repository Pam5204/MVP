"""Validation and redaction for RabbitMQ event messages."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from mq.config import SUPPORTED_EVENT_TYPES


# ---------------------------------------------------------------------------
# Standard event-envelope rules
#
# The event type doubles as the RabbitMQ routing key, so it must remain a
# lowercase dotted name such as bucketlist.destination.saved.
REQUIRED_EVENT_FIELDS = (
    "event_id",
    "event_type",
    "source",
    "timestamp",
    "correlation_id",
    "payload",
)
EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")


def _normalized_key(key: Any) -> str:
    """Normalize a field name so secret checks ignore punctuation and case."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_key(key: Any) -> bool:
    """Return whether a JSON field name identifies secret material."""
    normalized = _normalized_key(key)
    return (
        "password" in normalized
        or "secret" in normalized
        or normalized in {"pwd", "passwd", "authorization", "apikey", "apiaccesskey"}
        or normalized.endswith("token")
        or normalized.endswith("credentials")
    )


def find_sensitive_paths(value: Any, path: str = "$") -> list[str]:
    """Find forbidden keys recursively without exposing their values."""
    matches: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if is_sensitive_key(key):
                matches.append(child_path)
            else:
                matches.extend(find_sensitive_paths(child, child_path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            matches.extend(find_sensitive_paths(child, f"{path}[{index}]"))
    return matches


# ---------------------------------------------------------------------------
# Safe error copies
#
# Structured messages are recursively redacted. Unparseable raw messages are
# represented only by a fingerprint and size so error logs cannot expose data.
def sanitize_sensitive(value: Any) -> Any:
    """Return a JSON-compatible deep copy with secret fields redacted."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(key) else sanitize_sensitive(child)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_sensitive(child) for child in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def sanitize_for_error(value: Any) -> Any:
    """Sanitize structured input or fingerprint an unparseable raw body."""
    if isinstance(value, bytes):
        raw = value
        text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
        raw = value.encode("utf-8", errors="replace")
    else:
        return sanitize_sensitive(value)

    try:
        parsed = json.loads(text)
    except Exception:
        return {
            "unparseable": True,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    return sanitize_sensitive(parsed)


def _validate_timestamp(timestamp: Any) -> None:
    """Require an ISO-8601 timestamp with an explicit UTC/offset timezone."""
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp must be valid ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")


# ---------------------------------------------------------------------------
# Canonical event validation and decoding
def validate_event(event: dict[str, Any]) -> None:
    """Validate the shared JSON event envelope and reject secret fields."""
    if not isinstance(event, dict):
        raise ValueError("Event must be a JSON object")

    missing = [
        field
        for field in REQUIRED_EVENT_FIELDS
        if field not in event or event[field] is None or event[field] == ""
    ]
    if missing:
        raise ValueError(f"Missing required event fields: {', '.join(missing)}")

    # A UUID event ID lets logs and consumers identify one exact event.
    try:
        UUID(str(event["event_id"]))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("event_id must be a UUID") from error

    # Reject malformed or unknown routing keys before they reach the broker.
    event_type = event["event_type"]
    if not isinstance(event_type, str) or not EVENT_TYPE_PATTERN.fullmatch(event_type):
        raise ValueError("event_type must be a lowercase dotted routing key")
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(f"Unsupported event_type: {event_type}")

    # Validate the remaining envelope types and timestamp semantics.
    if not isinstance(event["source"], str) or not event["source"].strip():
        raise ValueError("source must be a non-empty string")
    if not isinstance(event["correlation_id"], str) or not event["correlation_id"].strip():
        raise ValueError("correlation_id must be a non-empty string")
    if not isinstance(event["payload"], dict):
        raise ValueError("payload must be a JSON object")
    _validate_timestamp(event["timestamp"])

    # Scan the entire envelope, including nested payload lists and objects.
    sensitive_paths = find_sensitive_paths(event)
    if sensitive_paths:
        raise ValueError(
            "Sensitive fields are forbidden in events: " + ", ".join(sensitive_paths)
        )

    # Catch unsupported Python objects before json.dumps is used by a publisher.
    try:
        json.dumps(event)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Event must be JSON serializable: {error}") from error


def parse_and_validate_event(body: bytes) -> dict[str, Any]:
    """Decode a queue body and validate the standard event envelope."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid JSON payload: {error}") from error
    validate_event(payload)
    return payload
