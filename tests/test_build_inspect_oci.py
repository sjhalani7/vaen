"""Tests building a `.agent` archive and inspecting OCI/readback contents."""

from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.inspect import inspect_agent_archive


class BuildInspectOciTests(unittest.TestCase):
    def test_build_writes_expected_oci_shape(self) -> None:
        fixture_manifest = (
            PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        )

        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "synthetic.agent"
            built = build_agent(manifest_path=fixture_manifest, output_path=archive_path)
            self.assertEqual(built, archive_path)
            self.assertTrue(archive_path.is_file())

            with tarfile.open(archive_path, mode="r") as outer:
                member_names = {member.name for member in outer.getmembers()}
                self.assertIn("oci-layout", member_names)
                self.assertIn("index.json", member_names)
                self.assertTrue(any(name.startswith("blobs/sha256/") for name in member_names))

                index_doc = json.loads(_read_member(outer, "index.json").decode("utf-8"))
                manifest_desc = index_doc["manifests"][0]
                manifest_blob_name = _blob_name(manifest_desc["digest"])
                self.assertIn(manifest_blob_name, member_names)

                manifest_doc = json.loads(
                    _read_member(outer, manifest_blob_name).decode("utf-8")
                )
                config_blob_name = _blob_name(manifest_doc["config"]["digest"])
                layer_blob_name = _blob_name(manifest_doc["layers"][0]["digest"])
                self.assertIn(config_blob_name, member_names)
                self.assertIn(layer_blob_name, member_names)

                layer_blob = _read_member(outer, layer_blob_name)
                with tarfile.open(fileobj=io.BytesIO(layer_blob), mode="r:") as layer:
                    layer_names = {member.name for member in layer.getmembers()}
                    self.assertIn("vaen/metadata.json", layer_names)
                    self.assertIn("instructions/main/AGENTS.md", layer_names)
                    self.assertTrue(
                        any(name.startswith("skills/code-review/") for name in layer_names)
                    )
                    self.assertTrue(
                        any(name.startswith("skills/refactor/") for name in layer_names)
                    )

    def test_inspect_reads_manifest_and_stored_paths(self) -> None:
        fixture_manifest = (
            PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        )

        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "synthetic.agent"
            build_agent(manifest_path=fixture_manifest, output_path=archive_path)

            result = inspect_agent_archive(archive_path)
            self.assertEqual(result.archive_path, archive_path.resolve())
            self.assertEqual(result.metadata["manifest"]["publisher"], "VAEN Synthetic Fixture")
            self.assertEqual(result.metadata["manifest"]["version"], "0.1")
            self.assertEqual(
                result.metadata["manifest"]["requiredVars"],
                ["OPENAI_API_KEY"],
            )
            self.assertIn("instructions/main/AGENTS.md", result.stored_paths)
            self.assertIn("instructions/includes/style.md", result.stored_paths)
            self.assertIn("skills/code-review", result.stored_paths)
            self.assertIn("skills/refactor", result.stored_paths)


def _read_member(tf: tarfile.TarFile, name: str) -> bytes:
    member = tf.getmember(name)
    extracted = tf.extractfile(member)
    if extracted is None:
        raise AssertionError(f"Missing readable tar member: {name}")
    return extracted.read()


def _blob_name(digest: str) -> str:
    algo, value = digest.split(":", 1)
    return f"blobs/{algo}/{value}"


if __name__ == "__main__":
    unittest.main()

