"""Tests doctor validation for MCP files declared in bundle metadata."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.doctor import run_doctor


class MCPDoctorCanonicalChecksTests(unittest.TestCase):
    def test_doctor_fails_when_declared_canonical_mcp_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vaen-test-mcp-doctor-") as tmp:
            target_repo = Path(tmp).resolve()
            bundle_dir = _write_minimal_imported_bundle(
                target_repo=target_repo,
                bundle_name="missing-mcp",
            )

            declared_mcp_path = "mcp/servers/postgres.json"

            result = run_doctor(target_repo=target_repo)

            expected_missing_path = bundle_dir / declared_mcp_path
            self.assertFalse(result.passed)
            self.assertIn(
                "bundle:missing-mcp:canonical-mcp-files-exist",
                result.checks_run,
            )
            self.assertEqual(
                result.errors,
                (f"Missing canonical MCP file: {expected_missing_path}",),
            )

    def test_doctor_fails_when_selected_claude_mcp_config_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vaen-test-mcp-doctor-") as tmp:
            target_repo = Path(tmp).resolve()
            bundle_dir = _write_minimal_imported_bundle(
                target_repo=target_repo,
                bundle_name="activated-mcp",
            )
            declared_mcp_path = "mcp/servers/postgres.json"
            canonical_mcp_path = bundle_dir / declared_mcp_path
            canonical_mcp_path.parent.mkdir(parents=True)
            canonical_mcp_path.write_text("{}", encoding="utf-8")

            result = run_doctor(target_repo=target_repo, client="claude")

            expected_config_path = target_repo / ".mcp.json"
            self.assertFalse(result.passed)
            self.assertIn("mcp-client-config-exists:claude", result.checks_run)
            self.assertEqual(
                result.errors,
                (
                    "Missing activated MCP client config file "
                    f"for 'claude': {expected_config_path}",
                ),
            )

    def test_doctor_runs_canonical_mcp_checks_before_selected_client_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vaen-test-mcp-doctor-") as tmp:
            target_repo = Path(tmp).resolve()
            bundle_dir = _write_minimal_imported_bundle(
                target_repo=target_repo,
                bundle_name="ordering",
            )

            result = run_doctor(target_repo=target_repo, client="claude")

            expected_mcp_path = bundle_dir / "mcp" / "servers" / "postgres.json"
            expected_config_path = target_repo / ".mcp.json"
            self.assertFalse(result.passed)
            self.assertEqual(
                result.errors,
                (
                    f"Missing canonical MCP file: {expected_mcp_path}",
                    "Missing activated MCP client config file "
                    f"for 'claude': {expected_config_path}",
                ),
            )
            self.assertLess(
                result.checks_run.index("bundle:ordering:canonical-mcp-files-exist"),
                result.checks_run.index("mcp-client-config-exists:claude"),
            )

    def test_doctor_fails_when_codex_mcp_config_toml_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vaen-test-mcp-doctor-") as tmp:
            target_repo = Path(tmp).resolve()
            bundle_dir = _write_minimal_imported_bundle(
                target_repo=target_repo,
                bundle_name="malformed-codex-config",
            )
            _write_declared_canonical_mcp_file(bundle_dir)
            config_path = target_repo / ".codex" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text("[mcp_servers.postgres\n", encoding="utf-8")

            result = run_doctor(target_repo=target_repo, client="codex")

            self.assertFalse(result.passed)
            self.assertIn("mcp-client-config-toml-syntax:codex", result.checks_run)
            self.assertEqual(
                result.errors,
                (f"Malformed activated Codex MCP config TOML: {config_path}",),
            )

    def test_doctor_fails_when_claude_mcp_config_json_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vaen-test-mcp-doctor-") as tmp:
            target_repo = Path(tmp).resolve()
            bundle_dir = _write_minimal_imported_bundle(
                target_repo=target_repo,
                bundle_name="malformed-claude-config",
            )
            _write_declared_canonical_mcp_file(bundle_dir)
            config_path = target_repo / ".mcp.json"
            config_path.write_text("{", encoding="utf-8")

            result = run_doctor(target_repo=target_repo, client="claude")

            self.assertFalse(result.passed)
            self.assertIn("mcp-client-config-json-syntax:claude", result.checks_run)
            self.assertEqual(
                result.errors,
                (f"Malformed activated Claude MCP config JSON: {config_path}",),
            )


def _write_minimal_imported_bundle(*, target_repo: Path, bundle_name: str) -> Path:
    bundle_dir = target_repo / ".agent" / bundle_name

    (bundle_dir / "vaen").mkdir(parents=True)
    (bundle_dir / "instructions").mkdir()
    (bundle_dir / "skills").mkdir()
    (target_repo / ".agent" / "skills").mkdir(parents=True)
    (target_repo / ".claude" / "skills").mkdir(parents=True)
    (target_repo / "AGENTS.md").write_text("# Agent\n", encoding="utf-8")
    (target_repo / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")

    (bundle_dir / "vaen" / "metadata.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "mcp": {
                        "servers": [
                            {
                                "name": "postgres",
                                "transport": "stdio",
                                "bundlePath": "mcp/servers/postgres.json",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return bundle_dir


def _write_declared_canonical_mcp_file(bundle_dir: Path) -> None:
    canonical_mcp_path = bundle_dir / "mcp" / "servers" / "postgres.json"
    canonical_mcp_path.parent.mkdir(parents=True)
    canonical_mcp_path.write_text("{}", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
