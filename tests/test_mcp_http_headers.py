"""Tests static HTTP header support across manifest parsing, bundling, and renderers."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback.
    import tomli as tomllib  # type: ignore[no-redef]

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.errors import ManifestValidationError
from vaen.importer import prepare_import_plan, render_mcp_config
from vaen.inspect import inspect_agent_archive
from vaen.manifest import load_manifest


class MCPHttpHeadersTests(unittest.TestCase):
    def _write_manifest(self, root: Path, http_block: str) -> Path:
        instructions = root / "instructions"
        instructions.mkdir()
        (instructions / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")

        manifest_path = root / "agent.yaml"
        manifest_path.write_text(
            dedent(
                f"""
                version: "0.1"
                publisher: "HTTP Headers Fixture"

                instructions:
                  main: "./instructions/AGENTS.md"

                artifacts: []

                mcp:
                  servers:
                    - name: figma
                      transport: http
                      url: "https://mcp.figma.com/mcp"
                {http_block}
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def test_manifest_parses_static_http_headers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest_path = self._write_manifest(
                Path(td),
                """
                      http_headers:
                        X-Figma-Region: us-east-1
                      bearer_token_env_var: FIGMA_OAUTH_TOKEN
                      header_env_vars:
                        X-Workspace: WORKSPACE_ID
                """,
            )

            manifest = load_manifest(manifest_path)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            self.assertIsNotNone(manifest.mcp)
            assert manifest.mcp is not None

            server = manifest.mcp.servers[0]
            self.assertEqual(server.transport, "http")
            self.assertEqual(server.http_headers, {"X-Figma-Region": "us-east-1"})
            self.assertEqual(server.bearer_token_env_var, "FIGMA_OAUTH_TOKEN")
            self.assertEqual(server.header_env_vars, {"X-Workspace": "WORKSPACE_ID"})

    def test_duplicate_static_and_env_backed_headers_fail_validation(self) -> None:
        cases = [
            """
                      http_headers:
                        X-Figma-Region: us-east-1
                      header_env_vars:
                        x-figma-region: FIGMA_REGION
            """,
            """
                      http_headers:
                        Authorization: Bearer static-token
                      bearer_token_env_var: FIGMA_OAUTH_TOKEN
            """,
        ]

        for http_block in cases:
            with self.subTest(http_block=http_block):
                with tempfile.TemporaryDirectory() as td:
                    manifest_path = self._write_manifest(Path(td), http_block)

                    with self.assertRaises(ManifestValidationError) as ctx:
                        load_manifest(manifest_path)
                    self.assertIn("conflicts with", str(ctx.exception))

    def test_build_inspect_and_import_plan_preserve_static_http_headers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(
                root,
                """
                      http_headers:
                        X-Figma-Region: us-east-1
                      bearer_token_env_var: FIGMA_OAUTH_TOKEN
                      header_env_vars:
                        X-Workspace: WORKSPACE_ID
                """,
            )
            archive_path = root / "figma.agent"

            build_agent(manifest_path=manifest_path, output_path=archive_path)

            inspected = inspect_agent_archive(archive_path)
            server_metadata = inspected.metadata["manifest"]["mcp"]["servers"][0]
            self.assertEqual(server_metadata["httpHeaders"], {"X-Figma-Region": "us-east-1"})
            self.assertEqual(server_metadata["bearerTokenEnvVar"], "FIGMA_OAUTH_TOKEN")
            self.assertEqual(server_metadata["headerEnvVars"], {"X-Workspace": "WORKSPACE_ID"})
            self.assertEqual(
                server_metadata["requiredVarNames"],
                ["FIGMA_OAUTH_TOKEN", "WORKSPACE_ID"],
            )

            plan = prepare_import_plan(archive_path)
            self.assertEqual(
                plan.mcp_servers[0].definition["httpHeaders"],
                {"X-Figma-Region": "us-east-1"},
            )

    def test_client_renderers_write_static_http_headers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = self._write_manifest(
                root,
                """
                      http_headers:
                        X-Figma-Region: us-east-1
                      bearer_token_env_var: FIGMA_OAUTH_TOKEN
                      header_env_vars:
                        X-Workspace: WORKSPACE_ID
                """,
            )
            archive_path = root / "figma.agent"

            build_agent(manifest_path=manifest_path, output_path=archive_path)
            plan = prepare_import_plan(archive_path)

            codex = tomllib.loads(render_mcp_config(plan, "codex"))
            self.assertEqual(
                codex["mcp_servers"]["figma"],
                {
                    "url": "https://mcp.figma.com/mcp",
                    "bearer_token_env_var": "FIGMA_OAUTH_TOKEN",
                    "http_headers": {"X-Figma-Region": "us-east-1"},
                    "env_http_headers": {"X-Workspace": "WORKSPACE_ID"},
                },
            )
            codex_text = render_mcp_config(plan, "codex")
            self.assertIn(
                'http_headers = { "X-Figma-Region" = "us-east-1" }',
                codex_text,
            )
            self.assertIn(
                'env_http_headers = { "X-Workspace" = "WORKSPACE_ID" }',
                codex_text,
            )
            self.assertNotIn("[mcp_servers.figma.http_headers]", codex_text)
            self.assertNotIn("[mcp_servers.figma.env_http_headers]", codex_text)

            claude = json.loads(render_mcp_config(plan, "claude"))
            self.assertEqual(
                claude["mcpServers"]["figma"]["headers"],
                {
                    "X-Figma-Region": "us-east-1",
                    "Authorization": "Bearer ${FIGMA_OAUTH_TOKEN}",
                    "X-Workspace": "${WORKSPACE_ID}",
                },
            )

            copilot = json.loads(render_mcp_config(plan, "copilot"))
            self.assertEqual(
                copilot["mcpServers"]["figma"]["headers"],
                {
                    "X-Figma-Region": "us-east-1",
                    "Authorization": "Bearer ${FIGMA_OAUTH_TOKEN}",
                    "X-Workspace": "${WORKSPACE_ID}",
                },
            )


if __name__ == "__main__":
    unittest.main()
