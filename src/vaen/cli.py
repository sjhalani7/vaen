"""CLI surface for VAEN v1 validate/build/inspect/import/doctor/cleanup commands."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from .build import build_agent
from .doctor import run_doctor
from .errors import BundleImportError, VAENError
from .importer import (
    cleanup_canonical_bundle,
    create_root_instruction_shims,
    ensure_mcp_client_target_available,
    ensure_root_shims_available,
    ensure_skill_mirrors_available,
    extract_canonical_bundle,
    mirror_imported_skills,
    prepare_import_plan,
    resolve_import_target,
    resolve_import_target_overrides_with_client_defaults,
    write_selected_client_mcp_config,
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
            overrides = resolve_import_target_overrides_with_client_defaults(
                client=args.client,
                target=args.target,
                target_instructions_file_name=args.target_instructions_file_name,
                target_skills_directory=args.target_skills_directory,
            )
            plan = prepare_import_plan(args.archive)
            if plan.mcp_servers and args.client is None:
                raise BundleImportError(
                    "Import requires --client when the bundle contains MCP servers."
                )
            ensure_root_shims_available(
                target_repo=repo_root,
                overrides=overrides,
            )
            ensure_skill_mirrors_available(
                target_repo=repo_root,
                plan=plan,
                overrides=overrides,
            )
            mcp_target_paths = None
            if plan.mcp_servers and args.client is not None:
                mcp_target_paths = ensure_mcp_client_target_available(
                    target_repo=repo_root,
                    archive_path=args.archive,
                    client=args.client,
                )
            canonical_destination = extract_canonical_bundle(
                archive_path=args.archive,
                target_repo=repo_root,
            )
            try:
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
                if mcp_target_paths is not None:
                    write_selected_client_mcp_config(
                        plan=plan,
                        target_paths=mcp_target_paths,
                    )
            except Exception:
                shutil.rmtree(canonical_destination, ignore_errors=True)
                raise
            print(f"Import complete. Canonical bundle extracted to {canonical_destination}")
            mcp_env_var_names = _collect_mcp_required_env_var_names(plan.metadata)
            if mcp_env_var_names:
                joined_names = ", ".join(mcp_env_var_names)
                print(f"MCP env vars to set locally: {joined_names}")
            return 0

        if args.command == "doctor":
            result = run_doctor(
                target_repo=args.into,
                start=Path.cwd(),
                target=args.target,
                target_instructions_file_name=args.target_instructions_file_name,
                target_skills_directory=args.target_skills_directory,
                client=args.client,
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
            "import, doctor, and cleanup."
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
    import_parser.add_argument(
        "--client",
        choices=("codex", "claude", "copilot"),
        help=(
            "Optional project-scoped MCP client target "
            "(codex, claude, or copilot). Required when the bundle contains MCP servers. "
            "If no activated-output override flags are provided "
            "(`--target`, `--target-instructions-file-name`, `--target-skills-directory`), "
            "`--client` also selects the default activated root instruction + skills mirror paths."
        ),
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help=(
            "Run setup validation checks for an imported repository "
            "(including requiredVars metadata and target-derived activated paths)."
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
    doctor_parser.add_argument(
        "--client",
        choices=("codex", "claude", "copilot"),
        help=(
            "Optional project-scoped MCP client target for MCP config checks "
            "(codex, claude, or copilot). If no activated-output override flags are provided "
            "(`--target`, `--target-instructions-file-name`, `--target-skills-directory`), "
            "`--client` also selects the default activated root instruction + skills mirror checks."
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


def _collect_mcp_required_env_var_names(metadata: Mapping[str, Any] | Any) -> tuple[str, ...]:
    """Return stable MCP-required env var names from import-plan metadata."""

    if not isinstance(metadata, Mapping):
        return ()

    manifest_metadata = metadata.get("manifest")
    if not isinstance(manifest_metadata, Mapping):
        return ()

    mcp_metadata = manifest_metadata.get("mcp")
    if not isinstance(mcp_metadata, Mapping):
        return ()

    servers = mcp_metadata.get("servers")
    if not isinstance(servers, list):
        return ()

    env_var_names: list[str] = []
    for server in servers:
        if not isinstance(server, Mapping):
            continue
        required_var_names = server.get("requiredVarNames")
        if not isinstance(required_var_names, list):
            continue
        for env_var_name in required_var_names:
            if isinstance(env_var_name, str) and env_var_name not in env_var_names:
                env_var_names.append(env_var_name)

    return tuple(env_var_names)
