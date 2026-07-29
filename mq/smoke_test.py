"""Broker-backed smoke tests used by mq/setup-test_mq.sh.

The tests use temporary observer queues to verify delivery without consuming
messages from the application's canonical queues.
"""

from __future__ import annotations

import argparse
import json
import time
from uuid import uuid4

import pika

from mq.config import (
    ADMIN_AUDIT_QUEUE,
    API_FAILURE_QUEUE,
    AUTH_EVENTS_QUEUE,
    BUCKETLIST_EVENTS_QUEUE,
    CACHE_REFRESH_QUEUE,
    ERROR_EXCHANGE,
    ERROR_QUEUE,
    ERROR_ROUTING_KEY,
    PROFILE_EVENTS_QUEUE,
)
from mq.rabbitmq import (
    _connection,
    build_event,
    declare_project_topology,
    exchange_for_event,
    publish_event,
)
from mq.validation import parse_and_validate_event


# Safe representative events covering every required MQ feature family.
SMOKE_EVENTS = (
    ("auth.account.created", {"message": "Account created"}, {"user_id": 101}),
    ("profile.updated", {"message": "Profile updated"}, {"user_id": 101}),
    (
        "bucketlist.destination.saved",
        {"message": "Destination saved"},
        {"user_id": 101, "place_id": "demo-place", "bucket_item_id": 501},
    ),
    (
        "bucketlist.destination.deleted",
        {"message": "Destination deleted"},
        {"user_id": 101, "place_id": "demo-place", "bucket_item_id": 501},
    ),
    (
        "cache.refresh.requested",
        {"message": "Cache refresh requested"},
        {"place_id": "demo-place"},
    ),
    (
        "api.failure",
        {"message": "Synthetic upstream failure for MQ smoke test"},
        {"place_id": "demo-place", "status": "failed", "error_code": "SMOKE"},
    ),
    (
        "admin.audit.created",
        {"message": "Synthetic audit event for MQ smoke test"},
        {"admin_user_id": 1, "target_id": 101, "status": "recorded"},
    ),
)

# The canonical queue whose message count must increase for each smoke event.
EXPECTED_QUEUE = {
    "auth.account.created": AUTH_EVENTS_QUEUE,
    "profile.updated": PROFILE_EVENTS_QUEUE,
    "bucketlist.destination.saved": BUCKETLIST_EVENTS_QUEUE,
    "bucketlist.destination.deleted": BUCKETLIST_EVENTS_QUEUE,
    "cache.refresh.requested": CACHE_REFRESH_QUEUE,
    "api.failure": API_FAILURE_QUEUE,
    "admin.audit.created": ADMIN_AUDIT_QUEUE,
}


def _get_with_timeout(channel, queue_name: str, seconds: float = 5.0):
    """Poll a queue briefly and return one unacknowledged delivery."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        method, properties, body = channel.basic_get(queue=queue_name, auto_ack=False)
        if method is not None:
            return method, properties, body
        time.sleep(0.1)
    raise TimeoutError(f"No message arrived on temporary queue {queue_name}")


def test_publish_events() -> None:
    """Publish, observe, validate, and confirm all representative events."""
    correlation_id = f"mq-smoke-{uuid4()}"
    with _connection() as monitor_connection:
        channel = monitor_connection.channel()
        declare_project_topology(channel)
        for event_type, payload, optional_fields in SMOKE_EVENTS:
            canonical_queue = EXPECTED_QUEUE[event_type]
            before_count = channel.queue_declare(
                queue=canonical_queue, passive=True, durable=True
            ).method.message_count
            # The exclusive observer proves routing without removing the copy
            # retained by the real application queue.
            temporary_queue = channel.queue_declare(
                queue="", exclusive=True, auto_delete=True
            ).method.queue
            channel.queue_bind(
                exchange=exchange_for_event(event_type),
                queue=temporary_queue,
                routing_key=event_type,
            )
            event = build_event(
                event_type,
                "mq-smoke-test",
                payload,
                correlation_id=correlation_id,
                **optional_fields,
            )
            publish_event(event)
            method, _properties, body = _get_with_timeout(channel, temporary_queue)
            received = parse_and_validate_event(body)
            if received["event_id"] != event["event_id"]:
                raise AssertionError(f"Received the wrong {event_type} event")
            channel.basic_ack(delivery_tag=method.delivery_tag)
            channel.queue_delete(queue=temporary_queue)
            # The canonical count check proves its configured binding worked.
            after_count = channel.queue_declare(
                queue=canonical_queue, passive=True, durable=True
            ).method.message_count
            if after_count < before_count + 1:
                raise AssertionError(
                    f"{canonical_queue} did not retain the {event_type} smoke event"
                )
            print(
                f"PASS {event_type} -> {exchange_for_event(event_type)} "
                f"-> {canonical_queue}"
            )
    print(f"Published and consumed {len(SMOKE_EVENTS)} safe smoke-test events.")


def test_bad_message() -> None:
    """Reject one malformed body and prove it reaches the error route once."""
    malformed = json.dumps(
        {"event_type": "bucketlist.destination.saved", "payload": "not-an-object"}
    ).encode("utf-8")
    with _connection() as connection:
        channel = connection.channel()
        declare_project_topology(channel)
        before_error_count = channel.queue_declare(
            queue=ERROR_QUEUE, passive=True, durable=True
        ).method.message_count

        # Observe error.exchange independently while the canonical error queue
        # keeps its own copy as deployment evidence.
        observer_queue = channel.queue_declare(
            queue="", exclusive=True, auto_delete=True
        ).method.queue
        channel.queue_bind(
            exchange=ERROR_EXCHANGE,
            queue=observer_queue,
            routing_key=ERROR_ROUTING_KEY,
        )
        # This temporary source queue uses the same DLX configuration as the
        # project queues, letting the test reject without risking real traffic.
        source_queue = channel.queue_declare(
            queue="",
            exclusive=True,
            auto_delete=True,
            arguments={
                "x-dead-letter-exchange": ERROR_EXCHANGE,
                "x-dead-letter-routing-key": ERROR_ROUTING_KEY,
            },
        ).method.queue
        channel.basic_publish(
            exchange="",
            routing_key=source_queue,
            body=malformed,
            properties=pika.BasicProperties(delivery_mode=2),
        )
        method, _properties, body = _get_with_timeout(channel, source_queue)
        if body != malformed:
            raise AssertionError("Source queue returned an unexpected body")
        # requeue=False is the key poison-message loop prevention behavior.
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        dlq_method, _dlq_properties, dlq_body = _get_with_timeout(
            channel, observer_queue
        )
        if dlq_body != malformed:
            raise AssertionError("Dead-letter exchange returned an unexpected body")
        channel.basic_ack(delivery_tag=dlq_method.delivery_tag)
        after_error_count = channel.queue_declare(
            queue=ERROR_QUEUE, passive=True, durable=True
        ).method.message_count
        if after_error_count < before_error_count + 1:
            raise AssertionError(f"{ERROR_QUEUE} did not receive the malformed message")
        print("PASS malformed event was rejected once and reached error.exchange")
        print("PASS requeue=False prevents an endless poison-message loop")


def main() -> None:
    """Select the publish or bad-message broker test from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("publish", "bad"))
    args = parser.parse_args()
    if args.mode == "publish":
        test_publish_events()
    else:
        test_bad_message()


if __name__ == "__main__":
    main()
