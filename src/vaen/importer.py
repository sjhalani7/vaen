"""Read `.agent` OCI archives and prepare import materialization plans."""

from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from .errors import BundleImportError

_METADATA_PATH = "vaen/metadata.json"
_ROOT_SHIMS = ("AGENTS.md", "CLAUDE.md")
_SKILL_MIRROR_ROOTS = ((".agent", "skills"), (".claude", "skills"))
_REPO_SAFE_TOKEN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_MCP_CODEX_CONFIG_PATH = (".codex", "config.toml")
_MCP_CLAUDE_CONFIG_PATH = (".mcp.json",)
_MCP_COPILOT_CONFIG_PATH = (".github", "mcp.json")


@dataclass(frozen=True, slots=True)
class SkillPlan:
    """One discovered skill root and the files present under it."""

    root: PurePosixPath
    files: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class MCPServerPlan:
    """One discovered canonical MCP server definition from the bundle layer."""

    name: str
    transport: str
    canonical_file: PurePosixPath
    definition: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """Structured import plan extracted from a `.agent` archive."""

    archive_path: Path
    metadata: Mapping[str, Any]
    main_instruction: PurePosixPath
    included_instructions: tuple[PurePosixPath, ...]
    skills: tuple[SkillPlan, ...]
    mcp_servers: tuple[MCPServerPlan, ...]
    layer_files: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class ImportTargetOverrides:
    """Validated optional import-target overrides from CLI flags."""

    target_name: str | None = None
    instruction_filename: str | None = None
    skills_directory_name: str | None = None


@dataclass(frozen=True, slots=True)
class ActivatedImportPaths:
    """Derived activated output paths for root instructions and mirrored skills."""

    root_instruction_paths: tuple[Path, ...]
    skills_mirror_roots: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class MCPClientTargetPaths:
    """Derived client-specific MCP target paths for later activation steps."""

    client: str
    config_path: Path


def render_mcp_config(plan: ImportPlan, client: str) -> str:
    """Render project-scoped MCP config for the selected client."""

    if client == "codex":
        return _render_codex_mcp_config(plan)
    if client == "claude":
        return _render_json_mcp_config(plan, _render_claude_mcp_server)
    if client == "copilot":
        return _render_json_mcp_config(plan, _render_copilot_mcp_server)
    raise BundleImportError(
        f"Unsupported MCP client `{client}`. Expected one of: codex, claude, copilot."
    )


def _render_codex_mcp_config(plan: ImportPlan) -> str:
    """Render project-scoped Codex MCP TOML from neutral MCP server definitions."""

    if not plan.mcp_servers:
        return ""

    lines: list[str] = []
    for index, server in enumerate(plan.mcp_servers):
        if index > 0:
            lines.append("")
        lines.extend(_render_codex_mcp_server(server))
    lines.append("")
    return "\n".join(lines)


def _render_json_mcp_config(
    plan: ImportPlan,
    render_server: Any,
) -> str:
    """Render clients whose project MCP config uses the mcpServers JSON shape."""

    if not plan.mcp_servers:
        return ""

    mcp_servers: dict[str, dict[str, Any]] = {}
    for server in plan.mcp_servers:
        mcp_servers[server.name] = render_server(server)

    return json.dumps({"mcpServers": mcp_servers}, indent=2) + "\n"


def validate_import_target_name(raw: str) -> str:
    """Validate `--target` name as repo-safe lowercase/number/hyphen."""

    return _validate_repo_safe_token(raw, field_label="target")


def validate_instruction_filename_stem(raw: str) -> str:
    """Validate instruction filename stem and return `<stem>.md`."""

    stem = _validate_repo_safe_token(raw, field_label="target-instructions-file-name")
    return f"{stem}.md"


def validate_target_skills_directory_name(raw: str) -> str:
    """Validate `--target-skills-directory` as repo-safe token."""

    return _validate_repo_safe_token(raw, field_label="target-skills-directory")


