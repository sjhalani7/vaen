"""Tests import failure when root AGENTS.md or CLAUDE.md already exists."""

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
from vaen.importer import (
    create_root_instruction_shims,
    extract_canonical_bundle,
    prepare_import_plan,
)


class ImportRootShimConflictTests(unittest.TestCase):
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

    def test_import_fails_when_root_instruction_shim_already_exists(self) -> None:
        for existing_name in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(existing_name=existing_name):
                target_repo, canonical_destination, plan = self._prepare_import_state()
                (target_repo / existing_name).write_text("existing", encoding="utf-8")

                with self.assertRaises(BundleImportError) as ctx:
                    create_root_instruction_shims(
                        canonical_destination=canonical_destination,
                        plan=plan,
                        target_repo=target_repo,
                    )
                self.assertIn("Root instruction shim already exists", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
