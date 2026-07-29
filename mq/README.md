# DreamEscapes RabbitMQ

This package implements Pyu2 MVP/final-demo responsibilities: durable
domain topology, a shared safe event format, producer/consumer helpers,
dead-letter handling, VM setup, and broker-backed smoke tests.

## Topology

All exchanges and queues are durable. Every canonical application queue has
`error.exchange` / `error.message` configured as its dead-letter route.

| Exchange | Type | Purpose |
| --- | --- | --- |
| `auth.exchange` | direct | Account/profile events and private registration/login commands |
| `bucketlist.exchange` | topic | Bucket-list lifecycle events |
| `cache.exchange` | topic | Cache refresh/status and upstream API failures |
| `admin.exchange` | topic | Admin actions and audit events |
| `log.exchange` | topic | Reserved project logging exchange |
| `error.exchange` | direct | Rejected, malformed, and dead-lettered messages |

| Queue | Exchange | Binding(s) |
| --- | --- | --- |
| `auth.events.queue` | `auth.exchange` | `auth.account.created`, `auth.login.success`, `auth.login.failure`, `auth.logout`, `auth.password.changed`, `auth.security.alert` |
| `profile.events.queue` | `auth.exchange` | `profile.updated` |
| `bucketlist.events.queue` | `bucketlist.exchange` | `bucketlist.#` |
| `cache.refresh.queue` | `cache.exchange` | `cache.#` |
| `api.failure.queue` | `cache.exchange` | `api.#` |
| `admin.audit.queue` | `admin.exchange` | `admin.#` |
| `project.error.queue` | `error.exchange` | `error.message` |

The full event catalog lives in `mq.config.SUPPORTED_EVENT_TYPES`. It includes
all required checklist routes plus logout/security, duplicate-save rejection,
cache completion/destination/stale-cache, Geoapify-unavailable, destination
review, and unauthorized-admin events.

The durable `auth.request.db.queue` and `auth.error.queue` form the private
authentication command boundary used by the App and DB services. Each
registration or login request creates its own exclusive response queue,
preventing stale or concurrent responses from blocking authentication. There
is no shared authentication response queue. Audit/domain messages use the
standard event API below; they are never published to those command queues.

## Standard event format

Every new domain event uses one JSON envelope:

```json
{
  "event_id": "4b245fbe-b26b-4bcb-a702-d345215f7f18",
  "event_type": "profile.updated",
  "source": "app",
  "timestamp": "2026-07-19T16:00:00Z",
  "correlation_id": "request-123",
  "user_id": 1,
  "payload": {
    "message": "Profile updated"
  }
}
```

Required fields are `event_id`, `event_type`, `source`, `timestamp`,
`correlation_id`, and `payload`. Optional top-level IDs/status fields include
`user_id`, `place_id`, `bucket_item_id`, `admin_user_id`, `target_id`, `status`,
and `error_code`.

`mq.validation` recursively rejects password fields, password hashes, secrets,
API keys, tokens, authorization values, and credential objects. Rejection
records redact those fields. The error consumer logs only a SHA-256 fingerprint
and body size, never the rejected body.

## Publish and consume

```python
from mq.rabbitmq import publish_event_type

result = publish_event_type(
    "bucketlist.destination.saved",
    source="api",
    correlation_id="request-123",
    user_id=7,
    place_id="geoapify-place-id",
    bucket_item_id=42,
    payload={"message": "Destination saved"},
)
```

The publisher validates the event, declares topology idempotently, creates a
persistent message, uses mandatory routing, and waits for broker confirmation.

Consume a canonical queue for monitoring or future processing:

```bash
python -m mq.listener bucketlist.events.queue
python -m mq.listener cache.refresh.queue
python -m mq.listener bad
```

Consumers acknowledge successful messages. A malformed/failed message is
published once to the sanitized error route; if that fails, the original queue
dead-letters it with `requeue=False`, preventing a poison-message loop.

## MQ VM setup

Run from the repository root on Ubuntu/Debian. Supply credentials at the prompt
or through temporary environment variables; the script has no committed
password and does not grant the application user an administrator tag.

```bash
bash mq/setup-test_mq.sh
```

For non-interactive setup:

```bash
MQ_USER=dream_app \
MQ_PASSWORD='set-this-outside-git' \
MQ_BIND_ADDRESS=10.0.0.12 \
RUN_PUBLISH_EVENT_TEST=yes \
RUN_BAD_MESSAGE_TEST=no \
bash mq/setup-test_mq.sh
```

Use the MQ VM's private/ZeroTier address for `MQ_BIND_ADDRESS`, and restrict
TCP 5672 at the host/cloud firewall to the App, API, and DB VMs. Store the
resulting `RABBITMQ_URL` only in uncommitted `.env` files or service-manager
secrets. Do not use the remote `guest` account.

The single setup script installs/starts RabbitMQ, creates or updates the user
and vhost permissions, and declares all exchanges, queues, bindings, and
dead-letter settings. During an upgrade, it also deletes the retired
`auth.response.app.queue`, including any obsolete messages still in that
queue. It then asks two independent questions:

- `Run the publish-event test? [Y/n]`
- `Run the bad-message/DLQ test? [Y/n]`

Pressing Enter selects `Y`, the default. Answering the prompts lets you run
both tests, either test, or neither. For non-interactive execution, set
`RUN_PUBLISH_EVENT_TEST` and `RUN_BAD_MESSAGE_TEST` to `yes` or `no`.

The publish test sends account-created, profile, bucket-list save/delete,
cache refresh, API failure, and admin-audit events through temporary observers
and verifies each canonical queue. The bad-message test rejects a malformed
message with `requeue=False` and verifies that it reaches both
`error.exchange` and `project.error.queue`.

For lightweight broker monitoring on the MQ VM:

```bash
sudo rabbitmqctl list_exchanges name type durable
sudo rabbitmqctl list_queues name messages consumers
```

## Local tests

The unit suite does not require a running broker:

```bash
python -m unittest discover -s mq/tests -v
```

Broker-backed smoke tests require `RABBITMQ_URL` and a reachable RabbitMQ node.
