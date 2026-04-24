"""Regression tests for MCP stdio env_vars list handling across build and import."""

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
from vaen.importer import (
    prepare_import_plan,
    render_mcp_config,
)
from vaen.inspect import inspect_agent_archive


class MCPStdioEnvVarsRegressionTests(unittest.TestCase):
    def _write_manifest(self, root: Path) -> Path:
        instructions = root / "instructions"
        instructions.mkdir()
        (instructions / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")

        manifest_path = root / "agent.yaml"
        manifest_path.write_text(
            dedent(
                """
                version: "0.1"
                publisher: "Regression Fixture"

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
                      cwd: "./workspace"
                      env_vars:
                        - "DB_URL"
                        - "API_KEY"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def test_build_and_import_plan_preserve_stdio_env_var_list_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(root)
            archive_path = root / "postgres.agent"

            build_agent(manifest_path=manifest_path, output_path=archive_path)

            inspected = inspect_agent_archive(archive_path)
            server_metadata = inspected.metadata["manifest"]["mcp"]["servers"][0]
            self.assertEqual(server_metadata["name"], "postgres")
            self.assertEqual(server_metadata["bundlePath"], "mcp/servers/postgres.json")
            self.assertEqual(server_metadata["envVars"], ["DB_URL", "API_KEY"])
            self.assertNotIn(
                {"kind": "mcp.server", "path": "mcp/servers/postgres.json"},
                inspected.metadata["entries"],
            )
            self.assertIn("mcp/servers/postgres.json", inspected.stored_paths)

            plan = prepare_import_plan(archive_path)
            self.assertEqual(len(plan.mcp_servers), 1)
            self.assertEqual(plan.mcp_servers[0].definition["envVars"], ["DB_URL", "API_KEY"])

    def test_client_renderers_treat_stdio_env_vars_as_identity_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(root)
            archive_path = root / "postgres.agent"

            build_agent(manifest_path=manifest_path, output_path=archive_path)
            plan = prepare_import_plan(archive_path)

            codex = render_mcp_config(plan, "codex")
            self.assertIn('env_vars = ["DB_URL", "API_KEY"]', codex)
            self.assertNotIn("[mcp_servers.postgres.env]", codex)

            claude = json.loads(render_mcp_config(plan, "claude"))
            self.assertEqual(
                claude["mcpServers"]["postgres"]["env"],
                {
                    "DB_URL": "${DB_URL}",
                    "API_KEY": "${API_KEY}",
                },
            )

            copilot = json.loads(render_mcp_config(plan, "copilot"))
            self.assertEqual(
                copilot["mcpServers"]["postgres"]["env"],
                {
                    "DB_URL": "${DB_URL}",
                    "API_KEY": "${API_KEY}",
                },
            )
            self.assertEqual(copilot["mcpServers"]["postgres"]["tools"], ["*"])


if __name__ == "__main__":
    unittest.main()
