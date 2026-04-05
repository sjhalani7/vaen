"""Inspect behavior for `.agent` OCI archives."""

from __future__ import annotations

import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import BuildError


@dataclass(frozen=True, slots=True)
class InspectResult:
    """Structured view of a `.agent` archive."""

    archive_path: Path
    metadata: dict[str, Any]
    stored_paths: list[str]


def inspect_agent_archive(archive_path: str | Path) -> InspectResult:
    """Read a `.agent` OCI archive and return manifest metadata and stored paths."""

    path = Path(archive_path).expanduser()
    if not path.is_file():
        raise BuildError(f"Archive not found: {path}")

    with tarfile.open(path, mode="r") as outer:
        index_json = _read_tar_member(outer, "index.json")
        index = json.loads(index_json.decode("utf-8"))
        manifests = index.get("manifests", [])
        if not manifests:
            raise BuildError("Archive index.json has no manifests")

        manifest_digest = manifests[0]["digest"]
        manifest_blob = _read_blob(outer, manifest_digest)
        image_manifest = json.loads(manifest_blob.decode("utf-8"))
        layers = image_manifest.get("layers", [])
        if not layers:
            raise BuildError("Archive manifest has no layers")

        layer_digest = layers[0]["digest"]
        layer_blob = _read_blob(outer, layer_digest)

    with tarfile.open(fileobj=io.BytesIO(layer_blob), mode="r:") as layer_tar:
        metadata_blob = _read_tar_member(layer_tar, "vaen/metadata.json")
        metadata_doc = json.loads(metadata_blob.decode("utf-8"))

    stored_paths = metadata_doc.get("storedPaths", [])
    return InspectResult(
        archive_path=path.resolve(),
        metadata=metadata_doc,
        stored_paths=stored_paths,
    )


def format_inspect_output(result: InspectResult) -> str:
    """Render inspect output as human-readable JSON."""

    payload = {
        "archive": str(result.archive_path),
        "manifest": result.metadata.get("manifest", {}),
        "storedPaths": result.stored_paths,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _read_blob(outer_tar: tarfile.TarFile, digest: str) -> bytes:
    algorithm, hex_digest = digest.split(":", 1)
    member_name = f"blobs/{algorithm}/{hex_digest}"
    return _read_tar_member(outer_tar, member_name)


def _read_tar_member(tf: tarfile.TarFile, name: str) -> bytes:
    try:
        member = tf.getmember(name)
    except KeyError as exc:
        raise BuildError(f"Archive entry not found: {name}") from exc
    extracted = tf.extractfile(member)
    if extracted is None:
        raise BuildError(f"Failed to read archive entry: {name}")
    data = extracted.read()
    if data is None:
        raise BuildError(f"Failed to read archive entry: {name}")
    return data
