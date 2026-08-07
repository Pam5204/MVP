"""Offline unit tests for MQ contracts, topology, and failure handling."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mq.config import (
    ADMIN_EXCHANGE,
    AUTH_EXCHANGE,
    BUCKETLIST_EXCHANGE,
    CACHE_EXCHANGE,
    CENTRAL_LOG_QUEUE,
    ERROR_EXCHANGE,
    ERROR_QUEUE,
    ERROR_ROUTING_KEY,
    EVENT_EXCHANGES,
    EXCHANGE_TYPES,
    LOG_EXCHANGE,
    QUEUE_BINDINGS,
    SUPPORTED_EVENT_TYPES,
)
from mq.rabbitmq import (
    build_event,
    consume_central_logs,
    consume_event_queue,
    declare_project_topology,
    exchange_for_event,
    publish_auth_response,
    publish_event,
    request_auth_response,
    validate_auth_message,
)
from mq.validation import sanitize_for_error, sanitize_sensitive, validate_event


# Explicit acceptance list copied from the Pyu2 RabbitMQ checklist. The test
# prevents an accidental removal or spelling change from passing unnoticed.
REQUIRED_TODO_EVENTS = {
    "auth.account.created",
    "auth.login.success",
    "auth.login.failure",
    "profile.updated",
    "bucketlist.destination.saved",
    "bucketlist.destination.updated",
    "bucketlist.destination.deleted",
    "cache.refresh.requested",
    "api.failure",
    "admin.user.role_changed",
    "admin.user.status_changed",
    "admin.audit.created",
    "review.submitted",
    "community.post.created",
    "community.post.updated",
    "community.post.deleted",
    "community.post.moderated",
}


class EventContractTests(unittest.TestCase):
    """Verify envelope generation, timestamp rules, and secret protection."""
    def test_todo_routing_keys_are_supported(self):
        self.assertTrue(REQUIRED_TODO_EVENTS.issubset(SUPPORTED_EVENT_TYPES))

    def test_build_event_creates_required_standard_envelope(self):
        event = build_event(
            "profile.updated",
            "app",
            {"message": "Profile updated"},
            correlation_id="request-123",
            user_id=7,
        )
        self.assertEqual(
            {
                "event_id",
                "event_type",
                "source",
                "timestamp",
                "correlation_id",
                "payload",
            },
            set(event).intersection(
                {
                    "event_id",
                    "event_type",
                    "source",
                    "timestamp",
                    "correlation_id",
                    "payload",
                }
            ),
        )
        self.assertEqual("request-123", event["correlation_id"])
        self.assertEqual(7, event["user_id"])

    def test_sensitive_fields_are_rejected_at_any_depth(self):
        forbidden_keys = (
            "password",
            "password_hash",
            "api_key",
            "client_secret",
            "access_token",
            "database_credentials",
        )
        for key in forbidden_keys:
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "Sensitive fields"):
                    build_event(
                        "auth.login.failure",
                        "app",
                        {"details": [{key: "must-not-publish"}]},
                    )

    def test_sensitive_fields_are_redacted_from_error_copies(self):
        sanitized = sanitize_sensitive(
            {
                "email": "traveler@example.test",
                "nested": {"password_hash": "must-not-log"},
                "items": [{"api_key": "must-not-log"}],
            }
        )
        self.assertEqual("[REDACTED]", sanitized["nested"]["password_hash"])
        self.assertEqual("[REDACTED]", sanitized["items"][0]["api_key"])
        self.assertNotIn("must-not-log", json.dumps(sanitized))

        raw_json = sanitize_for_error('{"password": "must-not-log"}')
        self.assertEqual("[REDACTED]", raw_json["password"])
        self.assertNotIn("must-not-log", json.dumps(raw_json))

        unparseable = sanitize_for_error("not-json must-not-log")
        self.assertTrue(unparseable["unparseable"])
        self.assertNotIn("must-not-log", json.dumps(unparseable))

    def test_invalid_timestamp_is_rejected(self):
        event = build_event("auth.logout", "app", {"message": "Logged out"})
        event["timestamp"] = "2026-07-19 12:00:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            validate_event(event)


class TopologyTests(unittest.TestCase):
    """Verify every event maps to a declared exchange/queue binding."""
    def test_every_supported_event_has_an_exchange(self):
        self.assertEqual(SUPPORTED_EVENT_TYPES, frozenset(EVENT_EXCHANGES))
        for event_type in SUPPORTED_EVENT_TYPES:
            self.assertIn(exchange_for_event(event_type), EXCHANGE_TYPES)

    def test_event_families_use_the_expected_exchange(self):
        self.assertEqual(AUTH_EXCHANGE, exchange_for_event("auth.account.created"))
        self.assertEqual(AUTH_EXCHANGE, exchange_for_event("profile.updated"))
        self.assertEqual(
            BUCKETLIST_EXCHANGE,
            exchange_for_event("bucketlist.destination.saved"),
        )
        self.assertEqual(CACHE_EXCHANGE, exchange_for_event("api.failure"))
        self.assertEqual(ADMIN_EXCHANGE, exchange_for_event("admin.audit.created"))
        self.assertEqual(LOG_EXCHANGE, exchange_for_event("review.submitted"))
        self.assertEqual(LOG_EXCHANGE, exchange_for_event("community.post.created"))
        self.assertEqual(LOG_EXCHANGE, QUEUE_BINDINGS[CENTRAL_LOG_QUEUE].exchange)

    def test_topology_declares_canonical_queues_with_dlq_and_bindings(self):
        channel = MagicMock()
        declare_project_topology(channel)

        declared_exchanges = {
            call.kwargs["exchange"] for call in channel.exchange_declare.call_args_list
        }
        self.assertEqual(set(EXCHANGE_TYPES), declared_exchanges)

        declared_queues = {
            call.kwargs["queue"]: call.kwargs
            for call in channel.queue_declare.call_args_list
        }
        self.assertIn(ERROR_QUEUE, declared_queues)
        for queue_name in QUEUE_BINDINGS:
            self.assertIn(queue_name, declared_queues)
            self.assertEqual(
                ERROR_EXCHANGE,
                declared_queues[queue_name]["arguments"]["x-dead-letter-exchange"],
            )
            self.assertEqual(
                ERROR_ROUTING_KEY,
                declared_queues[queue_name]["arguments"][
                    "x-dead-letter-routing-key"
                ],
            )

        actual_bindings = {
            (
                call.kwargs["exchange"],
                call.kwargs["queue"],
                call.kwargs["routing_key"],
            )
            for call in channel.queue_bind.call_args_list
        }
        for queue_name, binding in QUEUE_BINDINGS.items():
            for routing_key in binding.routing_keys:
                self.assertIn(
                    (binding.exchange, queue_name, routing_key), actual_bindings
                )


class PublisherConsumerTests(unittest.TestCase):
    """Verify AMQP publish guarantees and poison-message behavior offline."""
    @patch("mq.rabbitmq._connection")
    def test_publish_uses_persistent_message_and_confirmation(self, connection_factory):
        # A mocked broker proves the publisher contract without network access.
        connection = MagicMock()
        channel = MagicMock()
        connection.__enter__.return_value = connection
        connection.channel.return_value = channel
        channel.basic_publish.return_value = True
        connection_factory.return_value = connection

        event = build_event(
            "bucketlist.destination.saved",
            "api",
            {"message": "Destination saved"},
            user_id=5,
            place_id="place-1",
            bucket_item_id=8,
        )
        result = publish_event(event)

        channel.confirm_delivery.assert_called_once_with()
        published = channel.basic_publish.call_args.kwargs
        self.assertTrue(published["mandatory"])
        self.assertEqual(2, published["properties"].delivery_mode)
        self.assertEqual(event["event_id"], published["properties"].message_id)
        self.assertEqual(event["event_id"], result["event_id"])

    @patch("mq.rabbitmq.publish_error_message")
    @patch("mq.rabbitmq._connection")
    def test_consumer_quarantines_bad_message_without_requeue(
        self, connection_factory, publish_error
    ):
        connection = MagicMock()
        channel = MagicMock()
        connection.channel.return_value = channel
        connection.is_open = True
        connection_factory.return_value = connection
        publish_error.side_effect = RuntimeError("broker error route unavailable")

        # Capture the registered callback, feed it malformed JSON, and confirm
        # the fallback rejection does not requeue forever.
        consume_event_queue(next(iter(QUEUE_BINDINGS)), MagicMock())
        callback = channel.basic_consume.call_args.kwargs["on_message_callback"]
        method = MagicMock(delivery_tag=44)
        callback(channel, method, MagicMock(), b"not-json")

        channel.basic_nack.assert_called_once_with(delivery_tag=44, requeue=False)
        channel.basic_ack.assert_not_called()

    @patch("mq.rabbitmq.consume_event_queue")
    def test_central_logger_appends_validated_jsonl_with_correlation_id(self, consume):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_file = Path(temporary_directory) / "final_features.jsonl"
            event = build_event(
                "review.submitted",
                "api",
                {"message": "Destination review submitted"},
                correlation_id="evidence-review-1",
                review_id=7,
            )
            with patch("mq.rabbitmq.CENTRAL_LOG_FILE", str(log_file)):
                consume_central_logs()
                handler = consume.call_args.args[1]
                handler(event)

            written = json.loads(log_file.read_text(encoding="utf-8"))
            self.assertEqual(written["event_id"], event["event_id"])
            self.assertEqual(written["correlation_id"], "evidence-review-1")
            self.assertEqual(written["event_type"], "review.submitted")


class AuthResponseTests(unittest.TestCase):
    """Verify authentication uses only private request-specific replies."""

    def test_non_auth_command_is_rejected(self):
        message = {
            "type": "unsupported.auth.request",
            "correlation_id": "current-request",
            "timestamp": "2026-07-29T12:00:00Z",
            "payload": {},
        }

        with self.assertRaisesRegex(ValueError, "Unsupported auth message"):
            validate_auth_message(message)

    @patch("mq.rabbitmq.time.sleep")
    @patch("mq.rabbitmq._connection")
    def test_request_uses_a_new_exclusive_reply_queue(
        self, connection_factory, _sleep
    ):
        connection = MagicMock()
        channel = MagicMock()
        connection.__enter__.return_value = connection
        connection.channel.return_value = channel
        connection_factory.return_value = connection
        channel.queue_declare.return_value.method.queue = "amq.gen-private-response"

        message = {
            "type": "auth.login.request",
            "correlation_id": "current-request",
            "timestamp": "2026-07-29T12:00:00Z",
            "payload": {
                "email": "traveler@example.test",
                "password": "test-password",
            },
        }
        response = {
            "success": True,
            "correlation_id": "current-request",
            "payload": {},
        }
        method = MagicMock(delivery_tag=71)
        properties = MagicMock(correlation_id="current-request")
        channel.basic_get.return_value = (
            method,
            properties,
            json.dumps(response).encode("utf-8"),
        )

        result = request_auth_response(message, timeout_seconds=1)

        self.assertEqual(response, result)
        channel.queue_declare.assert_any_call(
            queue="",
            exclusive=True,
            auto_delete=True,
        )
        published = channel.basic_publish.call_args.kwargs
        self.assertEqual(
            "amq.gen-private-response",
            published["properties"].reply_to,
        )
        channel.basic_get.assert_called_once_with(
            queue="amq.gen-private-response",
            auto_ack=False,
        )
        channel.basic_ack.assert_called_once_with(delivery_tag=71)
        channel.basic_nack.assert_not_called()

    def test_response_routes_directly_to_requested_queue(self):
        channel = MagicMock()
        response = {
            "success": True,
            "correlation_id": "current-request",
        }

        publish_auth_response(
            channel,
            response,
            reply_to="amq.gen-private-response",
        )

        published = channel.basic_publish.call_args.kwargs
        self.assertEqual("", published["exchange"])
        self.assertEqual("amq.gen-private-response", published["routing_key"])

    def test_response_requires_a_private_queue(self):
        channel = MagicMock()

        with self.assertRaisesRegex(ValueError, "private reply queue"):
            publish_auth_response(
                channel,
                {"success": True, "correlation_id": "current-request"},
                reply_to="",
            )

        channel.basic_publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