def resolve_import_target_overrides(
    target: str | None = None,
    *,
    target_instructions_file_name: str | None = None,
    target_skills_directory: str | None = None,
) -> ImportTargetOverrides:
    """Resolve validated target overrides and derived defaults.

    This helper is policy-only for later import wiring and does not mutate
    filesystem behavior in this step.
    """

    validated_target = (
        validate_import_target_name(target) if target is not None else None
    )
    validated_instruction_filename = (
        validate_instruction_filename_stem(target_instructions_file_name)
        if target_instructions_file_name is not None
        else None
    )
    validated_skills_directory = (
        validate_target_skills_directory_name(target_skills_directory)
        if target_skills_directory is not None
        else None
    )

    if validated_instruction_filename is None and validated_target is not None:
        validated_instruction_filename = f"{validated_target.upper()}.md"
    if validated_skills_directory is None and validated_target is not None:
        validated_skills_directory = validated_target

    return ImportTargetOverrides(
        target_name=validated_target,
        instruction_filename=validated_instruction_filename,
        skills_directory_name=validated_skills_directory,
    )


def resolve_import_target(
    target_path: str | Path | None = None,
    *,
    start: str | Path = ".",
) -> Path:
    """Resolve import target path, defaulting to the current working directory."""

    if target_path is None:
        target = Path(start)
    else:
        target = Path(target_path).expanduser()
    return target.resolve()


def derive_bundle_name(archive_path: str | Path) -> str:
    """Derive bundle name from archive filename stem.

    This is the deterministic fallback until a canonical manifest name is
    available. Example: ``foo.agent`` -> ``foo``.
    """

    archive = Path(archive_path).expanduser()
    bundle_name = archive.stem.strip()
    if not bundle_name:
        raise BundleImportError(f"Cannot derive bundle name from archive: {archive}")
    return bundle_name


def canonical_bundle_destination(target_repo: str | Path, archive_path: str | Path) -> Path:
    """Return canonical import destination ``<target_repo>/.agent/<bundle-name>``."""

    bundle_name = derive_bundle_name(archive_path)
    return resolve_import_target(target_repo) / ".agent" / bundle_name


def ensure_canonical_destination_available(
    target_repo: str | Path,
    archive_path: str | Path,
) -> Path:
    """Raise if canonical destination already exists, otherwise return it."""

    destination = canonical_bundle_destination(target_repo, archive_path)
    if destination.exists():
        raise BundleImportError(
            f"Import destination already exists: {destination}. "
            "Refusing to overwrite existing bundle directory."
        )
    return destination


def derive_activated_paths(
    target_repo: str | Path,
    overrides: ImportTargetOverrides | None = None,
) -> ActivatedImportPaths:
    """Derive activated output paths from optional import target overrides.

    Canonical extraction remains fixed at `.agent/<bundle-name>` and is not
    affected by these activated-output derivations.
    """

    repo_root = resolve_import_target(target_repo)
    active_overrides = overrides or ImportTargetOverrides()

    if active_overrides.instruction_filename is not None:
        root_instruction_paths = (repo_root / active_overrides.instruction_filename,)
    else:
        root_instruction_paths = tuple(repo_root / name for name in _ROOT_SHIMS)

    if active_overrides.skills_directory_name is not None:
        skills_mirror_roots = (
            repo_root / f".{active_overrides.skills_directory_name}" / "skills",
        )
    else:
        skills_mirror_roots = tuple(
            repo_root / root_tokens[0] / root_tokens[1]
            for root_tokens in _SKILL_MIRROR_ROOTS
        )

    return ActivatedImportPaths(
        root_instruction_paths=root_instruction_paths,
        skills_mirror_roots=skills_mirror_roots,
    )


def derive_mcp_client_target_paths(
    target_repo: str | Path,
    client: str,
) -> MCPClientTargetPaths:
    """Derive client-specific MCP target paths under the repo root.

    Codex, Claude, and Copilot all resolve to project-scoped config paths.
    """

    repo_root = resolve_import_target(target_repo)
    if client == "codex":
        return MCPClientTargetPaths(
            client=client,
            config_path=repo_root.joinpath(*_MCP_CODEX_CONFIG_PATH),
        )

    if client == "claude":
        return MCPClientTargetPaths(
            client=client,
            config_path=repo_root.joinpath(*_MCP_CLAUDE_CONFIG_PATH),
        )

    if client == "copilot":
        return MCPClientTargetPaths(
            client=client,
            config_path=repo_root.joinpath(*_MCP_COPILOT_CONFIG_PATH),
        )

    raise BundleImportError(
        f"Unsupported MCP client `{client}`. Expected one of: codex, claude, copilot."
    )


