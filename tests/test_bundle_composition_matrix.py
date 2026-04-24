"""Composition-matrix tests for VAEN bundles.

This file verifies that different valid/invalid manifest "shapes" behave correctly:

- Invalid:
  - Missing top-level `instructions` fails validation.
  - Missing `instructions.main` fails validation.

- Valid bundles build + import + pass doctor for these compositions:
  - instructions only
  - instructions + skills
  - instructions + MCP
  - instructions + skills + MCP

For the import + doctor cases we assert both:
- Activated outputs in the target repo (root instruction shims, mirrored skills roots,
  and MCP client config when enabled).
- Canonical stored contents under `.agent/<bundle-name>` (main instruction, optional
  skills, optional canonical MCP server definitions, and `vaen/metadata.json`).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.cli import main as cli_main
from vaen.doctor import run_doctor
from vaen.errors import ManifestValidationError
from vaen.manifest import load_manifest


class BundleCompositionValidationFailureTests(unittest.TestCase):
    def test_missing_instructions_bucket(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vaen-test-composition-validate-") as tmp:
            root = Path(tmp)

            missing_instructions = root / "missing-instructions.yaml"
            missing_instructions.write_text(
                dedent(
                    """
                    version: "0.1"
                    publisher: "Fixture"
                    artifacts: []
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(missing_instructions)
            self.assertIn("instructions must be a mapping", str(ctx.exception))

            missing_instructions_main = root / "missing-instructions-main.yaml"
            missing_instructions_main.write_text(
                dedent(
                    """
                    version: "0.1"
                    publisher: "Fixture"
                    instructions: {}
                    artifacts: []
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(missing_instructions_main)
            self.assertIn("instructions.main must be a non-empty string", str(ctx.exception))


class BundleCompositionMatrixTests(unittest.TestCase):
    def test_build_import_doctor_matrix(self) -> None:
        cases = [
            ("instructions-only", False, False),
            ("instructions-skills", True, False),
            ("instructions-mcp", False, True),
            ("instructions-skills-mcp", True, True),
        ]

        for bundle_name, with_skills, with_mcp in cases:
            with self.subTest(bundle=bundle_name):
                with tempfile.TemporaryDirectory(prefix="vaen-test-composition-") as tmp:
                    root = Path(tmp)
                    manifest_path = _write_fixture_manifest(
                        root,
                        bundle_name=bundle_name,
                        with_skills=with_skills,
                        with_mcp=with_mcp,
                    )
                    archive_path = root / f"{bundle_name}.agent"
                    target_repo = root / "target-repo"
                    target_repo.mkdir()

                    build_agent(manifest_path=manifest_path, output_path=archive_path)

                    client = "codex" if with_mcp else None
                    self._import_archive(archive_path, target_repo=target_repo, client=client)
                    self._assert_activated_outputs(
                        target_repo=target_repo,
                        bundle_name=bundle_name,
                        with_skills=with_skills,
                        with_mcp=with_mcp,
                        client=client,
                    )
                    self._assert_canonical_outputs(
                        target_repo=target_repo,
                        bundle_name=bundle_name,
                        with_skills=with_skills,
                        with_mcp=with_mcp,
                    )

                    result = run_doctor(target_repo=target_repo, client=client)
                    self.assertTrue(result.passed)
                    self.assertEqual(result.errors, ())

    def _import_archive(self, archive_path: Path, *, target_repo: Path, client: str | None) -> None:
        argv = ["import", str(archive_path), "--into", str(target_repo)]
        if client is not None:
            argv += ["--client", client]
        code = cli_main(argv)
        self.assertEqual(code, 0)

    def _assert_activated_outputs(
        self,
        *,
        target_repo: Path,
        bundle_name: str,
        with_skills: bool,
        with_mcp: bool,
        client: str | None,
    ) -> None:
        expected_main = "# Main instructions\n"
        canonical_main = (
            target_repo / ".agent" / bundle_name / "instructions" / "main" / "AGENTS.md"
        )
        self.assertTrue(canonical_main.is_file())

        if client is None:
            self.assertTrue((target_repo / "AGENTS.md").is_file())
            self.assertTrue((target_repo / "CLAUDE.md").is_file())
            self.assertEqual((target_repo / "AGENTS.md").read_text(encoding="utf-8"), expected_main)
            self.assertEqual((target_repo / "CLAUDE.md").read_text(encoding="utf-8"), expected_main)

            # Doctor requires these directories exist even when no skills are packaged.
            self.assertTrue((target_repo / ".agent" / "skills").is_dir())
            self.assertTrue((target_repo / ".claude" / "skills").is_dir())

            if with_skills:
                self.assertTrue(
                    (target_repo / ".agent" / "skills" / "code-review" / "SKILL.md").is_file()
                )
                self.assertTrue(
                    (target_repo / ".claude" / "skills" / "code-review" / "SKILL.md").is_file()
                )
        else:
            self.assertEqual(client, "codex")
            self.assertTrue((target_repo / "AGENTS.md").is_file())
            self.assertFalse((target_repo / "CLAUDE.md").exists())
            self.assertEqual((target_repo / "AGENTS.md").read_text(encoding="utf-8"), expected_main)

            self.assertTrue((target_repo / ".codex" / "skills").is_dir())
            if with_skills:
                self.assertTrue(
                    (target_repo / ".codex" / "skills" / "code-review" / "SKILL.md").is_file()
                )

            if with_mcp:
                config_path = target_repo / ".codex" / "config.toml"
                self.assertTrue(config_path.is_file())
                self.assertIn("[mcp_servers.postgres]", config_path.read_text(encoding="utf-8"))

    def _assert_canonical_outputs(
        self,
        *,
        target_repo: Path,
        bundle_name: str,
        with_skills: bool,
        with_mcp: bool,
    ) -> None:
        canonical_root = target_repo / ".agent" / bundle_name
        self.assertTrue((canonical_root / "vaen" / "metadata.json").is_file())
        self.assertTrue(
            (canonical_root / "instructions" / "main" / "AGENTS.md").is_file()
        )
        self.assertEqual(
            (canonical_root / "instructions" / "main" / "AGENTS.md").read_text(encoding="utf-8"),
            "# Main instructions\n",
        )

        if with_skills:
            self.assertTrue(
                (canonical_root / "skills" / "code-review" / "SKILL.md").is_file()
            )
            self.assertIn(
                "Code review skill",
                (canonical_root / "skills" / "code-review" / "SKILL.md").read_text(encoding="utf-8"),
            )

        if with_mcp:
            canonical_server = canonical_root / "mcp" / "servers" / "postgres.json"
            self.assertTrue(canonical_server.is_file())
            doc = json.loads(canonical_server.read_text(encoding="utf-8"))
            self.assertEqual(doc.get("name"), "postgres")
            self.assertEqual(doc.get("transport"), "stdio")


def _write_fixture_manifest(
    root: Path,
    *,
    bundle_name: str,
    with_skills: bool,
    with_mcp: bool,
) -> Path:
    instructions_dir = root / "instructions"
    instructions_dir.mkdir()
    (instructions_dir / "AGENTS.md").write_text("# Main instructions\n", encoding="utf-8")

    manifest_lines: list[str] = [
        'version: "0.1"',
        f'publisher: "Composition Fixture: {bundle_name}"',
        "",
        "instructions:",
        '  main: "./instructions/AGENTS.md"',
        "",
    ]

    if with_skills:
        skill_dir = root / "skills" / "code-review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Code review skill\n", encoding="utf-8")
        manifest_lines += [
            "artifacts:",
            "  - type: skills",
            '    path: "./skills/code-review"',
            "",
        ]
    else:
        manifest_lines += ["artifacts: []", ""]

    if with_mcp:
        manifest_lines += [
            "mcp:",
            "  servers:",
            "    - name: postgres",
            "      transport: stdio",
            '      command: "psql"',
            "      args:",
            '        - "--version"',
            "",
        ]

    manifest_path = root / f"{bundle_name}.yaml"
    manifest_path.write_text("\n".join(manifest_lines).strip() + "\n", encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    unittest.main()

