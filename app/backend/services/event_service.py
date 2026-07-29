"""Best-effort publication of safe domain events through RabbitMQ."""

from mq.config import RABBITMQ_URL
from mq.rabbitmq import build_event, publish_event


def broker_is_configured():
    """Return whether the configured broker URL looks deployable."""
    return bool(
        RABBITMQ_URL
        and "REPLACE_WITH" not in RABBITMQ_URL
        and "replace-outside-git" not in RABBITMQ_URL
    )


def emit_event(event_type, payload, *, correlation_id=None, source="app", **fields):
    """Validate an event and publish it when a real broker is configured.

    Domain work remains available during local development or a short broker
    outage. The returned metadata makes the publication status observable.
    """
    event = build_event(
        event_type,
        source=source,
        payload=payload,
        correlation_id=correlation_id,
        **fields,
    )
    if not broker_is_configured():
        return {"published": False, "reason": "broker_not_configured", "event": event}
    try:
        result = publish_event(event)
    except Exception as error:
        return {
            "published": False,
            "reason": "broker_unavailable",
            "error": str(error),
            "event": event,
        }
    return {"published": True, "event": event, "rabbitmq": result}
