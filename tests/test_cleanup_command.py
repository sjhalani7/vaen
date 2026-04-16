"""Tests `vaen cleanup` success and refusal when canonical bundle state is missing."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.cli import main as cli_main
from vaen.importer import extract_canonical_bundle


class CleanupCommandTests(unittest.TestCase):
    def test_cleanup_removes_canonical_bundle_directory(self) -> None:
        fixture_manifest = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"

        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            archive_path = tmp_root / "synthetic.agent"
            target_repo = tmp_root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture_manifest, output_path=archive_path)
            canonical_destination = extract_canonical_bundle(
                archive_path=archive_path,
                target_repo=target_repo,
            )
            self.assertTrue(canonical_destination.is_dir())

            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                code = cli_main(
                    ["cleanup", str(archive_path), "--into", str(target_repo)]
                )

            self.assertEqual(code, 0)
            self.assertFalse(canonical_destination.exists())
            self.assertIn("Cleanup complete.", stdout_buffer.getvalue())

    def test_cleanup_refuses_when_canonical_bundle_missing(self) -> None:
        fixture_manifest = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"

        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            archive_path = tmp_root / "synthetic.agent"
            target_repo = tmp_root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture_manifest, output_path=archive_path)

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = cli_main(
                    ["cleanup", str(archive_path), "--into", str(target_repo)]
                )

            self.assertEqual(code, 2)
            self.assertIn(
                "Canonical bundle directory not found for cleanup",
                stderr_buffer.getvalue(),
            )


if __name__ == "__main__":
    unittest.main()
