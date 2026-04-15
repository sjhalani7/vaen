"""Read `.agent` OCI archives and prepare import materialization plans."""

from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .errors import BundleImportError

_METADATA_PATH = "vaen/metadata.json"
_ROOT_SHIMS = ("AGENTS.md", "CLAUDE.md")
_SKILL_MIRROR_ROOTS = ((".agent", "skills"), (".claude", "skills"))
_REPO_SAFE_TOKEN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class SkillPlan:
    """One discovered skill root and the files present under it."""

    root: PurePosixPath
    files: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """Structured import plan extracted from a `.agent` archive."""

    archive_path: Path
    metadata: Mapping[str, Any]
    main_instruction: PurePosixPath
    included_instructions: tuple[PurePosixPath, ...]
    skills: tuple[SkillPlan, ...]
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

    main, includes, skill_roots = _discover_paths(metadata, layer_files)
    skills = _build_skill_plans(skill_roots, layer_files)

    return ImportPlan(
        archive_path=path.resolve(),
        metadata=metadata,
        main_instruction=main,
        included_instructions=includes,
        skills=skills,
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


def _is_canonical_stored_path(path: PurePosixPath) -> bool:
    if path.as_posix() == _METADATA_PATH:
        return True
    if _is_under(path, PurePosixPath("instructions")):
        return True
    if _is_under(path, PurePosixPath("skills")):
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