def ensure_mcp_client_target_available(
    target_repo: str | Path,
    archive_path: str | Path,
    client: str,
) -> MCPClientTargetPaths:
    """Raise if the activated MCP client config path already exists."""

    target_paths = derive_mcp_client_target_paths(target_repo, client)
    if target_paths.config_path.exists():
        canonical_mcp_root = canonical_bundle_destination(
            target_repo,
            archive_path,
        ) / "mcp"
        raise BundleImportError(
            f"MCP client config already exists: {target_paths.config_path}. "
            "Refusing to overwrite existing project MCP configuration. "
            f"Copy the generated files from the canonical bundle instead: {canonical_mcp_root}"
        )
    return target_paths


def write_selected_client_mcp_config(
    plan: ImportPlan,
    *,
    target_paths: MCPClientTargetPaths,
) -> Path:
    """Render and write the selected client's activated MCP config file."""

    payload = render_mcp_config(plan, target_paths.client)
    target_paths.config_path.parent.mkdir(parents=True, exist_ok=True)
    target_paths.config_path.write_text(payload, encoding="utf-8")
    return target_paths.config_path


def ensure_root_shims_available(
    target_repo: str | Path,
    overrides: ImportTargetOverrides | None = None,
) -> tuple[Path, ...]:
    """Raise if any configured root instruction output path already exists."""

    root_paths = derive_activated_paths(
        target_repo=target_repo,
        overrides=overrides,
    ).root_instruction_paths
    existing = [path for path in root_paths if path.exists()]
    if existing:
        rendered = ", ".join(str(path) for path in existing)
        raise BundleImportError(
            f"Root instruction shim already exists: {rendered}. "
            "Refusing to overwrite root instruction files."
        )
    return root_paths


def prepare_import_plan(archive_path: str | Path) -> ImportPlan:
    """Read a `.agent` archive and return a structured, policy-free plan."""

    path = Path(archive_path).expanduser()
    if not path.is_file():
        raise BundleImportError(f"Archive not found: {path}")

    layer_blob = _read_layer_blob(path)
    with tarfile.open(fileobj=io.BytesIO(layer_blob), mode="r:") as layer_tar:
        metadata = _read_metadata(layer_tar)
        layer_files = _list_layer_files(layer_tar)
        mcp_servers = _build_mcp_server_plans(layer_tar, metadata, layer_files)

    main, includes, skill_roots = _discover_paths(metadata, layer_files)
    skills = _build_skill_plans(skill_roots, layer_files)

    return ImportPlan(
        archive_path=path.resolve(),
        metadata=metadata,
        main_instruction=main,
        included_instructions=includes,
        skills=skills,
        mcp_servers=mcp_servers,
        layer_files=layer_files,
    )


def extract_canonical_bundle(
    archive_path: str | Path,
    target_repo: str | Path | None = None,
    *,
    start: str | Path = ".",
) -> Path:
    """Extract canonical bundle contents into ``.agent/<bundle-name>``.

    This writes only canonical stored content for the imported bundle:
    - ``instructions/...``
    - ``skills/...``
    - ``vaen/metadata.json``
    """

    repo_root = resolve_import_target(target_repo, start=start)
    destination = ensure_canonical_destination_available(repo_root, archive_path)

    plan = prepare_import_plan(archive_path)
    layer_blob = _read_layer_blob(plan.archive_path)

    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(layer_blob), mode="r:") as layer_tar:
        for member in layer_tar.getmembers():
            if not member.isfile():
                continue
            rel = _safe_rel_path(member.name)
            if not _is_canonical_stored_path(rel):
                continue
            payload = _read_tar_member(layer_tar, member.name)
            target_path = destination / Path(rel.as_posix())
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)

    return destination


