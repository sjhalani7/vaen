"""Doctor module surface for validating a built or imported setup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 compatibility.
    tomllib = None

from .importer import (
    derive_activated_paths,
    derive_mcp_client_target_paths,
    resolve_import_target_overrides_with_client_defaults,
)

@dataclass(frozen=True, slots=True)
class DoctorResult:
    """Result model for doctor execution."""

    target_repo: Path
    passed: bool
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    checks_run: tuple[str, ...] = ()


def run_doctor(
    target_repo: str | Path | None = None,
    *,
    start: str | Path = ".",
    target: str | None = None,
    target_instructions_file_name: str | None = None,
    target_skills_directory: str | None = None,
    client: str | None = None,
) -> DoctorResult:
    """Run structural checks for an imported VAEN setup."""

    repo_root = resolve_doctor_target(target_repo=target_repo, start=start)
    overrides = resolve_import_target_overrides_with_client_defaults(
        client=client,
        target=target,
        target_instructions_file_name=target_instructions_file_name,
        target_skills_directory=target_skills_directory,
    )
    activated_paths = derive_activated_paths(
        target_repo=repo_root,
        overrides=overrides,
    )
    mcp_client_paths = (
        derive_mcp_client_target_paths(target_repo=repo_root, client=client)
        if client is not None
        else None
    )
    checks_run: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    checks_run.append("target-repo-exists")
    if not repo_root.exists():
        errors.append(f"Doctor target does not exist: {repo_root}")
        return DoctorResult(
            target_repo=repo_root,
            passed=False,
            errors=tuple(errors),
            checks_run=tuple(checks_run),
        )

    checks_run.append("target-repo-is-directory")
    if not repo_root.is_dir():
        errors.append(f"Doctor target is not a directory: {repo_root}")
        return DoctorResult(
            target_repo=repo_root,
            passed=False,
            errors=tuple(errors),
            checks_run=tuple(checks_run),
        )

    bundles = _discover_canonical_bundles(repo_root)
    checks_run.append("imported-bundle-presence")
    if not bundles:
        errors.append(
            f"No canonical imported bundle directory found under {repo_root / '.agent'}"
        )

    for path in activated_paths.root_instruction_paths:
        checks_run.append(f"root-instruction-exists:{path.name}")
        if not path.is_file():
            errors.append(f"Missing root instruction file: {path}")

    for path in activated_paths.skills_mirror_roots:
        checks_run.append(f"mirrored-skills-dir-exists:{path}")
        if not path.is_dir():
            errors.append(f"Missing mirrored skills directory: {path}")

    for bundle_dir in bundles:
        _check_bundle_structure(bundle_dir, checks_run, warnings, errors)
        manifest_doc = _read_bundle_manifest_metadata(bundle_dir, errors)
        _check_bundle_canonical_mcp_files(bundle_dir, manifest_doc, checks_run, errors)
        _report_bundle_required_vars(
            bundle_dir,
            manifest_doc,
            checks_run,
            warnings,
            errors,
        )

    if mcp_client_paths is not None:
        checks_run.append(f"mcp-client-config-exists:{mcp_client_paths.client}")
        if not mcp_client_paths.config_path.is_file():
            errors.append(
                "Missing activated MCP client config file "
                f"for '{mcp_client_paths.client}': {mcp_client_paths.config_path}"
            )
        elif mcp_client_paths.client == "codex":
            _check_codex_mcp_config_toml_syntax(
                mcp_client_paths.config_path,
                checks_run,
                errors,
            )
        elif mcp_client_paths.client in {"claude", "copilot"}:
            _check_json_mcp_config_syntax(
                mcp_client_paths.config_path,
                mcp_client_paths.client,
                checks_run,
                errors,
            )

    return DoctorResult(
        target_repo=repo_root,
        passed=not errors,
        warnings=tuple(warnings),
        errors=tuple(errors),
        checks_run=tuple(checks_run),
    )


def resolve_doctor_target(
    target_repo: str | Path | None = None,
    *,
    start: str | Path = ".",
) -> Path:
    """Resolve doctor target path, defaulting to the current working directory."""

    if target_repo is None:
        target = Path(start)
    else:
        target = Path(target_repo).expanduser()
    return target.resolve()


def _discover_canonical_bundles(repo_root: Path) -> tuple[Path, ...]:
    agent_root = repo_root / ".agent"
    if not agent_root.is_dir():
        return ()

    bundles = [
        entry
        for entry in agent_root.iterdir()
        if entry.is_dir() and entry.name != "skills"
    ]
    return tuple(sorted(bundles, key=lambda path: path.name))


def _check_bundle_structure(
    bundle_dir: Path,
    checks_run: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    bundle_name = bundle_dir.name

    metadata_path = bundle_dir / "vaen" / "metadata.json"
    checks_run.append(f"bundle:{bundle_name}:metadata-exists")
    if not metadata_path.is_file():
        errors.append(f"Missing canonical metadata file: {metadata_path}")

    instructions_dir = bundle_dir / "instructions"
    checks_run.append(f"bundle:{bundle_name}:instructions-dir-exists")
    if not instructions_dir.is_dir():
        errors.append(f"Missing canonical instructions directory: {instructions_dir}")

    skills_dir = bundle_dir / "skills"
    checks_run.append(f"bundle:{bundle_name}:skills-dir-exists")
    if not skills_dir.is_dir():
        warnings.append(
            "Missing canonical skills directory: "
            f"{skills_dir}. This may simply mean the user did not package skills."
        )


def _read_bundle_manifest_metadata(bundle_dir: Path, errors: list[str]) -> dict | None:
    metadata_path = bundle_dir / "vaen" / "metadata.json"
    if not metadata_path.is_file():
        return None

    try:
        metadata_doc = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        errors.append(f"Malformed canonical metadata file: {metadata_path}")
        return None

    if not isinstance(metadata_doc, dict):
        errors.append(f"Malformed canonical metadata file: {metadata_path}")
        return None

    manifest_doc = metadata_doc.get("manifest", {})
    if not isinstance(manifest_doc, dict):
        errors.append(f"Malformed canonical manifest metadata in: {metadata_path}")
        return None

    return manifest_doc


def _check_bundle_canonical_mcp_files(
    bundle_dir: Path,
    manifest_doc: dict | None,
    checks_run: list[str],
    errors: list[str],
) -> None:
    bundle_name = bundle_dir.name
    checks_run.append(f"bundle:{bundle_name}:canonical-mcp-files-exist")

    if manifest_doc is None:
        return

    metadata_path = bundle_dir / "vaen" / "metadata.json"
    mcp_raw = manifest_doc.get("mcp")
    if mcp_raw is None:
        return
    if not isinstance(mcp_raw, dict):
        errors.append(f"Malformed MCP metadata in: {metadata_path}")
        return

    servers_raw = mcp_raw.get("servers", [])
    if servers_raw is None:
        servers_raw = []
    if not isinstance(servers_raw, list):
        errors.append(f"Malformed MCP servers metadata in: {metadata_path}")
        return

    for server in servers_raw:
        if not isinstance(server, dict):
            errors.append(f"Malformed MCP servers metadata in: {metadata_path}")
            return

        raw_path = server.get("bundlePath")
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"Malformed MCP bundlePath metadata in: {metadata_path}")
            return

        bundle_path = PurePosixPath(raw_path)
        if (
            bundle_path.is_absolute()
            or ".." in bundle_path.parts
            or not bundle_path.parts
            or bundle_path.parts[0] != "mcp"
        ):
            errors.append(f"Malformed MCP bundlePath metadata in: {metadata_path}")
            return

        canonical_path = bundle_dir.joinpath(*bundle_path.parts)
        if not canonical_path.is_file():
            errors.append(f"Missing canonical MCP file: {canonical_path}")


def _check_codex_mcp_config_toml_syntax(
    config_path: Path,
    checks_run: list[str],
    errors: list[str],
) -> None:
    checks_run.append("mcp-client-config-toml-syntax:codex")
    if tomllib is None:
        return

    try:
        with config_path.open("rb") as config_file:
            tomllib.load(config_file)
    except tomllib.TOMLDecodeError:
        errors.append(f"Malformed activated Codex MCP config TOML: {config_path}")
    except OSError:
        errors.append(f"Unable to read activated Codex MCP config file: {config_path}")


def _check_json_mcp_config_syntax(
    config_path: Path,
    client: str,
    checks_run: list[str],
    errors: list[str],
) -> None:
    checks_run.append(f"mcp-client-config-json-syntax:{client}")
    client_label = client.capitalize()

    try:
        json.loads(config_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append(
            f"Malformed activated {client_label} MCP config JSON: {config_path}"
        )
    except OSError:
        errors.append(
            f"Unable to read activated {client_label} MCP config file: {config_path}"
        )


def _report_bundle_required_vars(
    bundle_dir: Path,
    manifest_doc: dict | None,
    checks_run: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    bundle_name = bundle_dir.name
    checks_run.append(f"bundle:{bundle_name}:required-vars-metadata")

    if manifest_doc is None:
        return

    metadata_path = bundle_dir / "vaen" / "metadata.json"
    required_raw = manifest_doc.get("requiredVars", [])
    if required_raw is None:
        required_raw = []
    if not isinstance(required_raw, list):
        errors.append(f"Malformed requiredVars in: {metadata_path}")
        return

    required_vars: list[str] = []
    for item in required_raw:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"Malformed requiredVars in: {metadata_path}")
            return
        required_vars.append(item.strip())

    if required_vars:
        rendered = ", ".join(sorted(required_vars))
        warnings.append(
            f"Required env vars declared by bundle '{bundle_name}': {rendered}"
        )
