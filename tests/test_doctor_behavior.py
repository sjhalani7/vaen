"""Tests doctor pass/warn/fail behavior."""

from __future__ import annotations

import shutil
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

    def test_doctor_reports_required_vars_without_requiring_env_file(self) -> None:
        repo = self._prepare_imported_repo()

        result = run_doctor(target_repo=repo)
        self.assertTrue(result.passed)
        self.assertTrue(
            any(
                "Required env vars declared by bundle 'synthetic'" in msg
                and "OPENAI_API_KEY" in msg
                and "SYNTHETIC_MCP_TOKEN" in msg
                for msg in result.warnings
            )
        )
        self.assertFalse(any("Missing repo .env file" in msg for msg in result.warnings))
        self.assertEqual(result.errors, ())

    def test_doctor_does_not_fail_based_on_env_contents(self) -> None:
        repo = self._prepare_imported_repo()
        (repo / ".env").write_text("OTHER_VAR=1\n", encoding="utf-8")

        result = run_doctor(target_repo=repo)
        self.assertTrue(result.passed)
        self.assertEqual(result.errors, ())

    def test_doctor_warns_but_passes_when_canonical_skills_missing(self) -> None:
        repo = self._prepare_imported_repo()
        shutil.rmtree(repo / ".agent" / "synthetic" / "skills")

        result = run_doctor(target_repo=repo)
        self.assertTrue(result.passed)
        self.assertTrue(
            any(
                "Missing canonical skills directory" in msg
                and "may simply mean the user did not package skills" in msg
                for msg in result.warnings
            )
        )
        self.assertEqual(result.errors, ())


if __name__ == "__main__":
    unittest.main()
