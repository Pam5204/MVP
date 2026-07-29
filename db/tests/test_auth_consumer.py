"""Unit tests for the mysqlclient authentication-consumer boundary."""

import os
import unittest
from unittest.mock import MagicMock, patch

from db import auth_consumer


class AuthConsumerDatabaseTests(unittest.TestCase):
    """Verify transactions and cleanup without requiring a live database."""

    def _connection_with_cursor(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("db.auth_consumer.MySQLdb.connect")
    def test_database_connection_uses_mysqlclient_and_environment(self, connect):
        connection = connect.return_value
        environment = {
            "DB_HOST": "db.internal",
            "DB_PORT": "3307",
            "DB_USER": "dream_test",
            "DB_PASSWORD": "test-password",
            "DB_NAME": "DreamEscapes",
        }

        with patch.dict(os.environ, environment, clear=False):
            result = auth_consumer._database_connection()

        self.assertIs(result, connection)
        connect.assert_called_once_with(
            host="db.internal",
            port=3307,
            user="dream_test",
            passwd="test-password",
            db="DreamEscapes",
            charset="utf8mb4",
            cursorclass=auth_consumer.DictCursor,
        )
        connection.autocommit.assert_called_once_with(False)

    @patch("db.auth_consumer.bcrypt.hashpw", return_value=b"$2b$12$test-hash")
    @patch("db.auth_consumer._database_connection")
    def test_register_commits_and_closes_resources(self, database_connection, _hash):
        connection, cursor = self._connection_with_cursor()
        database_connection.return_value = connection
        cursor.lastrowid = 17
        cursor.fetchone.return_value = {
            "user_id": 17,
            "username": "Traveler",
            "email": "traveler@example.com",
            "role": "user",
            "account_status": "enabled",
            "travel_preferences": "",
        }

        result = auth_consumer._register(
            {
                "username": " Traveler ",
                "email": "Traveler@Example.com",
                "password": "secure-pass",
            }
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["payload"]["user_id"], 17)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    @patch("db.auth_consumer.bcrypt.hashpw", return_value=b"$2b$12$test-hash")
    @patch("db.auth_consumer._database_connection")
    def test_duplicate_registration_rolls_back(self, database_connection, _hash):
        connection, cursor = self._connection_with_cursor()
        database_connection.return_value = connection
        cursor.execute.side_effect = auth_consumer.MySQLdb.IntegrityError(
            1062, "Duplicate entry"
        )

        result = auth_consumer._register(
            {
                "username": "Traveler",
                "email": "traveler@example.com",
                "password": "secure-pass",
            }
        )

        self.assertFalse(result["success"])
        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    @patch("db.auth_consumer.bcrypt.checkpw", return_value=True)
    @patch("db.auth_consumer._database_connection")
    def test_login_commits_timestamp_update(self, database_connection, _check):
        connection, cursor = self._connection_with_cursor()
        database_connection.return_value = connection
        cursor.fetchone.return_value = {
            "user_id": 17,
            "username": "Traveler",
            "email": "traveler@example.com",
            "password_hash": "$2b$12$stored-hash",
            "role": "user",
            "account_status": "enabled",
            "travel_preferences": "",
        }

        result = auth_consumer._login(
            {"email": "Traveler@Example.com", "password": "secure-pass"}
        )

        self.assertTrue(result["success"])
        self.assertEqual(cursor.execute.call_count, 2)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()

    @patch("db.auth_consumer._database_connection")
    def test_failed_login_rolls_back_and_closes_resources(self, database_connection):
        connection, cursor = self._connection_with_cursor()
        database_connection.return_value = connection
        cursor.fetchone.return_value = None

        result = auth_consumer._login(
            {"email": "missing@example.com", "password": "secure-pass"}
        )

        self.assertFalse(result["success"])
        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()


class AuthConsumerRoutingTests(unittest.TestCase):
    """Verify the DB consumer returns results to each request's reply queue."""

    @patch("db.auth_consumer.pika.BlockingConnection")
    @patch("db.auth_consumer.declare_auth_topology")
    @patch("db.auth_consumer._publish_domain_result")
    @patch("db.auth_consumer.publish_auth_response")
    @patch("db.auth_consumer.process_auth_message")
    def test_callback_preserves_reply_to(
        self,
        process_message,
        publish_response,
        _publish_domain,
        _declare_topology,
        blocking_connection,
    ):
        connection = MagicMock()
        channel = MagicMock()
        connection.channel.return_value = channel
        connection.is_open = True
        blocking_connection.return_value = connection
        process_message.return_value = {
            "success": True,
            "correlation_id": "current-request",
            "payload": {},
        }

        auth_consumer.run_consumer()
        callback = channel.basic_consume.call_args.kwargs["on_message_callback"]
        method = MagicMock(delivery_tag=81)
        properties = MagicMock(reply_to="amq.gen-private-response")
        body = (
            b'{"type":"auth.login.request","correlation_id":"current-request",'
            b'"timestamp":"2026-07-29T12:00:00Z","payload":'
            b'{"email":"traveler@example.test","password":"test-password"}}'
        )

        callback(channel, method, properties, body)

        publish_response.assert_called_once_with(
            channel,
            process_message.return_value,
            reply_to="amq.gen-private-response",
        )
        channel.basic_ack.assert_called_once_with(delivery_tag=81)

    @patch("db.auth_consumer.pika.BlockingConnection")
    @patch("db.auth_consumer.declare_auth_topology")
    @patch("db.auth_consumer.publish_auth_error")
    @patch("db.auth_consumer.publish_auth_response")
    @patch("db.auth_consumer.process_auth_message")
    def test_callback_rejects_request_without_private_reply_queue(
        self,
        process_message,
        publish_response,
        publish_error,
        _declare_topology,
        blocking_connection,
    ):
        connection = MagicMock()
        channel = MagicMock()
        connection.channel.return_value = channel
        connection.is_open = True
        blocking_connection.return_value = connection

        auth_consumer.run_consumer()
        callback = channel.basic_consume.call_args.kwargs["on_message_callback"]
        method = MagicMock(delivery_tag=82)
        properties = MagicMock(reply_to=None)
        body = (
            b'{"type":"auth.login.request","correlation_id":"current-request",'
            b'"timestamp":"2026-07-29T12:00:00Z","payload":'
            b'{"email":"traveler@example.test","password":"test-password"}}'
        )

        callback(channel, method, properties, body)

        process_message.assert_not_called()
        publish_response.assert_not_called()
        publish_error.assert_called_once()
        channel.basic_nack.assert_called_once_with(
            delivery_tag=82,
            requeue=False,
        )


class AuthDomainEventTests(unittest.TestCase):
    """Verify the DB auth boundary emits the required safe MVP events."""

    @patch("db.auth_consumer.publish_event_type")
    def test_registration_emits_safe_account_created_event(self, publish_event):
        message = {
            "type": "auth.register.request",
            "correlation_id": "register-request",
            "timestamp": "2026-07-29T12:00:00Z",
            "payload": {
                "username": "Traveler",
                "email": "traveler@example.test",
                "password": "must-not-publish",
            },
        }
        response = {
            "success": True,
            "correlation_id": "register-request",
            "payload": {
                "user_id": 17,
                "username": "Traveler",
                "email": "traveler@example.test",
            },
        }

        auth_consumer._publish_domain_result(message, response)

        published = publish_event.call_args
        self.assertEqual("auth.account.created", published.args[0])
        self.assertEqual("db", published.kwargs["source"])
        self.assertEqual(17, published.kwargs["user_id"])
        self.assertNotIn("password", str(published).lower())


if __name__ == "__main__":
    unittest.main()
