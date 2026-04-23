"""Tests client-derived default activated output mapping for import + doctor."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.cli import main as cli_main
from vaen.doctor import run_doctor


class ClientDefaultTargetMappingTests(unittest.TestCase):
    def test_import_and_doctor_with_client_codex_use_codex_defaults(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"

        with tempfile.TemporaryDirectory(prefix="vaen-test-client-defaults-codex-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            code = cli_main(
                [
                    "import",
                    str(archive),
                    "--into",
                    str(target_repo),
                    "--client",
                    "codex",
                ]
            )
            self.assertEqual(code, 0)

            self.assertTrue((target_repo / "AGENTS.md").is_file())
            self.assertFalse((target_repo / "CLAUDE.md").exists())

            self.assertTrue((target_repo / ".codex" / "skills").is_dir())
            self.assertFalse((target_repo / ".agent" / "skills").exists())
            self.assertFalse((target_repo / ".claude" / "skills").exists())
            self.assertTrue(
                (target_repo / ".codex" / "skills" / "code-review" / "SKILL.md").is_file()
            )

            self.assertTrue((target_repo / ".codex" / "config.toml").is_file())

            result = run_doctor(target_repo=target_repo, client="codex")
            self.assertTrue(result.passed)
            self.assertEqual(result.errors, ())
            self.assertIn("root-instruction-exists:AGENTS.md", result.checks_run)
            self.assertNotIn("root-instruction-exists:CLAUDE.md", result.checks_run)
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.codex' / 'skills').resolve()}",
                result.checks_run,
            )

    def test_import_and_doctor_with_client_claude_use_claude_defaults(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"

        with tempfile.TemporaryDirectory(prefix="vaen-test-client-defaults-claude-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            code = cli_main(
                [
                    "import",
                    str(archive),
                    "--into",
                    str(target_repo),
                    "--client",
                    "claude",
                ]
            )
            self.assertEqual(code, 0)

            self.assertTrue((target_repo / "CLAUDE.md").is_file())
            self.assertFalse((target_repo / "AGENTS.md").exists())

            self.assertTrue((target_repo / ".claude" / "skills").is_dir())
            self.assertFalse((target_repo / ".agent" / "skills").exists())
            self.assertFalse((target_repo / ".codex" / "skills").exists())
            self.assertTrue(
                (target_repo / ".claude" / "skills" / "code-review" / "SKILL.md").is_file()
            )

            self.assertTrue((target_repo / ".mcp.json").is_file())

            result = run_doctor(target_repo=target_repo, client="claude")
            self.assertTrue(result.passed)
            self.assertEqual(result.errors, ())
            self.assertIn("root-instruction-exists:CLAUDE.md", result.checks_run)
            self.assertNotIn("root-instruction-exists:AGENTS.md", result.checks_run)
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.claude' / 'skills').resolve()}",
                result.checks_run,
            )

    def test_explicit_target_override_disables_client_defaults(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"

        with tempfile.TemporaryDirectory(prefix="vaen-test-client-defaults-override-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            code = cli_main(
                [
                    "import",
                    str(archive),
                    "--into",
                    str(target_repo),
                    "--client",
                    "codex",
                    "--target",
                    "copilot",
                ]
            )
            self.assertEqual(code, 0)

            self.assertTrue((target_repo / "COPILOT.md").is_file())
            self.assertFalse((target_repo / "AGENTS.md").exists())
            self.assertFalse((target_repo / "CLAUDE.md").exists())

            self.assertTrue((target_repo / ".copilot" / "skills").is_dir())
            self.assertFalse((target_repo / ".codex" / "skills").exists())
            self.assertFalse((target_repo / ".agent" / "skills").exists())
            self.assertFalse((target_repo / ".claude" / "skills").exists())

            self.assertTrue((target_repo / ".codex" / "config.toml").is_file())

            result = run_doctor(target_repo=target_repo, target="copilot", client="codex")
            self.assertTrue(result.passed)
            self.assertEqual(result.errors, ())
            self.assertIn("root-instruction-exists:COPILOT.md", result.checks_run)
            self.assertNotIn("root-instruction-exists:AGENTS.md", result.checks_run)
            self.assertNotIn("root-instruction-exists:CLAUDE.md", result.checks_run)
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.copilot' / 'skills').resolve()}",
                result.checks_run,
            )


if __name__ == "__main__":
    unittest.main()

