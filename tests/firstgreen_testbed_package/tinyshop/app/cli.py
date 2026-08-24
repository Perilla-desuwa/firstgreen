"""TinyShop command-line interface."""

import argparse
import json
from collections.abc import Sequence

from app.main import health


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinyshop")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("health", help="print health information")
    echo = subparsers.add_parser("echo", help="echo a value for smoke tests")
    echo.add_argument("value")
    return parser


def run(argv: Sequence[str] | None = None) -> tuple[int, str]:
    parser = build_parser()
    values = parser.parse_args(argv)
    if values.command == "health":
        return 0, json.dumps(health(), sort_keys=True)
    if values.command == "echo":
        return 0, str(values.value)
    return 0, parser.format_help().strip()


def main(argv: Sequence[str] | None = None) -> int:
    code, output = run(argv)
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
