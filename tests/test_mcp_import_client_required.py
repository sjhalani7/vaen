"""Tests CLI import requires --client for MCP-enabled bundles."""

from __future__ import annotations

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


class MCPImportClientRequiredTests(unittest.TestCase):
    def test_import_without_client_fails_when_bundle_contains_mcp_servers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_mcp_manifest(root)
            archive_path = root / "mcp-client-required.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=manifest_path, output_path=archive_path)

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = cli_main(["import", str(archive_path), "--into", str(target_repo)])

            self.assertEqual(code, 2)
            self.assertIn(
                "Import requires --client when the bundle contains MCP servers.",
                stderr_buffer.getvalue(),
            )
            self.assertFalse((target_repo / ".agent" / "mcp-client-required").exists())

    def _write_mcp_manifest(self, root: Path) -> Path:
        instructions = root / "instructions"
        instructions.mkdir()
        (instructions / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")

        manifest_path = root / "agent.yaml"
        manifest_path.write_text(
            dedent(
                """
                version: "0.1"
                publisher: "MCP Client Required Fixture"

                instructions:
                  main: "./instructions/AGENTS.md"

                artifacts: []

                mcp:
                  servers:
                    - name: workspace-files
                      transport: stdio
                      command: "npx"
                      args:
                        - "-y"
                        - "@modelcontextprotocol/server-filesystem"
                        - "."
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return manifest_path


if __name__ == "__main__":
    unittest.main()
