"""Build-time scanning for obvious secret-like source paths."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .errors import BuildScanError

_EXACT_NAMES = {
    ".env",
    "id_rsa",
    ".npmrc",
    ".pypirc",
    "credentials",
}

_SUFFIXES = {
    ".pem",
    ".key",
}


def is_obvious_secret_path(path: str | Path) -> bool:
    """Return ``True`` when a path matches the v1 obvious-secret rules."""

    raw = str(path)
    p = Path(raw)
    name = p.name.lower()

    if name in _EXACT_NAMES:
        return True
    if name.startswith(".env."):
        return True
    if any(name.endswith(suffix) for suffix in _SUFFIXES):
        return True
    if any(part.lower() == "credentials" for part in p.parts):
        return True
    return False


def scan_source_paths(paths: Iterable[str | Path]) -> None:
    """Raise ``BuildScanError`` when any source path is obviously sensitive."""

    rejected: list[str] = []
    for path in paths:
        if is_obvious_secret_path(path):
            rejected.append(str(path))

    if rejected:
        # Report only path locations, never secret values.
        rendered = ", ".join(sorted(set(rejected)))
        raise BuildScanError(f"Build rejected obvious secret path(s): {rendered}")
