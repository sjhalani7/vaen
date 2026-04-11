"""Doctor module surface for validating a built or imported setup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Collection


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
) -> DoctorResult:
    """Run structural checks for an imported VAEN setup."""

    repo_root = resolve_doctor_target(target_repo=target_repo, start=start)
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

    # Task 32: discover only repo-local `.env` (no shell env lookup).
    checks_run.append("repo-dotenv-discovery")
    env_path = discover_repo_env_file(repo_root)
    if env_path is None:
        warnings.append(f"Missing repo .env file: {repo_root / '.env'}")
        env_var_names: set[str] = set()
    else:
        env_var_names = parse_repo_env_file(env_path)

    bundles = _discover_canonical_bundles(repo_root)
    checks_run.append("imported-bundle-presence")
    if not bundles:
        errors.append(
            f"No canonical imported bundle directory found under {repo_root / '.agent'}"
        )

    checks_run.append("root-agents-md-exists")
    if not (repo_root / "AGENTS.md").is_file():
        errors.append(f"Missing root AGENTS.md: {repo_root / 'AGENTS.md'}")

    checks_run.append("root-claude-md-exists")
    if not (repo_root / "CLAUDE.md").is_file():
        errors.append(f"Missing root CLAUDE.md: {repo_root / 'CLAUDE.md'}")

    checks_run.append("mirrored-agent-skills-dir-exists")
    if not (repo_root / ".agent" / "skills").is_dir():
        errors.append(f"Missing mirrored skills directory: {repo_root / '.agent' / 'skills'}")

    checks_run.append("mirrored-claude-skills-dir-exists")
    if not (repo_root / ".claude" / "skills").is_dir():
        errors.append(
            f"Missing mirrored skills directory: {repo_root / '.claude' / 'skills'}"
        )

    for bundle_dir in bundles:
        _check_bundle_structure(bundle_dir, checks_run, errors)
        if env_path is not None:
            _check_bundle_required_vars(bundle_dir, env_var_names, checks_run, errors)

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


def discover_repo_env_file(repo_root: Path) -> Path | None:
    """Return `<target-repo>/.env` when present, else `None`."""

    env_path = repo_root / ".env"
    if env_path.is_file():
        return env_path
    return None


def parse_repo_env_file(env_path: Path) -> set[str]:
    """Parse a `.env` file and return declared variable names only.

    Parsing is intentionally simple and tolerant:
    - blank lines and `#` comments are ignored
    - lines without `=` are ignored
    - optional leading `export ` is stripped
    """

    result: set[str] = set()
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        result.add(key)
    return result


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


def _check_bundle_structure(bundle_dir: Path, checks_run: list[str], errors: list[str]) -> None:
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
        errors.append(f"Missing canonical skills directory: {skills_dir}")


def _check_bundle_required_vars(
    bundle_dir: Path,
    env_var_names: Collection[str],
    checks_run: list[str],
    errors: list[str],
) -> None:
    bundle_name = bundle_dir.name
    checks_run.append(f"bundle:{bundle_name}:required-vars-present")

    metadata_path = bundle_dir / "vaen" / "metadata.json"
    if not metadata_path.is_file():
        return

    try:
        metadata_doc = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        errors.append(f"Malformed canonical metadata file: {metadata_path}")
        return

    if not isinstance(metadata_doc, dict):
        errors.append(f"Malformed canonical metadata file: {metadata_path}")
        return

    manifest_doc = metadata_doc.get("manifest", {})
    if not isinstance(manifest_doc, dict):
        errors.append(f"Malformed canonical manifest metadata in: {metadata_path}")
        return

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

    missing = [name for name in required_vars if name not in env_var_names]
    if missing:
        rendered = ", ".join(sorted(missing))
        errors.append(
            f"Missing required vars for bundle '{bundle_name}' in .env: {rendered}"
        )