def cleanup_canonical_bundle(
    archive_path: str | Path,
    target_repo: str | Path | None = None,
    *,
    start: str | Path = ".",
) -> Path:
    """Delete only canonical ``.agent/<bundle-name>`` for an imported archive."""

    repo_root = resolve_import_target(target_repo, start=start)
    destination = canonical_bundle_destination(repo_root, archive_path)
    canonical_root = (repo_root / ".agent").resolve()

    if destination.parent != canonical_root:
        raise BundleImportError(
            "Refusing cleanup: resolved canonical destination is outside `.agent` root."
        )
    if not destination.exists():
        raise BundleImportError(
            f"Canonical bundle directory not found for cleanup: {destination}"
        )
    if not destination.is_dir():
        raise BundleImportError(
            f"Refusing cleanup: canonical destination is not a directory: {destination}"
        )

    shutil.rmtree(destination)
    return destination


def create_root_instruction_shims(
    canonical_destination: str | Path,
    plan: ImportPlan,
    target_repo: str | Path,
    overrides: ImportTargetOverrides | None = None,
) -> tuple[Path, ...]:
    """Create identical root instruction shims from main instruction.

    The canonical bundle must already be extracted under ``canonical_destination``.
    This function writes only the root instruction shims and does not perform
    any skill mirroring or additional import orchestration.
    """

    root_paths = ensure_root_shims_available(
        target_repo=target_repo,
        overrides=overrides,
    )
    canonical_root = Path(canonical_destination).expanduser().resolve()
    source_instruction = canonical_root / Path(plan.main_instruction.as_posix())
    if not source_instruction.is_file():
        raise BundleImportError(
            "Canonical main instruction file is missing: "
            f"{source_instruction}"
        )

    content = source_instruction.read_bytes()
    for path in root_paths:
        path.write_bytes(content)
    return root_paths


def mirror_imported_skills(
    canonical_destination: str | Path,
    plan: ImportPlan,
    target_repo: str | Path,
    overrides: ImportTargetOverrides | None = None,
) -> tuple[Path, ...]:
    """Mirror imported skills into derived activated mirror roots.

    This function performs file-copy behavior only. Collision policy is handled
    separately by later import tasks.
    """

    canonical_root = Path(canonical_destination).expanduser().resolve()
    repo_root = resolve_import_target(target_repo)
    mirror_roots = derive_activated_paths(
        target_repo=repo_root,
        overrides=overrides,
    ).skills_mirror_roots

    for skill in plan.skills:
        if len(skill.root.parts) < 2:
            raise BundleImportError(f"Invalid skill root in import plan: {skill.root}")
        skill_name = skill.root.parts[1]
        per_root_skill_paths = tuple(root / skill_name for root in mirror_roots)
        existing = [path for path in per_root_skill_paths if path.exists()]
        if existing:
            rendered = ", ".join(str(path) for path in existing)
            raise BundleImportError(
                "Mirrored skill name already exists. "
                f"Refusing to overwrite: {rendered}"
            )
        for file_path in skill.files:
            source_file = canonical_root / Path(file_path.as_posix())
            if not source_file.is_file():
                raise BundleImportError(
                    f"Canonical skill file is missing: {source_file}"
                )
            relative = file_path.relative_to(skill.root)
            payload = source_file.read_bytes()
            for skill_root in per_root_skill_paths:
                target = skill_root / Path(relative.as_posix())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)

    return mirror_roots


def _read_layer_blob(archive_path: Path) -> bytes:
    with tarfile.open(archive_path, mode="r") as outer:
        index_doc = _parse_json(_read_tar_member(outer, "index.json"), "index.json")
        manifests = index_doc.get("manifests")
        if not isinstance(manifests, list) or not manifests:
            raise BundleImportError("Archive index.json has no manifests")

        manifest_entry = manifests[0]
        if not isinstance(manifest_entry, Mapping):
            raise BundleImportError("Archive index manifest entry is malformed")

        manifest_digest = manifest_entry.get("digest")
        if not isinstance(manifest_digest, str) or not manifest_digest:
            raise BundleImportError("Archive index manifest digest is missing")

        image_manifest = _parse_json(
            _read_blob(outer, manifest_digest),
            "manifest blob",
        )
        layers = image_manifest.get("layers")
        if not isinstance(layers, list) or not layers:
            raise BundleImportError("Archive manifest has no layers")

        layer_entry = layers[0]
        if not isinstance(layer_entry, Mapping):
            raise BundleImportError("Archive layer descriptor is malformed")

        layer_digest = layer_entry.get("digest")
        if not isinstance(layer_digest, str) or not layer_digest:
            raise BundleImportError("Archive layer digest is missing")

        return _read_blob(outer, layer_digest)


