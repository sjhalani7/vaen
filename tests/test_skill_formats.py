"""Tests preservation of different skill folder formats across build/import."""

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


class SkillFormatTests(unittest.TestCase):
    def test_skill_formats_are_preserved_through_build_and_import(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            target = root / "target-repo"
            archive = root / "formats.agent"
            target.mkdir()

            self._create_fixture(source)
            build_agent(manifest_path=source / "agent.yaml", output_path=archive)

            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target)
            create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target,
            )
            mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target,
            )

            expected_files = [
                "single-file/SKILL.md",
                "multi-file/SKILL.md",
                "multi-file/rules.txt",
                "nested/docs/howto.md",
                "nested/snippets/refactor.py",
            ]

            # Canonical stored skill files.
            for rel in expected_files:
                self.assertTrue((canonical / "skills" / rel).is_file(), rel)

            # Mirrored skill files in both .agent and .claude trees.
            for rel in expected_files:
                self.assertTrue((target / ".agent" / "skills" / rel).is_file(), rel)
                self.assertTrue((target / ".claude" / "skills" / rel).is_file(), rel)

            # Root instruction shims should be created and identical.
            agents_md = target / "AGENTS.md"
            claude_md = target / "CLAUDE.md"
            self.assertTrue(agents_md.is_file())
            self.assertTrue(claude_md.is_file())
            self.assertEqual(
                agents_md.read_text(encoding="utf-8"),
                claude_md.read_text(encoding="utf-8"),
            )

    def _create_fixture(self, source: Path) -> None:
        (source / "instructions").mkdir(parents=True)
        (source / "skills" / "single-file").mkdir(parents=True)
        (source / "skills" / "multi-file").mkdir(parents=True)
        (source / "skills" / "nested" / "docs").mkdir(parents=True)
        (source / "skills" / "nested" / "snippets").mkdir(parents=True)

        (source / "instructions" / "AGENTS.md").write_text(
            "# Test instructions\nUse concise outputs.\n",
            encoding="utf-8",
        )
        (source / "instructions" / "style.md").write_text(
            "# Include\nUse clear naming.\n",
            encoding="utf-8",
        )

        # Single-file skill folder.
        (source / "skills" / "single-file" / "SKILL.md").write_text(
            "# single\n",
            encoding="utf-8",
        )

        # Multi-file skill folder.
        (source / "skills" / "multi-file" / "SKILL.md").write_text(
            "# multi\n",
            encoding="utf-8",
        )
        (source / "skills" / "multi-file" / "rules.txt").write_text(
            "rule=keep-it-simple\n",
            encoding="utf-8",
        )

        # Nested files inside a skill folder.
        (source / "skills" / "nested" / "docs" / "howto.md").write_text(
            "# howto\n",
            encoding="utf-8",
        )
        (source / "skills" / "nested" / "snippets" / "refactor.py").write_text(
            "print('ok')\n",
            encoding="utf-8",
        )

        (source / "agent.yaml").write_text(
            "\n".join(
                [
                    'version: "0.1"',
                    'publisher: "Skill Format Fixture"',
                    "instructions:",
                    '  main: "./instructions/AGENTS.md"',
                    "  includes:",
                    '    - "./instructions/style.md"',
                    "artifacts:",
                    "  - type: skills",
                    '    path: "./skills/single-file"',
                    "  - type: skills",
                    '    path: "./skills/multi-file"',
                    "  - type: skills",
                    '    path: "./skills/nested"',
                    "requiredVars:",
                    "  - OPENAI_API_KEY",
                ]
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
