"""Normalized bundle model and collision checks for build inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import quote

from .errors import BuildError
from .manifest import (
    ArtifactSpec,
    BundledPath,
    MCPHttpServerSpec,
    MCPStdioServerSpec,
    Manifest,
)
from .secret_scan import scan_source_paths


@dataclass(frozen=True, slots=True)
class BundleEntry:
    """A source path mapped to a normalized bundle-relative path."""

    kind: str
    source_path: Path
    bundle_path: PurePosixPath


@dataclass(frozen=True, slots=True)
class BundleModel:
    """Normalized, collision-free bundle inputs and stored manifest metadata."""

    entries: tuple[BundleEntry, ...]
    metadata: Mapping[str, Any]
    mcp_files: tuple["CanonicalMCPFile", ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalMCPFile:
    """A generated canonical MCP file that will be written into the bundle later."""

    server_name: str
    bundle_path: PurePosixPath


def build_bundle_model(manifest: Manifest) -> BundleModel:
    """Build a normalized bundle model from a validated manifest."""

    entries: list[BundleEntry] = []

    entries.append(_entry_from_bundled_path("instructions.main", manifest.instructions.main))

    for included in manifest.instructions.includes:
        entries.append(_entry_from_bundled_path("instructions.include", included))

    for artifact in manifest.artifacts:
        entries.append(_entry_from_artifact(artifact))

    mcp_files = _build_canonical_mcp_files(manifest)

    _check_entry_collisions(entries, mcp_files)
    scan_source_paths(entry.source_path for entry in entries)

    return BundleModel(
        entries=tuple(entries),
        metadata=_build_metadata(manifest),
        mcp_files=mcp_files,
    )


def _entry_from_bundled_path(kind: str, item: BundledPath) -> BundleEntry:
    return BundleEntry(kind=kind, source_path=item.source_path, bundle_path=item.bundle_path)


def _entry_from_artifact(artifact: ArtifactSpec) -> BundleEntry:
    return BundleEntry(
        kind=f"artifact.{artifact.type}",
        source_path=artifact.source_path,
        bundle_path=artifact.bundle_path,
    )


def _check_entry_collisions(
    entries: list[BundleEntry], mcp_files: tuple[CanonicalMCPFile, ...]
) -> None:
    seen: dict[PurePosixPath, str] = {}
    for entry in entries:
        previous = seen.get(entry.bundle_path)
        if previous is not None:
            raise BuildError(
                f"Bundle path collision for {entry.bundle_path}: "
                f"{previous} and {entry.source_path}"
            )
        seen[entry.bundle_path] = str(entry.source_path)

    for mcp_file in mcp_files:
        previous = seen.get(mcp_file.bundle_path)
        mcp_source = f"canonical MCP server {mcp_file.server_name!r}"
        if previous is not None:
            raise BuildError(
                f"Bundle path collision for {mcp_file.bundle_path}: "
                f"{previous} and {mcp_source}"
            )
        seen[mcp_file.bundle_path] = mcp_source


def _build_metadata(manifest: Manifest) -> Mapping[str, Any]:
    metadata: dict[str, Any] = {
        "version": manifest.version,
        "publisher": manifest.publisher,
        "requiredVars": _build_required_var_names(manifest),
    }

    mcp_metadata = _build_mcp_metadata(manifest)
    if mcp_metadata is not None:
        metadata["mcp"] = mcp_metadata

    if manifest.extra:
        metadata["extra"] = dict(manifest.extra)
    return metadata


def _build_canonical_mcp_files(manifest: Manifest) -> tuple[CanonicalMCPFile, ...]:
    if manifest.mcp is None:
        return ()

    return tuple(
        CanonicalMCPFile(
            server_name=server.name,
            bundle_path=_canonical_mcp_bundle_path(server.name),
        )
        for server in manifest.mcp.servers
    )


def _canonical_mcp_bundle_path(server_name: str) -> PurePosixPath:
    """Return the canonical neutral MCP path for a single server definition."""

    encoded_name = quote(server_name, safe="-_.")
    return PurePosixPath("mcp", "servers", f"{encoded_name}.json")


def _build_mcp_metadata(manifest: Manifest) -> Mapping[str, Any] | None:
    if manifest.mcp is None:
        return None

    return {
        "servers": [
            _build_mcp_server_metadata(server) for server in manifest.mcp.servers
        ]
    }


def _build_mcp_server_metadata(
    server: MCPStdioServerSpec | MCPHttpServerSpec,
) -> Mapping[str, Any]:
    metadata: dict[str, Any] = {
        "name": server.name,
        "transport": server.transport,
        "bundlePath": str(_canonical_mcp_bundle_path(server.name)),
        "requiredVarNames": _collect_server_required_var_names(server),
    }

    if isinstance(server, MCPStdioServerSpec):
        metadata["command"] = server.command
        metadata["args"] = list(server.args)
        if server.cwd is not None:
            metadata["cwd"] = server.cwd
        if server.env_vars:
            metadata["envVars"] = list(server.env_vars)
        return metadata

    metadata["url"] = server.url
    if server.bearer_token_env_var is not None:
        metadata["bearerTokenEnvVar"] = server.bearer_token_env_var
    if server.header_env_vars:
        metadata["headerEnvVars"] = dict(server.header_env_vars)
    return metadata


def _build_required_var_names(manifest: Manifest) -> list[str]:
    required_var_names = list(manifest.required_vars)

    if manifest.mcp is not None:
        for server in manifest.mcp.servers:
            for env_var_name in _collect_server_required_var_names(server):
                if env_var_name not in required_var_names:
                    required_var_names.append(env_var_name)

    return required_var_names


def _collect_server_required_var_names(
    server: MCPStdioServerSpec | MCPHttpServerSpec,
) -> list[str]:
    required_var_names: list[str] = []

    if isinstance(server, MCPStdioServerSpec):
        for env_var_name in server.env_vars:
            if env_var_name not in required_var_names:
                required_var_names.append(env_var_name)
        return required_var_names

    if server.bearer_token_env_var is not None:
        required_var_names.append(server.bearer_token_env_var)

    for env_var_name in server.header_env_vars.values():
        if env_var_name not in required_var_names:
            required_var_names.append(env_var_name)

    return required_var_names
