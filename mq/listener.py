"""Command-line consumers for canonical project queues and the error queue."""

import argparse
import json

from mq.config import QUEUE_BINDINGS
from mq.rabbitmq import (
    consume_bad_messages,
    consume_central_logs,
    consume_event_queue,
)


def main():
    choices = ["bad", "central", *sorted(QUEUE_BINDINGS)]
    parser = argparse.ArgumentParser(description="Consume DreamEscapes MQ messages.")
    parser.add_argument(
        "queue",
        choices=choices,
        help="A canonical queue name or 'bad' for the project error queue.",
    )
    args = parser.parse_args()
    if args.queue == "bad":
        consume_bad_messages()
        return
    if args.queue == "central":
        consume_central_logs()
        return
    consume_event_queue(
        args.queue,
        lambda event: print(json.dumps(event, sort_keys=True)),
    )


if __name__ == "__main__":
    main()
