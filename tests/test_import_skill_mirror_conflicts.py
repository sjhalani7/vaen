"""Tests import failure when mirrored skill names already exist."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.errors import BundleImportError
from vaen.importer import extract_canonical_bundle, mirror_imported_skills, prepare_import_plan


class ImportSkillMirrorConflictTests(unittest.TestCase):
    def _prepare_import_state(self) -> tuple[Path, Path, object]:
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
        return target_repo, canonical_destination, plan

    def test_import_fails_when_agent_skill_name_already_exists(self) -> None:
        target_repo, canonical_destination, plan = self._prepare_import_state()
        # Any existing incoming skill root should block mirror import.
        (target_repo / ".agent" / "skills" / "code-review").mkdir(parents=True)

        with self.assertRaises(BundleImportError) as ctx:
            mirror_imported_skills(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=target_repo,
            )
        self.assertIn("Mirrored skill name already exists", str(ctx.exception))

    def test_import_fails_when_claude_skill_name_already_exists(self) -> None:
        target_repo, canonical_destination, plan = self._prepare_import_state()
        (target_repo / ".claude" / "skills" / "code-review").mkdir(parents=True)

        with self.assertRaises(BundleImportError) as ctx:
            mirror_imported_skills(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=target_repo,
            )
        self.assertIn("Mirrored skill name already exists", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
