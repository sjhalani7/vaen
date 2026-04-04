"""Domain-specific exceptions for VAEN operations."""

from __future__ import annotations


class VAENError(Exception):
    """Base exception for all VAEN failures."""


class ManifestError(VAENError):
    """Raised when a manifest is missing, malformed, or unsupported."""


class ManifestValidationError(ManifestError):
    """Raised when a manifest fails structural or semantic validation."""


class BuildError(VAENError):
    """Raised when building a `.agent` bundle fails."""


class BuildScanError(BuildError):
    """Raised when build-time secret scanning rejects bundled inputs."""


class BundleImportError(VAENError):
    """Raised when importing or activating a bundle fails."""


class DoctorError(VAENError):
    """Raised when `vaen doctor` finds a blocking problem."""