def _read_metadata(layer_tar: tarfile.TarFile) -> Mapping[str, Any]:
    metadata_doc = _parse_json(
        _read_tar_member(layer_tar, _METADATA_PATH),
        _METADATA_PATH,
    )
    if not isinstance(metadata_doc, Mapping):
        raise BundleImportError("Archive metadata is malformed")
    return metadata_doc


def _list_layer_files(layer_tar: tarfile.TarFile) -> tuple[PurePosixPath, ...]:
    files: list[PurePosixPath] = []
    for member in layer_tar.getmembers():
        if not member.isfile():
            continue
        if member.name == _METADATA_PATH:
            continue
        files.append(_safe_rel_path(member.name))
    return tuple(sorted(files, key=str))


def _discover_paths(
    metadata: Mapping[str, Any],
    layer_files: tuple[PurePosixPath, ...],
) -> tuple[PurePosixPath, tuple[PurePosixPath, ...], tuple[PurePosixPath, ...]]:
    main: PurePosixPath | None = None
    includes: list[PurePosixPath] = []
    skill_roots: list[PurePosixPath] = []

    entries_raw = metadata.get("entries", [])
    if isinstance(entries_raw, list):
        for entry in entries_raw:
            if not isinstance(entry, Mapping):
                continue
            kind = entry.get("kind")
            raw_path = entry.get("path")
            if not isinstance(kind, str) or not isinstance(raw_path, str):
                continue
            bundle_path = _safe_rel_path(raw_path)
            if kind == "instructions.main":
                main = bundle_path
            elif kind == "instructions.include":
                includes.append(bundle_path)
            elif kind == "artifact.skills":
                skill_roots.append(bundle_path)

    stored_paths_raw = metadata.get("storedPaths", [])
    if isinstance(stored_paths_raw, list):
        for raw in stored_paths_raw:
            if not isinstance(raw, str):
                continue
            bundle_path = _safe_rel_path(raw)
            if main is None and _is_under(bundle_path, PurePosixPath("instructions", "main")):
                main = bundle_path
            if _is_under(bundle_path, PurePosixPath("instructions", "includes")):
                includes.append(bundle_path)
            skill_root = _skill_root(bundle_path)
            if skill_root is not None:
                skill_roots.append(skill_root)

    if main is None:
        main_candidates = [
            item for item in layer_files if _is_under(item, PurePosixPath("instructions", "main"))
        ]
        if main_candidates:
            main = main_candidates[0]

    if not includes:
        includes = [
            item
            for item in layer_files
            if _is_under(item, PurePosixPath("instructions", "includes"))
        ]

    if not skill_roots:
        discovered_roots: list[PurePosixPath] = []
        for file_path in layer_files:
            root = _skill_root(file_path)
            if root is not None:
                discovered_roots.append(root)
        skill_roots = discovered_roots

    if main is None:
        raise BundleImportError("Archive does not contain a main instruction file")

    return (
        main,
        tuple(_dedupe_paths(includes)),
        tuple(_dedupe_paths(skill_roots)),
    )


def _build_skill_plans(
    skill_roots: tuple[PurePosixPath, ...],
    layer_files: tuple[PurePosixPath, ...],
) -> tuple[SkillPlan, ...]:
    plans: list[SkillPlan] = []
    for root in skill_roots:
        files = tuple(sorted((item for item in layer_files if _is_under(item, root)), key=str))
        plans.append(SkillPlan(root=root, files=files))
    return tuple(plans)


