"""Tests import activation layout from a built synthetic `.agent` bundle."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.importer import (
    create_root_instruction_shims,
    extract_canonical_bundle,
    mirror_imported_skills,
    prepare_import_plan,
)


class ImportLayoutTests(unittest.TestCase):
    def test_import_creates_expected_activated_layout(self) -> None:
        fixture_manifest = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"

        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            archive_path = tmp_root / "synthetic.agent"
            target_repo = tmp_root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture_manifest, output_path=archive_path)

            plan = prepare_import_plan(archive_path)
            canonical_destination = extract_canonical_bundle(
                archive_path=archive_path,
                target_repo=target_repo,
            )
            agent_skills_root, claude_skills_root = mirror_imported_skills(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=target_repo,
            )
            agents_path, claude_path = create_root_instruction_shims(
                canonical_destination=canonical_destination,
                plan=plan,
                target_repo=target_repo,
            )

            # Root files.
            self.assertTrue(agents_path.is_file())
            self.assertTrue(claude_path.is_file())
            self.assertEqual(agents_path.read_text(encoding="utf-8"), claude_path.read_text(encoding="utf-8"))

            # Canonical bundle destination and core stored dirs/files.
            expected_canonical = (target_repo / ".agent" / "synthetic").resolve()
            self.assertEqual(canonical_destination, expected_canonical)
            self.assertTrue((expected_canonical / "instructions").is_dir())
            self.assertTrue((expected_canonical / "skills").is_dir())
            self.assertTrue((expected_canonical / "vaen" / "metadata.json").is_file())

            # Root instruction content comes from canonical main instruction.
            canonical_main = expected_canonical / Path(plan.main_instruction.as_posix())
            self.assertTrue(canonical_main.is_file())
            self.assertEqual(canonical_main.read_text(encoding="utf-8"), agents_path.read_text(encoding="utf-8"))

            # Mirrored skill roots.
            self.assertEqual(agent_skills_root, (target_repo / ".agent" / "skills").resolve())
            self.assertEqual(claude_skills_root, (target_repo / ".claude" / "skills").resolve())
            self.assertTrue(agent_skills_root.is_dir())
            self.assertTrue(claude_skills_root.is_dir())

            # Expected mirrored skills and canonical skills.
            for skill_name in ("code-review", "refactor"):
                canonical_skill_file = expected_canonical / "skills" / skill_name / "SKILL.md"
                self.assertTrue(canonical_skill_file.is_file())
                self.assertTrue((agent_skills_root / skill_name / "SKILL.md").is_file())
                self.assertTrue((claude_skills_root / skill_name / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
