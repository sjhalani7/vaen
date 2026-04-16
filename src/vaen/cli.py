"""CLI surface for VAEN v1 validate/build/inspect/import/doctor/cleanup commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import build_agent
from .doctor import run_doctor
from .errors import VAENError
from .importer import (
    cleanup_canonical_bundle,
    create_root_instruction_shims,
    extract_canonical_bundle,
    mirror_imported_skills,
    prepare_import_plan,
    resolve_import_target,
    resolve_import_target_overrides,
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
            overrides = resolve_import_target_overrides(
                target=args.target,
                target_instructions_file_name=args.target_instructions_file_name,
                target_skills_directory=args.target_skills_directory,
            )
            plan = prepare_import_plan(args.archive)
            canonical_destination = extract_canonical_bundle(
                archive_path=args.archive,
                target_repo=repo_root,
            )
            create_root_instruction_shims(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=repo_root,
                overrides=overrides,
            )
            mirror_imported_skills(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=repo_root,
                overrides=overrides,
            )
            print(f"Import complete. Canonical bundle extracted to {canonical_destination}")
            return 0

        if args.command == "doctor":
            result = run_doctor(
                target_repo=args.into,
                start=Path.cwd(),
                target=args.target,
                target_instructions_file_name=args.target_instructions_file_name,
                target_skills_directory=args.target_skills_directory,
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

        if args.command == "cleanup":
            deleted = cleanup_canonical_bundle(
                archive_path=args.archive,
                target_repo=args.into,
                start=Path.cwd(),
            )
            print(f"Cleanup complete. Removed canonical bundle directory {deleted}")
            return 0

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
            "import, doctor, and cleanup. MCP tool configuration support is planned for "
            "a later phase."
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
            "Import a `.agent` archive into a target repository "
            "(canonical extraction + activated instruction/skill outputs)."
        ),
    )
    import_parser.add_argument("archive", help="Path to .agent archive.")
    import_parser.add_argument(
        "--into",
        help="Target repository path. Defaults to current directory.",
    )
    import_parser.add_argument(
        "--target",
        help=(
            "Optional target name for derived activated outputs "
            "(for example: copilot -> COPILOT.md and .copilot/skills)."
        ),
    )
    import_parser.add_argument(
        "--target-instructions-file-name",
        help=(
            "Optional root instruction filename stem override for activated output "
            "(for example: copilot-instructions -> copilot-instructions.md)."
        ),
    )
    import_parser.add_argument(
        "--target-skills-directory",
        help=(
            "Optional skills directory name override for activated output "
            "(for example: copilot -> .copilot/skills)."
        ),
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help=(
            "Run setup validation checks for an imported repository "
            "(including requiredVars from .env and target-derived activated paths)."
        ),
    )
    doctor_parser.add_argument(
        "--into",
        help="Target repository path. Defaults to current directory.",
    )
    doctor_parser.add_argument(
        "--target",
        help=(
            "Optional target name for derived activated checks "
            "(for example: copilot -> COPILOT.md and .copilot/skills)."
        ),
    )
    doctor_parser.add_argument(
        "--target-instructions-file-name",
        help=(
            "Optional root instruction filename stem override for activated checks "
            "(for example: copilot-instructions -> copilot-instructions.md)."
        ),
    )
    doctor_parser.add_argument(
        "--target-skills-directory",
        help=(
            "Optional skills directory name override for activated checks "
            "(for example: copilot -> .copilot/skills)."
        ),
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help=(
            "Cleanup canonical imported bundle state for a `.agent` archive "
            "(deletes only `.agent/<bundle-name>` for the chosen archive/target pair)."
        ),
    )
    cleanup_parser.add_argument("archive", help="Path to .agent archive.")
    cleanup_parser.add_argument(
        "--into",
        help="Target repository path. Defaults to current directory.",
    )

    return parser