def _build_mcp_server_plans(
    layer_tar: tarfile.TarFile,
    metadata: Mapping[str, Any],
    layer_files: tuple[PurePosixPath, ...],
) -> tuple[MCPServerPlan, ...]:
    server_paths = _discover_mcp_server_paths(metadata, layer_files)
    plans: list[MCPServerPlan] = []
    seen_names: set[str] = set()

    for canonical_file in server_paths:
        definition = _parse_json(
            _read_tar_member(layer_tar, canonical_file.as_posix()),
            canonical_file.as_posix(),
        )
        if not isinstance(definition, Mapping):
            raise BundleImportError(
                f"Canonical MCP definition is malformed: {canonical_file}"
            )

        name = definition.get("name")
        if not isinstance(name, str) or not name:
            raise BundleImportError(
                f"Canonical MCP definition is missing name: {canonical_file}"
            )

        transport = definition.get("transport")
        if transport not in {"stdio", "http"}:
            raise BundleImportError(
                f"Canonical MCP definition has unsupported transport: {canonical_file}"
            )

        if name in seen_names:
            raise BundleImportError(
                f"Canonical MCP definition name is duplicated in archive: {name}"
            )
        seen_names.add(name)

        plans.append(
            MCPServerPlan(
                name=name,
                transport=transport,
                canonical_file=canonical_file,
                definition=definition,
            )
        )

    return tuple(plans)


def _discover_mcp_server_paths(
    metadata: Mapping[str, Any],
    layer_files: tuple[PurePosixPath, ...],
) -> tuple[PurePosixPath, ...]:
    paths: list[PurePosixPath] = []

    manifest_raw = metadata.get("manifest")
    if isinstance(manifest_raw, Mapping):
        mcp_raw = manifest_raw.get("mcp")
        if isinstance(mcp_raw, Mapping):
            servers_raw = mcp_raw.get("servers")
            if isinstance(servers_raw, list):
                for server in servers_raw:
                    if not isinstance(server, Mapping):
                        continue
                    raw_path = server.get("bundlePath")
                    if not isinstance(raw_path, str):
                        continue
                    bundle_path = _safe_rel_path(raw_path)
                    if _is_mcp_server_path(bundle_path):
                        paths.append(bundle_path)

    stored_paths_raw = metadata.get("storedPaths", [])
    if isinstance(stored_paths_raw, list):
        for raw_path in stored_paths_raw:
            if not isinstance(raw_path, str):
                continue
            bundle_path = _safe_rel_path(raw_path)
            if _is_mcp_server_path(bundle_path):
                paths.append(bundle_path)

    if not paths:
        paths = [item for item in layer_files if _is_mcp_server_path(item)]

    return tuple(_dedupe_paths(paths))


def _render_codex_mcp_server(server: MCPServerPlan) -> list[str]:
    definition = server.definition
    lines = [f'[mcp_servers.{_render_toml_key(server.name)}]']

    if server.transport == "stdio":
        command = _require_string_field(
            definition,
            "command",
            server.name,
        )
        lines.append(f"command = {_render_toml_string(command)}")
        args = _optional_string_list_field(definition, "args")
        if args:
            lines.append(f"args = {_render_toml_string_list(args)}")
        cwd = _optional_string_field(definition, "cwd")
        if cwd is not None:
            lines.append(f"cwd = {_render_toml_string(cwd)}")

        env_vars = _optional_string_list_field(definition, "envVars")
        if env_vars:
            lines.append(f"env_vars = {_render_toml_string_list(_dedupe_strings(env_vars))}")
        return lines

    if server.transport == "http":
        url = _require_string_field(definition, "url", server.name)
        lines.append(f"url = {_render_toml_string(url)}")
        bearer_token_env_var = _optional_string_field(definition, "bearerTokenEnvVar")
        if bearer_token_env_var is not None:
            lines.append(
                f"bearer_token_env_var = {_render_toml_string(bearer_token_env_var)}"
            )

        http_headers = _optional_string_mapping_field(definition, "httpHeaders")
        if http_headers:
            lines.append(f"http_headers = {_render_toml_string_mapping(http_headers)}")

        header_env_vars = _optional_string_mapping_field(definition, "headerEnvVars")
        if header_env_vars:
            lines.append(
                f"env_http_headers = {_render_toml_string_mapping(header_env_vars)}"
            )
        return lines

    raise BundleImportError(
        f"Unsupported MCP transport for Codex rendering: {server.transport}"
    )


