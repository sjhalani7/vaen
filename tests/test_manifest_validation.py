"""Tests manifest validation failures and path normalization behavior."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from textwrap import dedent

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


class ManifestMCPValidationTests(unittest.TestCase):
    def test_invalid_inline_mcp_transport_values_fail_validation(self) -> None:
        for transport in ("sse", "websocket"):
            with self.subTest(transport=transport):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    (root / "instructions").mkdir()
                    (root / "instructions" / "AGENTS.md").write_text(
                        "hello",
                        encoding="utf-8",
                    )

                    manifest = root / "agent.yaml"
                    manifest.write_text(
                        dedent(
                            f"""
                            version: "0.1"
                            publisher: "Example"
                            instructions:
                              main: "./instructions/AGENTS.md"
                            artifacts: []
                            mcp:
                              servers:
                                - name: legacy
                                  transport: {transport}
                            """
                        ).strip()
                        + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaises(ManifestValidationError) as ctx:
                        load_manifest(manifest)
                    self.assertIn(
                        "mcp.servers[0].transport must be one of: ['http', 'stdio']",
                        str(ctx.exception),
                    )

    def test_stdio_mcp_server_requires_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                dedent(
                    """
                    version: "0.1"
                    publisher: "Example"
                    instructions:
                      main: "./instructions/AGENTS.md"
                    artifacts: []
                    mcp:
                      servers:
                        - name: filesystem
                          transport: stdio
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(manifest)
            self.assertIn(
                "mcp.servers[0].command must be a non-empty string",
                str(ctx.exception),
            )

    def test_http_mcp_server_requires_url(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                dedent(
                    """
                    version: "0.1"
                    publisher: "Example"
                    instructions:
                      main: "./instructions/AGENTS.md"
                    artifacts: []
                    mcp:
                      servers:
                        - name: docs
                          transport: http
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError) as ctx:
                load_manifest(manifest)
            self.assertIn(
                "mcp.servers[0].url must be a non-empty string",
                str(ctx.exception),
            )

    def test_stdio_mcp_env_vars_must_be_list_of_strings(self) -> None:
        cases = [
            (
                'env_vars: {"DB_URL": "DATABASE_URL"}',
                "mcp.servers[0].env_vars must be a list of strings",
            ),
            (
                "env_vars: [123]",
                "mcp.servers[0].env_vars[0] must be a non-empty string",
            ),
        ]

        for env_vars_yaml, expected_error in cases:
            with self.subTest(env_vars_yaml=env_vars_yaml):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    (root / "instructions").mkdir()
                    (root / "instructions" / "AGENTS.md").write_text(
                        "hello",
                        encoding="utf-8",
                    )

                    manifest = root / "agent.yaml"
                    manifest.write_text(
                        dedent(
                            f"""
                            version: "0.1"
                            publisher: "Example"
                            instructions:
                              main: "./instructions/AGENTS.md"
                            artifacts: []
                            mcp:
                              servers:
                                - name: postgres
                                  transport: stdio
                                  command: "uvx"
                                  {env_vars_yaml}
                            """
                        ).strip()
                        + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaises(ManifestValidationError) as ctx:
                        load_manifest(manifest)
                    self.assertIn(expected_error, str(ctx.exception))

    def test_http_mcp_header_env_vars_must_be_string_mapping(self) -> None:
        cases = [
            (
                'header_env_vars: ["X-Workspace"]',
                "mcp.servers[0].header_env_vars must be a mapping of strings",
            ),
            (
                "header_env_vars: {X-Workspace: 123}",
                "mcp.servers[0].header_env_vars.X-Workspace must be a non-empty string",
            ),
        ]

        for header_env_vars_yaml, expected_error in cases:
            with self.subTest(header_env_vars_yaml=header_env_vars_yaml):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    (root / "instructions").mkdir()
                    (root / "instructions" / "AGENTS.md").write_text(
                        "hello",
                        encoding="utf-8",
                    )

                    manifest = root / "agent.yaml"
                    manifest.write_text(
                        dedent(
                            f"""
                            version: "0.1"
                            publisher: "Example"
                            instructions:
                              main: "./instructions/AGENTS.md"
                            artifacts: []
                            mcp:
                              servers:
                                - name: docs
                                  transport: http
                                  url: "https://mcp.example.test"
                                  {header_env_vars_yaml}
                            """
                        ).strip()
                        + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaises(ManifestValidationError) as ctx:
                        load_manifest(manifest)
                    self.assertIn(expected_error, str(ctx.exception))

    def test_valid_inline_mcp_schema_parses_supported_server_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "instructions").mkdir()
            (root / "instructions" / "AGENTS.md").write_text("hello", encoding="utf-8")

            manifest = root / "agent.yaml"
            manifest.write_text(
                dedent(
                    """
                    version: "0.1"
                    publisher: "Example"
                    instructions:
                      main: "./instructions/AGENTS.md"
                    artifacts: []
                    mcp:
                      servers:
                        - name: postgres
                          transport: stdio
                          command: "uvx"
                          args: ["mcp-server-postgres"]
                          cwd: "./workspace"
                          env_vars: ["DB_URL"]
                        - name: docs
                          transport: http
                          url: "https://mcp.example.test"
                          bearer_token_env_var: "DOCS_TOKEN"
                          header_env_vars:
                            X-Workspace: "WORKSPACE_ID"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            doc = load_manifest(manifest)
            self.assertIsNotNone(doc)
            assert doc is not None
            self.assertIsNotNone(doc.mcp)
            assert doc.mcp is not None
            self.assertEqual(len(doc.mcp.servers), 2)

            stdio, http = doc.mcp.servers
            self.assertEqual(stdio.transport, "stdio")
            self.assertEqual(stdio.command, "uvx")
            self.assertEqual(stdio.args, ("mcp-server-postgres",))
            self.assertEqual(stdio.env_vars, ("DB_URL",))
            self.assertEqual(http.transport, "http")
            self.assertEqual(http.url, "https://mcp.example.test")
            self.assertEqual(http.bearer_token_env_var, "DOCS_TOKEN")
            self.assertEqual(http.header_env_vars, {"X-Workspace": "WORKSPACE_ID"})


if __name__ == "__main__":
    unittest.main()
