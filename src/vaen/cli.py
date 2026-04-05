"""Minimal CLI surface for VAEN build and inspect."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import build_agent
from .errors import VAENError
from .inspect import format_inspect_output, inspect_agent_archive


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            output_path = build_agent(
                manifest_path=args.file,
                output_path=args.output,
                start=Path.cwd(),
            )
            print(f"Wrote {output_path}")
            return 0

        if args.command == "inspect":
            result = inspect_agent_archive(args.archive)
            print(format_inspect_output(result))
            return 0

        parser.print_help()
        return 1
    except VAENError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vaen",
        description="Build and inspect OCI-backed `.agent` bundles.",
    )
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser(
        "build",
        help="Build a `.agent` OCI archive from agent.yaml.",
    )
    build_parser.add_argument(
        "-f",
        "--file",
        help="Path to manifest file. Defaults to ./agent.yaml.",
    )
    build_parser.add_argument(
        "-o",
        "--output",
        help="Output .agent file. Defaults to <bundle-name>.agent in current directory.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a `.agent` archive and print stored metadata and paths.",
    )
    inspect_parser.add_argument("archive", help="Path to .agent archive.")

    return parser
