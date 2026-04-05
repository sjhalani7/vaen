"""Normalized bundle model and collision checks for build inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .errors import BuildError
from .manifest import ArtifactSpec, BundledPath, Manifest
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


def build_bundle_model(manifest: Manifest) -> BundleModel:
    """Build a normalized bundle model from a validated manifest."""

    entries: list[BundleEntry] = []

    entries.append(_entry_from_bundled_path("instructions.main", manifest.instructions.main))

    for included in manifest.instructions.includes:
        entries.append(_entry_from_bundled_path("instructions.include", included))

    for artifact in manifest.artifacts:
        entries.append(_entry_from_artifact(artifact))

    _check_entry_collisions(entries)
    scan_source_paths(entry.source_path for entry in entries)

    return BundleModel(entries=tuple(entries), metadata=_build_metadata(manifest))


def _entry_from_bundled_path(kind: str, item: BundledPath) -> BundleEntry:
    return BundleEntry(kind=kind, source_path=item.source_path, bundle_path=item.bundle_path)


def _entry_from_artifact(artifact: ArtifactSpec) -> BundleEntry:
    return BundleEntry(
        kind=f"artifact.{artifact.type}",
        source_path=artifact.source_path,
        bundle_path=artifact.bundle_path,
    )


def _check_entry_collisions(entries: list[BundleEntry]) -> None:
    seen: dict[PurePosixPath, Path] = {}
    for entry in entries:
        previous = seen.get(entry.bundle_path)
        if previous is not None:
            raise BuildError(
                f"Bundle path collision for {entry.bundle_path}: "
                f"{previous} and {entry.source_path}"
            )
        seen[entry.bundle_path] = entry.source_path


def _build_metadata(manifest: Manifest) -> Mapping[str, Any]:
    metadata: dict[str, Any] = {
        "version": manifest.version,
        "publisher": manifest.publisher,
        "requiredVars": list(manifest.required_vars),
    }

    if manifest.extra:
        metadata["extra"] = dict(manifest.extra)
    return metadata
