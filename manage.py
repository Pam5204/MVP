#!/usr/bin/env python3
"""Django command runner for the DreamEscapes application."""

import os
import sys
from pathlib import Path


def main() -> None:
    """Run Django management commands with the repo/app paths available."""
    root_dir = Path(__file__).resolve().parent
    app_dir = root_dir / "app"
    sys.path.insert(0, str(root_dir))
    # Keep app_dir importable so the backend project package can be resolved.
    sys.path.append(str(app_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
