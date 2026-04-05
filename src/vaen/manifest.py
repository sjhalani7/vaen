"""Manifest loading and validation for VAEN agent bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .errors import ManifestError, ManifestValidationError

_DEFAULT_MANIFEST_NAME = "agent.yaml"
_ALLOWED_ARTIFACT_TYPES = {"skills"}
_ALLOWED_INSTRUCTION_KEYS = {"main", "includes"}
_ALLOWED_ARTIFACT_KEYS = {"type", "path"}


@dataclass(frozen=True, slots=True)
class BundledPath:
    """A resolved local source path plus its sanitized bundle-relative path."""

    source_path: Path
    bundle_path: PurePosixPath


@dataclass(frozen=True, slots=True)
class InstructionsSpec:
    """Top-level instructions definition for an agent bundle."""

    main: BundledPath
    includes: tuple[BundledPath, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """A bundled artifact referenced by the manifest."""

    type: str
    source_path: Path
    bundle_path: PurePosixPath


@dataclass(frozen=True, slots=True)
class Manifest:
    """Validated VAEN manifest model."""

    version: str
    publisher: str
    instructions: InstructionsSpec
    artifacts: tuple[ArtifactSpec, ...]
    required_vars: tuple[str, ...] = ()
    source_path: Path | None = None
    source_root: Path | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def normalized_bundle_paths(self) -> dict[str, Any]:
        """Return bundle-relative paths only, excluding local source paths."""

        return {
            "instructions": {
                "main": str(self.instructions.main.bundle_path),
                "includes": [str(item.bundle_path) for item in self.instructions.includes],
            },
            "skills": [str(artifact.bundle_path) for artifact in self.artifacts],
        }


def discover_manifest(start: str | Path = ".", filename: str = _DEFAULT_MANIFEST_NAME) -> Path:
    """Return the manifest path rooted at ``start``.

    The discovery model is intentionally simple in v1: the manifest is expected
    to live at the supplied root directory, not searched recursively.
    """

    root = Path(start)
    manifest_path = root / filename
    if not manifest_path.is_file():
        raise ManifestError(f"Missing manifest: {manifest_path}")
    return manifest_path


def load_manifest(
    manifest_path: str | Path | None = None,
    *,
    start: str | Path = ".",
    required: bool = True,
) -> Manifest | None:
    """Load and validate an ``agent.yaml`` file.

    ``manifest_path`` can point to an explicit manifest file. If omitted, the
    manifest is discovered relative to ``start``. When ``required`` is ``False``,
    a missing manifest returns ``None`` so callers can implement ``-f``-style
    override behavior without duplicating discovery logic.
    """

    if manifest_path is None:
        discovered = Path(start) / _DEFAULT_MANIFEST_NAME
        if not discovered.is_file():
            if required:
                raise ManifestError(f"Missing manifest: {discovered}")
            return None
        manifest_path = discovered

    manifest_path = Path(manifest_path).expanduser()
    if not manifest_path.is_file():
        if required:
            raise ManifestError(f"Missing manifest: {manifest_path}")
        return None
    manifest_path = manifest_path.resolve()

    document = _read_yaml_document(manifest_path)
    if not isinstance(document, Mapping):
        raise ManifestValidationError("agent.yaml must contain a top-level mapping")

    return _manifest_from_mapping(document, source_path=manifest_path)


def _read_yaml_document(manifest_path: Path) -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency issue
        raise ManifestError(
            "PyYAML is required to parse agent.yaml files"
        ) from exc

    with manifest_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _manifest_from_mapping(mapping: Mapping[str, Any], *, source_path: Path) -> Manifest:
    version = _require_string(mapping, "version")
    publisher = _require_string(mapping, "publisher")
    source_root = source_path.parent
    instructions = _parse_instructions(mapping.get("instructions"), source_root)
    artifacts = _parse_artifacts(mapping.get("artifacts"), source_root)
    required_vars = _parse_required_vars(mapping.get("requiredVars"))

    extra = {
        key: value
        for key, value in mapping.items()
        if key not in {"version", "publisher", "instructions", "artifacts", "requiredVars"}
    }

    return Manifest(
        version=version,
        publisher=publisher,
        instructions=instructions,
        artifacts=artifacts,
        required_vars=required_vars,
        source_path=source_path,
        source_root=source_root,
        extra=extra,
    )


def _parse_instructions(raw: Any, source_root: Path) -> InstructionsSpec:
    if not isinstance(raw, Mapping):
        raise ManifestValidationError("instructions must be a mapping with main/includes")

    unsupported = set(raw.keys()) - _ALLOWED_INSTRUCTION_KEYS
    if unsupported:
        raise ManifestValidationError(
            "instructions supports only main and includes in v1"
        )

    main = _require_string(raw, "main", context="instructions")
    includes_raw = raw.get("includes", [])
    if includes_raw is None:
        includes_raw = []
    if not isinstance(includes_raw, list):
        raise ManifestValidationError("instructions.includes must be a list of strings")

    includes: list[BundledPath] = []
    for index, include in enumerate(includes_raw):
        if not isinstance(include, str) or not include.strip():
            raise ManifestValidationError(
                f"instructions.includes[{index}] must be a non-empty string"
            )
        includes.append(
            BundledPath(
                source_path=_resolve_existing_file(
                    include,
                    source_root,
                    context=f"instructions.includes[{index}]",
                ),
                bundle_path=PurePosixPath("instructions", "includes", Path(include).name),
            )
        )

    return InstructionsSpec(
        main=BundledPath(
            source_path=_resolve_existing_file(main, source_root, context="instructions.main"),
            bundle_path=PurePosixPath("instructions", "main", Path(main).name),
        ),
        includes=tuple(includes),
    )


def _parse_artifacts(raw: Any, source_root: Path) -> tuple[ArtifactSpec, ...]:
    if not isinstance(raw, list):
        raise ManifestValidationError("artifacts must be a list")
    if not raw:
        return ()

    artifacts: list[ArtifactSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ManifestValidationError(f"artifacts[{index}] must be a mapping")

        unsupported = set(item.keys()) - _ALLOWED_ARTIFACT_KEYS
        if unsupported:
            raise ManifestValidationError(
                f"artifacts[{index}] supports only type and path"
            )

        artifact_type = _require_string(item, "type", context=f"artifacts[{index}]")
        if artifact_type not in _ALLOWED_ARTIFACT_TYPES:
            raise ManifestValidationError(
                f"artifacts[{index}].type must be one of: {sorted(_ALLOWED_ARTIFACT_TYPES)}"
            )

        artifact_path = _require_string(item, "path", context=f"artifacts[{index}]")
        source_path = _resolve_existing_directory(
            artifact_path,
            source_root,
            context=f"artifacts[{index}].path",
        )
        artifacts.append(
            ArtifactSpec(
                type=artifact_type,
                source_path=source_path,
                bundle_path=PurePosixPath("skills", source_path.name),
            )
        )

    return tuple(artifacts)


def _parse_required_vars(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestValidationError("requiredVars must be a list of names")

    required_vars: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise ManifestValidationError(
                f"requiredVars[{index}] must be a non-empty string"
            )
        required_vars.append(item)

    return tuple(required_vars)


def _require_string(
    mapping: Mapping[str, Any],
    key: str,
    *,
    context: str | None = None,
) -> str:
    value = mapping.get(key)
    label = f"{context}.{key}" if context else key
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{label} must be a non-empty string")
    return value


def _resolve_existing_file(raw_path: str, source_root: Path, *, context: str) -> Path:
    candidate = _resolve_source_path(raw_path, source_root)
    if not candidate.is_file():
        raise ManifestValidationError(f"{context} must reference an existing file")
    return candidate


def _resolve_existing_directory(raw_path: str, source_root: Path, *, context: str) -> Path:
    candidate = _resolve_source_path(raw_path, source_root)
    if not candidate.is_dir():
        raise ManifestValidationError(f"{context} must reference an existing directory")
    return candidate


def _resolve_source_path(raw_path: str, source_root: Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = source_root / path
    return path.resolve()
