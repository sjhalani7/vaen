"""CLI surface for VAEN v1 validate/build/inspect/import/doctor commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import build_agent
from .doctor import run_doctor
from .errors import VAENError
from .importer import (
    create_root_instruction_shims,
    extract_canonical_bundle,
    mirror_imported_skills,
    prepare_import_plan,
    resolve_import_target,
)
from .inspect import format_inspect_output, inspect_agent_archive
from .manifest import load_manifest


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

        if args.command == "validate":
            load_manifest(
                manifest_path=args.file,
                start=Path.cwd(),
                required=True,
            )
            print("Manifest is valid for VAEN v1.")
            return 0

        if args.command == "inspect":
            result = inspect_agent_archive(args.archive)
            print(format_inspect_output(result))
            return 0

        if args.command == "import":
            repo_root = resolve_import_target(args.into, start=Path.cwd())
            plan = prepare_import_plan(args.archive)
            canonical_destination = extract_canonical_bundle(
                archive_path=args.archive,
                target_repo=repo_root,
            )
            create_root_instruction_shims(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=repo_root,
            )
            mirror_imported_skills(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=repo_root,
            )
            print(f"Import complete. Canonical bundle extracted to {canonical_destination}")
            return 0

        if args.command == "doctor":
            result = run_doctor(
                target_repo=args.into,
                start=Path.cwd(),
            )
            status = "PASS" if result.passed else "FAIL"
            print(f"Doctor {status}: {result.target_repo}")
            if result.warnings:
                print("Warnings:")
                for warning in result.warnings:
                    print(f"- {warning}")
            if result.errors:
                print("Errors:")
                for error in result.errors:
                    print(f"- {error}")
            print(f"Checks run: {len(result.checks_run)}")
            return 0 if result.passed else 2

        parser.print_help()
        return 1
    except VAENError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vaen",
        description=(
            "VAEN v1 CLI for OCI-backed `.agent` bundles: validate, build, inspect, "
            "import, and doctor. MCP tool configuration support is planned for a later phase."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser(
        "build",
        help="Build a VAEN v1 `.agent` OCI archive from agent.yaml.",
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

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an agent.yaml manifest against the VAEN v1 contract.",
    )
    validate_parser.add_argument(
        "-f",
        "--file",
        help="Path to manifest file. Defaults to ./agent.yaml.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a `.agent` archive and print stored metadata and bundle paths.",
    )
    inspect_parser.add_argument("archive", help="Path to .agent archive.")

    import_parser = subparsers.add_parser(
        "import",
        help=(
            "Import a `.agent` archive into a target repository (canonical bundle extraction, "
            "root instruction shims, and skill mirrors in v1)."
        ),
    )
    import_parser.add_argument("archive", help="Path to .agent archive.")
    import_parser.add_argument(
        "--into",
        help="Target repository path. Defaults to current directory.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run setup validation checks for an imported repository (including requiredVars from .env).",
    )
    doctor_parser.add_argument(
        "--into",
        help="Target repository path. Defaults to current directory.",
    )

    return parser
