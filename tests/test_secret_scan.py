"""Tests obvious secret-path detection and build-time rejection behavior."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.bundle import build_bundle_model
from vaen.errors import BuildScanError
from vaen.manifest import load_manifest
from vaen.secret_scan import is_obvious_secret_path


class SecretPathDetectionTests(unittest.TestCase):
    def test_matches_expected_obvious_secret_patterns(self) -> None:
        positives = [
            ".env",
            ".env.local",
            "id_rsa",
            "server.pem",
            "private.key",
            ".npmrc",
            ".pypirc",
            "credentials",
            "nested/credentials/file.txt",
        ]
        negatives = [
            "instructions/AGENTS.md",
            "skills/code-review/SKILL.md",
            "docs/credentialing.md",
            "notes/key-points.txt",
        ]

        for item in positives:
            with self.subTest(path=item):
                self.assertTrue(is_obvious_secret_path(item))

        for item in negatives:
            with self.subTest(path=item):
                self.assertFalse(is_obvious_secret_path(item))


class BuildSecretRejectionTests(unittest.TestCase):
    def test_build_rejects_dotenv_main_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env").write_text("OPENAI_API_KEY=secret", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        '  main: "./.env"',
                        "artifacts: []",
                    ]
                ),
                encoding="utf-8",
            )

            doc = load_manifest(manifest)
            with self.assertRaises(BuildScanError) as ctx:
                build_bundle_model(doc)
            self.assertIn("obvious secret path", str(ctx.exception))

    def test_build_rejects_credentials_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("# main", encoding="utf-8")
            (root / "credentials").mkdir()
            (root / "credentials" / "SKILL.md").write_text("# skill", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        '  main: "./instructions/AGENTS.md"',
                        "artifacts:",
                        "  - type: skills",
                        '    path: "./credentials"',
                    ]
                ),
                encoding="utf-8",
            )

            doc = load_manifest(manifest)
            with self.assertRaises(BuildScanError):
                build_bundle_model(doc)

    def test_build_allows_non_secret_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("# main", encoding="utf-8")
            (root / "skills" / "refactor").mkdir(parents=True)
            (root / "skills" / "refactor" / "SKILL.md").write_text(
                "# skill", encoding="utf-8"
            )

            manifest = root / "agent.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        'version: "0.1"',
                        'publisher: "Example"',
                        "instructions:",
                        '  main: "./instructions/AGENTS.md"',
                        "artifacts:",
                        "  - type: skills",
                        '    path: "./skills/refactor"',
                    ]
                ),
                encoding="utf-8",
            )

            doc = load_manifest(manifest)
            model = build_bundle_model(doc)
            self.assertGreaterEqual(len(model.entries), 2)


if __name__ == "__main__":
    unittest.main()
