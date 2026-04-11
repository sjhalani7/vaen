"""Tests doctor pass/warn/fail behavior for repo-local `.env` handling."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.doctor import run_doctor
from vaen.importer import (
    create_root_instruction_shims,
    extract_canonical_bundle,
    mirror_imported_skills,
    prepare_import_plan,
)


class DoctorBehaviorTests(unittest.TestCase):
    def _prepare_imported_repo(self) -> Path:
        fixture_manifest = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)

        archive_path = root / "synthetic.agent"
        target_repo = root / "target-repo"
        target_repo.mkdir()

        build_agent(manifest_path=fixture_manifest, output_path=archive_path)
        plan = prepare_import_plan(archive_path)
        canonical_destination = extract_canonical_bundle(
            archive_path=archive_path,
            target_repo=target_repo,
        )
        create_root_instruction_shims(
            canonical_destination=canonical_destination,
            plan=plan,
            target_repo=target_repo,
        )
        mirror_imported_skills(
            canonical_destination=canonical_destination,
            plan=plan,
            target_repo=target_repo,
        )
        return target_repo

    def test_doctor_passes_when_env_contains_required_var(self) -> None:
        repo = self._prepare_imported_repo()
        (repo / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

        result = run_doctor(target_repo=repo)
        self.assertTrue(result.passed)
        self.assertEqual(result.errors, ())

    def test_doctor_warns_but_passes_when_env_missing(self) -> None:
        repo = self._prepare_imported_repo()

        result = run_doctor(target_repo=repo)
        self.assertTrue(result.passed)
        self.assertTrue(any("Missing repo .env file" in msg for msg in result.warnings))
        self.assertEqual(result.errors, ())

    def test_doctor_fails_when_env_missing_required_var(self) -> None:
        repo = self._prepare_imported_repo()
        (repo / ".env").write_text("OTHER_VAR=1\n", encoding="utf-8")

        result = run_doctor(target_repo=repo)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("Missing required vars" in msg and "OPENAI_API_KEY" in msg for msg in result.errors)
        )


if __name__ == "__main__":
    unittest.main()
