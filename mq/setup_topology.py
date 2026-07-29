"""Idempotently create the DreamEscapes RabbitMQ topology."""

import argparse
import sys
from pathlib import Path

# Support both `python -m mq.setup_topology` and direct file execution.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mq.config import EXCHANGE_TYPES, QUEUE_BINDINGS
from mq.rabbitmq import _connection, declare_exchanges, declare_queues


def main() -> None:
    # The combined mode is used by setup-test_mq.sh. The split modes remain
    # useful when an operator wants to inspect exchanges before adding queues.
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--exchanges-only", action="store_true")
    mode.add_argument("--queues-only", action="store_true")
    args = parser.parse_args()

    # RabbitMQ declarations are idempotent when names and properties match, so
    # this command can safely be rerun during deployment.
    with _connection() as connection:
        channel = connection.channel()
        if not args.queues_only:
            declare_exchanges(channel)
        if not args.exchanges_only:
            # Queue declaration assumes exchanges already exist only when the
            # optional --queues-only CLI mode is used directly.
            declare_queues(channel)

    # Print a short deployment-friendly summary after successful declarations.
    if args.exchanges_only:
        print("Declared exchanges: " + ", ".join(EXCHANGE_TYPES))
    elif args.queues_only:
        print("Declared queues and bindings: " + ", ".join(QUEUE_BINDINGS))
    else:
        print(
            f"RabbitMQ topology ready: {len(EXCHANGE_TYPES)} exchanges and "
            f"{len(QUEUE_BINDINGS)} canonical event queues."
        )


if __name__ == "__main__":
    # Avoid connecting to RabbitMQ when this module is imported by tests/code.
    main()
