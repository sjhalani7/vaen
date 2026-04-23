"""Tests Claude MCP config output created when importing MCP-enabled bundles."""

from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from textwrap import dedent

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.cli import main as cli_main
from vaen.importer import (
    ensure_mcp_client_target_available,
    extract_canonical_bundle,
    prepare_import_plan,
    write_selected_client_mcp_config,
)


class ClaudeMCPImportOutputTests(unittest.TestCase):
    def _write_mcp_manifest(self, root: Path) -> Path:
        instructions = root / "instructions"
        instructions.mkdir()
        (instructions / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")

        manifest_path = root / "agent.yaml"
        manifest_path.write_text(
            dedent(
                """
                version: "0.1"
                publisher: "Claude MCP Fixture"

                instructions:
                  main: "./instructions/AGENTS.md"

                artifacts: []

                mcp:
                  servers:
                    - name: postgres
                      transport: stdio
                      command: "uvx"
                      args:
                        - "mcp-server-postgres"
                        - "--readonly"
                      cwd: "./workspace"
                      env_vars:
                        - "DB_URL"
                        - "API_KEY"
                    - name: docs-http
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
        return manifest_path

    def test_import_with_claude_client_writes_expected_mcp_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_mcp_manifest(root)
            archive_path = root / "claude-mcp.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=manifest_path, output_path=archive_path)
            plan = prepare_import_plan(archive_path)
            extract_canonical_bundle(
                archive_path=archive_path,
                target_repo=target_repo,
            )
            target_paths = ensure_mcp_client_target_available(
                target_repo=target_repo,
                archive_path=archive_path,
                client="claude",
            )

            written_path = write_selected_client_mcp_config(
                plan,
                target_paths=target_paths,
            )

            expected_path = target_repo / ".mcp.json"
            self.assertEqual(written_path, expected_path.resolve())
            self.assertTrue(expected_path.is_file())

            config = json.loads(expected_path.read_text(encoding="utf-8"))
            servers = config["mcpServers"]
            self.assertEqual(
                servers["postgres"],
                {
                    "command": "uvx",
                    "args": ["mcp-server-postgres", "--readonly"],
                    "cwd": "./workspace",
                    "env": {
                        "DB_URL": "${DB_URL}",
                        "API_KEY": "${API_KEY}",
                    },
                },
            )
            self.assertNotIn("type", servers["postgres"])
            self.assertEqual(
                servers["docs-http"],
                {
                    "type": "http",
                    "url": "https://mcp.example.test",
                    "headers": {
                        "Authorization": "Bearer ${DOCS_TOKEN}",
                        "X-Workspace": "${WORKSPACE_ID}",
                    },
                },
            )

    def test_import_with_claude_client_fails_when_mcp_json_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_mcp_manifest(root)
            archive_path = root / "claude-mcp.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()
            existing_config = target_repo / ".mcp.json"
            existing_config.write_text('{"mcpServers": {}}\n', encoding="utf-8")

            build_agent(manifest_path=manifest_path, output_path=archive_path)

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = cli_main(
                    [
                        "import",
                        str(archive_path),
                        "--into",
                        str(target_repo),
                        "--client",
                        "claude",
                    ]
                )

            stderr = stderr_buffer.getvalue()
            self.assertEqual(code, 2)
            resolved_existing_config = existing_config.resolve()
            resolved_canonical_mcp_root = (
                target_repo.resolve() / ".agent" / "claude-mcp" / "mcp"
            )
            self.assertIn(
                f"MCP client config already exists: {resolved_existing_config}",
                stderr,
            )
            self.assertIn(
                "Refusing to overwrite existing project MCP configuration.",
                stderr,
            )
            self.assertIn(
                "Copy the generated files from the canonical bundle instead: "
                f"{resolved_canonical_mcp_root}",
                stderr,
            )
            self.assertFalse((target_repo / ".agent" / "claude-mcp").exists())
            self.assertEqual(
                existing_config.read_text(encoding="utf-8"),
                '{"mcpServers": {}}\n',
            )


if __name__ == "__main__":
    unittest.main()
