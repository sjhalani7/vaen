"""Build `.agent` archives using a minimal OCI image-layout tar format."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from .bundle import BundleModel, build_bundle_model
from .manifest import load_manifest

OCI_LAYOUT_PATH = "oci-layout"
INDEX_PATH = "index.json"
METADATA_PATH = "vaen/metadata.json"

_OCI_LAYOUT_VERSION = "1.0.0"
_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
_LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar"
_VAEN_ARTIFACT_TYPE = "application/vnd.vaen.agent.v1"


def build_agent(
    manifest_path: str | Path | None = None,
    output_path: str | Path | None = None,
    start: str | Path = ".",
) -> Path:
    """Build a `.agent` OCI image-layout archive and return its file path."""

    manifest = load_manifest(manifest_path=manifest_path, start=start, required=True)
    if manifest is None:  # pragma: no cover - guarded by required=True
        raise RuntimeError("Manifest unexpectedly missing")

    bundle = build_bundle_model(manifest)

    if output_path is None:
        bundle_name = _derive_bundle_name(manifest.source_root)
        archive_path = Path.cwd() / f"{bundle_name}.agent"
    else:
        archive_path = Path(output_path).expanduser()
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    layer_bytes = _build_layer_archive(bundle)
    layer_descriptor = _descriptor(layer_bytes, _LAYER_MEDIA_TYPE)

    config_bytes = json.dumps(
        {
            "architecture": "unknown",
            "os": "unknown",
            "rootfs": {"type": "layers", "diff_ids": [layer_descriptor["digest"]]},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    config_descriptor = _descriptor(config_bytes, _CONFIG_MEDIA_TYPE)

    oci_manifest = {
        "schemaVersion": 2,
        "mediaType": _MANIFEST_MEDIA_TYPE,
        "artifactType": _VAEN_ARTIFACT_TYPE,
        "config": config_descriptor,
        "layers": [layer_descriptor],
    }
    manifest_bytes = _encode_json(oci_manifest)
    manifest_descriptor = _descriptor(manifest_bytes, _MANIFEST_MEDIA_TYPE)

    index_bytes = _encode_json(
        {
            "schemaVersion": 2,
            "mediaType": _INDEX_MEDIA_TYPE,
            "manifests": [manifest_descriptor],
        }
    )
    layout_bytes = _encode_json({"imageLayoutVersion": _OCI_LAYOUT_VERSION})

    with tarfile.open(archive_path, mode="w") as tar:
        _add_bytes_to_tar(tar, OCI_LAYOUT_PATH, layout_bytes)
        _add_bytes_to_tar(tar, INDEX_PATH, index_bytes)
        _add_blob(tar, config_descriptor["digest"], config_bytes)
        _add_blob(tar, layer_descriptor["digest"], layer_bytes)
        _add_blob(tar, manifest_descriptor["digest"], manifest_bytes)

    return archive_path


def _derive_bundle_name(source_root: Path | None) -> str:
    if source_root is not None and source_root.name:
        return source_root.name
    return "bundle"


def _build_layer_archive(bundle: BundleModel) -> bytes:
    metadata_payload = {
        "manifest": dict(bundle.metadata),
        "storedPaths": [str(entry.bundle_path) for entry in bundle.entries],
        "entries": [
            {"kind": entry.kind, "path": str(entry.bundle_path)} for entry in bundle.entries
        ],
    }

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as layer_tar:
        _add_bytes_to_tar(layer_tar, METADATA_PATH, _encode_json(metadata_payload))
        for entry in sorted(bundle.entries, key=lambda item: str(item.bundle_path)):
            _add_entry(layer_tar, entry.source_path, entry.bundle_path)
    return buffer.getvalue()


def _add_entry(tar: tarfile.TarFile, source_path: Path, bundle_path: PurePosixPath) -> None:
    if source_path.is_file():
        _add_file_to_tar(tar, source_path, bundle_path)
        return

    if source_path.is_dir():
        for child in sorted(path for path in source_path.rglob("*") if path.is_file()):
            relative = child.relative_to(source_path)
            target = bundle_path / PurePosixPath(relative.as_posix())
            _add_file_to_tar(tar, child, target)
        return

    raise FileNotFoundError(f"Missing source path while building archive: {source_path}")


def _add_file_to_tar(tar: tarfile.TarFile, source_path: Path, target_path: PurePosixPath) -> None:
    data = source_path.read_bytes()
    _add_bytes_to_tar(tar, str(target_path), data)


def _add_blob(tar: tarfile.TarFile, digest: str, payload: bytes) -> None:
    algorithm, value = digest.split(":", 1)
    if algorithm != "sha256":
        raise ValueError(f"Unsupported OCI digest algorithm: {algorithm}")
    _add_bytes_to_tar(tar, f"blobs/sha256/{value}", payload)


def _descriptor(payload: bytes, media_type: str) -> dict[str, Any]:
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    return {
        "mediaType": media_type,
        "digest": digest,
        "size": len(payload),
    }


def _encode_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _add_bytes_to_tar(tar: tarfile.TarFile, path: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name=path)
    info.size = len(payload)
    info.mode = 0o644
    info.mtime = 0
    tar.addfile(info, io.BytesIO(payload))
