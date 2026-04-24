"""Tests CLI import leaves no partial canonical state on activation failures."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.cli import main as cli_main
from vaen.errors import BundleImportError


class ImportAtomicityTests(unittest.TestCase):
    def test_root_instruction_conflict_fails_before_canonical_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive_path = self._build_synthetic_archive(root)
            target_repo = root / "target-repo"
            target_repo.mkdir()
            existing_agents = target_repo / "AGENTS.md"
            existing_agents.write_text("existing\n", encoding="utf-8")

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = cli_main(
                    [
                        "import",
                        str(archive_path),
                        "--into",
                        str(target_repo),
                        "--client",
                        "codex",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertIn("Root instruction shim already exists", stderr_buffer.getvalue())
            self.assertFalse((target_repo / ".agent" / "synthetic").exists())
            self.assertEqual(existing_agents.read_text(encoding="utf-8"), "existing\n")

    def test_skill_mirror_conflict_fails_before_canonical_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive_path = self._build_synthetic_archive(root)
            target_repo = root / "target-repo"
            target_repo.mkdir()
            existing_skill = target_repo / ".codex" / "skills" / "code-review"
            existing_skill.mkdir(parents=True)

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = cli_main(
                    [
                        "import",
                        str(archive_path),
                        "--into",
                        str(target_repo),
                        "--client",
                        "codex",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertIn("Mirrored skill name already exists", stderr_buffer.getvalue())
            self.assertFalse((target_repo / ".agent" / "synthetic").exists())
            self.assertTrue(existing_skill.is_dir())

    def test_post_extraction_activation_failure_rolls_back_canonical_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive_path = self._build_synthetic_archive(root)
            target_repo = root / "target-repo"
            target_repo.mkdir()

            stderr_buffer = io.StringIO()
            with patch(
                "vaen.cli.create_root_instruction_shims",
                side_effect=BundleImportError("simulated activation failure"),
            ):
                with redirect_stderr(stderr_buffer):
                    code = cli_main(
                        [
                            "import",
                            str(archive_path),
                            "--into",
                            str(target_repo),
                            "--client",
                            "codex",
                        ]
                    )

            self.assertEqual(code, 2)
            self.assertIn("simulated activation failure", stderr_buffer.getvalue())
            self.assertFalse((target_repo / ".agent" / "synthetic").exists())

    def _build_synthetic_archive(self, root: Path) -> Path:
        fixture_manifest = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        archive_path = root / "synthetic.agent"
        build_agent(manifest_path=fixture_manifest, output_path=archive_path)
        return archive_path


if __name__ == "__main__":
    unittest.main()
