"""Tests manifest validation failures and path normalization behavior."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.errors import ManifestValidationError
from vaen.manifest import load_manifest


class ManifestValidationFailureTests(unittest.TestCase):
    def test_missing_publisher_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")
            (root / "skills" / "alpha").mkdir(parents=True)

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        "instructions:",
                        '  main: "./instructions/AGENTS.md"',
                        "artifacts:",
                        "  - type: skills",
                        '    path: "./skills/alpha"',
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(manifest)
            self.assertIn("publisher", str(ctx.exception))

    def test_artifacts_must_be_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        '  main: "./instructions/AGENTS.md"',
                        "artifacts: {}",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(manifest)
            self.assertIn("artifacts must be a list", str(ctx.exception))

    def test_invalid_artifact_type_uses_generic_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")
            (root / "skills" / "alpha").mkdir(parents=True)

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        '  main: "./instructions/AGENTS.md"',
                        "artifacts:",
                        "  - type: instructions",
                        '    path: "./skills/alpha"',
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(manifest)
            self.assertIn("must be one of: ['skills']", str(ctx.exception))

    def test_instructions_includes_must_be_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")
            (root / "skills" / "alpha").mkdir(parents=True)

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        '  main: "./instructions/AGENTS.md"',
                        '  includes: "./instructions/style.md"',
                        "artifacts:",
                        "  - type: skills",
                        '    path: "./skills/alpha"',
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(manifest)
            self.assertIn("instructions.includes must be a list", str(ctx.exception))


class ManifestPathNormalizationTests(unittest.TestCase):
    def test_external_source_paths_resolve_and_normalize(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            external = root / "external"
            external.mkdir()

            main = external / "AGENTS.md"
            include = external / "style.md"
            skill_dir = external / "code-review"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("# skill", encoding="utf-8")
            main.write_text("# main", encoding="utf-8")
            include.write_text("# include", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        f'  main: "{main}"',
                        "  includes:",
                        f'    - "{include}"',
                        "artifacts:",
                        "  - type: skills",
                        f'    path: "{skill_dir}"',
                    ]
                ),
                encoding="utf-8",
            )

            doc = load_manifest(manifest)
            self.assertIsNotNone(doc)
            assert doc is not None
            self.assertEqual(doc.instructions.main.source_path, main.resolve())
            self.assertEqual(
                doc.instructions.main.bundle_path,
                PurePosixPath("instructions", "main", "AGENTS.md"),
            )
            self.assertEqual(doc.instructions.includes[0].source_path, include.resolve())
            self.assertEqual(
                doc.instructions.includes[0].bundle_path,
                PurePosixPath("instructions", "includes", "style.md"),
            )
            self.assertEqual(doc.artifacts[0].source_path, skill_dir.resolve())
            self.assertEqual(
                doc.artifacts[0].bundle_path,
                PurePosixPath("skills", "code-review"),
            )

    def test_empty_artifacts_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        '  main: "./instructions/AGENTS.md"',
                        "artifacts: []",
                    ]
                ),
                encoding="utf-8",
            )

            doc = load_manifest(manifest)
            self.assertIsNotNone(doc)
            assert doc is not None
            self.assertEqual(doc.artifacts, ())


if __name__ == "__main__":
    unittest.main()
