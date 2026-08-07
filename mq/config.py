"""RabbitMQ names and routing contracts for DreamEscapes.

Only non-secret topology settings live here.  ``RABBITMQ_URL`` must be supplied
through the environment (normally from an uncommitted ``.env`` file).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


# Load the repository's private .env file when present. Environment variables
# already supplied by the shell or service manager keep precedence.
load_dotenv()

# ---------------------------------------------------------------------------
# Broker connection settings
#
# RABBITMQ_URL intentionally has no credential-bearing default. The heartbeat
# keeps idle connections healthy, while the blocked timeout prevents a caller
# from waiting forever when RabbitMQ applies resource back-pressure.
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
RABBITMQ_HEARTBEAT = int(os.getenv("RABBITMQ_HEARTBEAT", "30"))
RABBITMQ_BLOCKED_TIMEOUT = int(os.getenv("RABBITMQ_BLOCKED_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Exchange names and types
#
# Environment overrides allow VM-specific naming without editing source code.
AUTH_EXCHANGE = os.getenv("AUTH_EXCHANGE", "auth.exchange")
BUCKETLIST_EXCHANGE = os.getenv("BUCKETLIST_EXCHANGE", "bucketlist.exchange")
CACHE_EXCHANGE = os.getenv("CACHE_EXCHANGE", "cache.exchange")
ADMIN_EXCHANGE = os.getenv("ADMIN_EXCHANGE", "admin.exchange")
LOG_EXCHANGE = os.getenv("LOG_EXCHANGE", "log.exchange")
ERROR_EXCHANGE = os.getenv("ERROR_EXCHANGE", "error.exchange")

# auth.exchange is direct because App-to-DB authentication commands need exact
# routes. All auth event bindings are therefore explicit rather than wildcard
# bindings. The other domain exchanges are topics so their families can grow.
AUTH_EXCHANGE_TYPE = os.getenv("AUTH_EXCHANGE_TYPE", "direct")
EXCHANGE_TYPES = {
    AUTH_EXCHANGE: AUTH_EXCHANGE_TYPE,
    BUCKETLIST_EXCHANGE: "topic",
    CACHE_EXCHANGE: "topic",
    ADMIN_EXCHANGE: "topic",
    LOG_EXCHANGE: "topic",
    ERROR_EXCHANGE: "direct",
}

# ---------------------------------------------------------------------------
# Canonical application queues
#
# These are the queues assigned by the Pyu2 checklist. The separate error
# queue receives both explicit validation failures and broker dead letters.
AUTH_EVENTS_QUEUE = os.getenv("AUTH_EVENTS_QUEUE", "auth.events.queue")
PROFILE_EVENTS_QUEUE = os.getenv("PROFILE_EVENTS_QUEUE", "profile.events.queue")
BUCKETLIST_EVENTS_QUEUE = os.getenv(
    "BUCKETLIST_EVENTS_QUEUE", "bucketlist.events.queue"
)
CACHE_REFRESH_QUEUE = os.getenv("CACHE_REFRESH_QUEUE", "cache.refresh.queue")
API_FAILURE_QUEUE = os.getenv("API_FAILURE_QUEUE", "api.failure.queue")
ADMIN_AUDIT_QUEUE = os.getenv("ADMIN_AUDIT_QUEUE", "admin.audit.queue")
CENTRAL_LOG_QUEUE = os.getenv("CENTRAL_LOG_QUEUE", "central.log.queue")

ERROR_QUEUE = os.getenv("ERROR_QUEUE", "project.error.queue")
ERROR_ROUTING_KEY = os.getenv("ERROR_ROUTING_KEY", "error.message")
BAD_MESSAGE_LOG_FILE = os.getenv(
    "BAD_MESSAGE_LOG_FILE", "/var/log/dreamescapes/mq_bad_messages.log"
)
CENTRAL_LOG_FILE = os.getenv(
    "CENTRAL_LOG_FILE", "/var/log/dreamescapes/final_features.jsonl"
)


@dataclass(frozen=True)
class QueueBinding:
    """One durable project queue and the routes that feed it."""

    exchange: str
    routing_keys: tuple[str, ...]


# Each entry describes which exchange and routing keys feed one queue. This
# table is consumed by the topology creator, tests, and command-line listener.
QUEUE_BINDINGS = {
    AUTH_EVENTS_QUEUE: QueueBinding(
        AUTH_EXCHANGE,
        (
            "auth.account.created",
            "auth.login.success",
            "auth.login.failure",
            "auth.logout",
            "auth.password.changed",
            "auth.security.alert",
        ),
    ),
    PROFILE_EVENTS_QUEUE: QueueBinding(AUTH_EXCHANGE, ("profile.updated",)),
    BUCKETLIST_EVENTS_QUEUE: QueueBinding(BUCKETLIST_EXCHANGE, ("bucketlist.#",)),
    CACHE_REFRESH_QUEUE: QueueBinding(CACHE_EXCHANGE, ("cache.#",)),
    API_FAILURE_QUEUE: QueueBinding(CACHE_EXCHANGE, ("api.#",)),
    ADMIN_AUDIT_QUEUE: QueueBinding(ADMIN_EXCHANGE, ("admin.#",)),
    # Required final-feature actions are consumed additively into one JSONL
    # file by the supervised MQ logger. The same correlation ID returned by
    # the API remains in each event for production evidence.
    CENTRAL_LOG_QUEUE: QueueBinding(LOG_EXCHANGE, ("review.#", "community.#")),
}

# ---------------------------------------------------------------------------
# Event catalog and exchange ownership
#
# Producers may publish only these domain event types. Keeping one catalog
# catches routing-key spelling mistakes.
SUPPORTED_EVENT_TYPES = frozenset(
    {
        # US-01 account, authentication, and profile events.
        "auth.account.created",
        "auth.login.success",
        "auth.login.failure",
        "auth.logout",
        "auth.password.changed",
        "auth.security.alert",
        "profile.updated",
        # US-03 bucket-list events.
        "bucketlist.destination.saved",
        "bucketlist.destination.updated",
        "bucketlist.destination.deleted",
        "bucketlist.destination.duplicate_rejected",
        "bucketlist.updated",
        # US-02/US-05 cache and upstream API events.
        "cache.refresh.requested",
        "cache.refresh.completed",
        "cache.destination.updated",
        "cache.stale.used",
        "api.failure",
        "api.geoapify.unavailable",
        # US-04 administration/audit events.
        "admin.user.role_changed",
        "admin.user.status_changed",
        "admin.destination.reviewed",
        "admin.audit.created",
        "admin.unauthorized.attempted",
        # Required final-deliverable review and community logging events.
        "review.submitted",
        "community.post.created",
        "community.post.updated",
        "community.post.deleted",
        "community.post.moderated",
    }
)

# Derive the owning exchange once so publishers do not repeat routing logic.
EVENT_EXCHANGES = {
    event_type: (
        AUTH_EXCHANGE
        if event_type.startswith(("auth.", "profile."))
        else BUCKETLIST_EXCHANGE
        if event_type.startswith("bucketlist.")
        else CACHE_EXCHANGE
        if event_type.startswith(("cache.", "api."))
        else LOG_EXCHANGE
        if event_type.startswith(("review.", "community."))
        else ADMIN_EXCHANGE
    )
    for event_type in SUPPORTED_EVENT_TYPES
}

# ---------------------------------------------------------------------------
# Private App-to-DB authentication command routes
#
# These commands are separate from the safe audit/domain events listed above.
AUTH_REQUEST_QUEUE = os.getenv("AUTH_REQUEST_QUEUE", "auth.request.db.queue")
AUTH_ERROR_QUEUE = os.getenv("AUTH_ERROR_QUEUE", "auth.error.queue")
AUTH_ERROR_ROUTING_KEY = os.getenv("AUTH_ERROR_ROUTING_KEY", "auth.error")
AUTH_REGISTER_ROUTING_KEY = os.getenv(
    "AUTH_REGISTER_ROUTING_KEY", "auth.register.request"
)
AUTH_LOGIN_ROUTING_KEY = os.getenv("AUTH_LOGIN_ROUTING_KEY", "auth.login.request")
AUTH_REQUEST_TYPES = {
    "auth.register.request": AUTH_REGISTER_ROUTING_KEY,
    "auth.login.request": AUTH_LOGIN_ROUTING_KEY,
}