def _render_claude_mcp_server(server: MCPServerPlan) -> dict[str, Any]:
    definition = server.definition

    if server.transport == "stdio":
        command = _require_string_field(definition, "command", server.name)
        rendered: dict[str, Any] = {
            "command": command,
            "args": list(_optional_string_list_field(definition, "args")),
        }
        cwd = _optional_string_field(definition, "cwd")
        if cwd is not None:
            rendered["cwd"] = cwd

        env_vars = _optional_string_list_field(definition, "envVars")
        if env_vars:
            rendered["env"] = _render_identity_env_placeholder_mapping(env_vars)
        return rendered

    if server.transport == "http":
        url = _require_string_field(definition, "url", server.name)
        rendered = {
            "type": "http",
            "url": url,
        }

        headers = _render_http_headers(definition)
        if headers:
            rendered["headers"] = headers
        return rendered

    raise BundleImportError(
        f"Unsupported MCP transport for Claude rendering: {server.transport}"
    )


def _render_copilot_mcp_server(server: MCPServerPlan) -> dict[str, Any]:
    definition = server.definition

    if server.transport == "stdio":
        command = _require_string_field(definition, "command", server.name)
        rendered: dict[str, Any] = {
            "type": "local",
            "command": command,
            "args": list(_optional_string_list_field(definition, "args")),
            "tools": ["*"],
        }
        cwd = _optional_string_field(definition, "cwd")
        if cwd is not None:
            rendered["cwd"] = cwd

        env_vars = _optional_string_list_field(definition, "envVars")
        if env_vars:
            rendered["env"] = _render_identity_env_placeholder_mapping(env_vars)
        return rendered

    if server.transport == "http":
        url = _require_string_field(definition, "url", server.name)
        rendered = {
            "type": "http",
            "url": url,
            "tools": ["*"],
        }

        headers = _render_http_headers(definition)
        if headers:
            rendered["headers"] = headers
        return rendered

    raise BundleImportError(
        f"Unsupported MCP transport for Copilot rendering: {server.transport}"
    )


def _safe_rel_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise BundleImportError(f"Archive contains unsafe path: {raw_path}")
    if not path.parts:
        raise BundleImportError("Archive contains an empty path")
    return path


def _validate_repo_safe_token(raw: str, *, field_label: str) -> str:
    value = raw.strip()
    if not value:
        raise BundleImportError(
            f"Invalid --{field_label}: value must be non-empty."
        )
    if not _REPO_SAFE_TOKEN_PATTERN.fullmatch(value):
        raise BundleImportError(
            f"Invalid --{field_label}: `{raw}`. "
            "Expected lowercase letters, numbers, or hyphens only."
        )
    return value


def _skill_root(path: PurePosixPath) -> PurePosixPath | None:
    if len(path.parts) < 2 or path.parts[0] != "skills":
        return None
    return PurePosixPath("skills", path.parts[1])


def _is_mcp_server_path(path: PurePosixPath) -> bool:
    return _is_under(path, PurePosixPath("mcp", "servers"))


def _is_canonical_stored_path(path: PurePosixPath) -> bool:
    if path.as_posix() == _METADATA_PATH:
        return True
    if _is_under(path, PurePosixPath("instructions")):
        return True
    if _is_under(path, PurePosixPath("skills")):
        return True
    if _is_under(path, PurePosixPath("mcp")):
        return True
    return False


def _is_under(path: PurePosixPath, root: PurePosixPath) -> bool:
    root_parts = root.parts
    return len(path.parts) >= len(root_parts) and path.parts[: len(root_parts)] == root_parts


def _dedupe_paths(paths: list[PurePosixPath]) -> list[PurePosixPath]:
    seen: set[PurePosixPath] = set()
    deduped: list[PurePosixPath] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _read_blob(outer_tar: tarfile.TarFile, digest: str) -> bytes:
    algorithm, hex_digest = digest.split(":", 1)
    member_name = f"blobs/{algorithm}/{hex_digest}"
    return _read_tar_member(outer_tar, member_name)


def _read_tar_member(tf: tarfile.TarFile, name: str) -> bytes:
    try:
        member = tf.getmember(name)
    except KeyError as exc:
        raise BundleImportError(f"Archive entry not found: {name}") from exc
    extracted = tf.extractfile(member)
    if extracted is None:
        raise BundleImportError(f"Failed to read archive entry: {name}")
    data = extracted.read()
    if data is None:
        raise BundleImportError(f"Failed to read archive entry: {name}")
    return data


def _parse_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleImportError(f"Archive JSON is malformed: {label}") from exc


def _require_string_field(
    definition: Mapping[str, Any],
    field_name: str,
    server_name: str,
) -> str:
    value = definition.get(field_name)
    if isinstance(value, str) and value:
        return value
    raise BundleImportError(
        f"Canonical MCP definition for {server_name!r} is missing {field_name}"
    )


def _optional_string_field(
    definition: Mapping[str, Any],
    field_name: str,
) -> str | None:
    value = definition.get(field_name)
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    raise BundleImportError(
        f"Canonical MCP definition field {field_name!r} must be a non-empty string"
    )


def _optional_string_list_field(
    definition: Mapping[str, Any],
    field_name: str,
) -> tuple[str, ...]:
    value = definition.get(field_name)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BundleImportError(
            f"Canonical MCP definition field {field_name!r} must be a list of strings"
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise BundleImportError(
                f"Canonical MCP definition field {field_name!r} must be a list of strings"
            )
        items.append(item)
    return tuple(items)


def _optional_string_mapping_field(
    definition: Mapping[str, Any],
    field_name: str,
) -> Mapping[str, str]:
    value = definition.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BundleImportError(
            f"Canonical MCP definition field {field_name!r} must be a string mapping"
        )

    rendered: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            raise BundleImportError(
                f"Canonical MCP definition field {field_name!r} must be a string mapping"
            )
        rendered[raw_key] = raw_value
    return rendered


def _render_toml_key(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return json.dumps(value)


def _render_toml_string(value: str) -> str:
    return json.dumps(value)


def _render_toml_string_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_render_toml_string(value) for value in values) + "]"


def _render_toml_string_mapping(values: Mapping[str, str]) -> str:
    rendered_items = [
        f"{_render_toml_string(key)} = {_render_toml_string(value)}"
        for key, value in sorted(values.items())
    ]
    return "{ " + ", ".join(rendered_items) + " }"


def _render_env_placeholder(env_var_name: str) -> str:
    return f"${{{env_var_name}}}"


def _render_env_placeholder_mapping(values: Mapping[str, str]) -> dict[str, str]:
    rendered: dict[str, str] = {}
    for key, env_var_name in sorted(values.items()):
        rendered[key] = _render_env_placeholder(env_var_name)
    return rendered


def _render_http_headers(definition: Mapping[str, Any]) -> dict[str, str]:
    """Render static and env-backed HTTP headers for JSON MCP clients."""

    headers = dict(_optional_string_mapping_field(definition, "httpHeaders"))
    bearer_token_env_var = _optional_string_field(definition, "bearerTokenEnvVar")
    if bearer_token_env_var is not None:
        _add_rendered_http_header(
            headers,
            "Authorization",
            f"Bearer {_render_env_placeholder(bearer_token_env_var)}",
        )

    header_env_vars = _optional_string_mapping_field(definition, "headerEnvVars")
    for header_name, header_value in _render_env_placeholder_mapping(header_env_vars).items():
        _add_rendered_http_header(headers, header_name, header_value)

    return headers


def _add_rendered_http_header(
    headers: dict[str, str],
    header_name: str,
    header_value: str,
) -> None:
    for existing_name in headers:
        if existing_name.lower() == header_name.lower():
            raise BundleImportError(
                f"Canonical MCP definition has duplicate HTTP header {header_name!r}"
            )
    headers[header_name] = header_value


def _render_identity_env_placeholder_mapping(
    env_var_names: Iterable[str],
) -> dict[str, str]:
    rendered: dict[str, str] = {}
    for env_var_name in _dedupe_strings(env_var_names):
        rendered[env_var_name] = _render_env_placeholder(env_var_name)
    return rendered


def _dedupe_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)
