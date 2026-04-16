"""Tests import-target override validation and no-flag default behavior."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ imports work in plain unittest runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaen.build import build_agent
from vaen.doctor import run_doctor
from vaen.errors import BundleImportError
from vaen.importer import (
    create_root_instruction_shims,
    extract_canonical_bundle,
    mirror_imported_skills,
    prepare_import_plan,
    resolve_import_target_overrides,
    validate_import_target_name,
    validate_instruction_filename_stem,
    validate_target_skills_directory_name,
)


class ImportTargetValidationTests(unittest.TestCase):
    def test_validate_import_target_name_accepts_repo_safe_values(self) -> None:
        self.assertEqual(validate_import_target_name("copilot"), "copilot")
        self.assertEqual(validate_import_target_name("agent-2"), "agent-2")

    def test_validate_import_target_name_rejects_unsafe_values(self) -> None:
        with self.assertRaises(BundleImportError):
            validate_import_target_name("Copilot")
        with self.assertRaises(BundleImportError):
            validate_import_target_name("../copilot")
        with self.assertRaises(BundleImportError):
            validate_import_target_name("copilot.md")

    def test_validate_instruction_filename_stem_appends_md(self) -> None:
        self.assertEqual(
            validate_instruction_filename_stem("copilot-instructions"),
            "copilot-instructions.md",
        )

    def test_validate_instruction_filename_stem_rejects_unsafe_values(self) -> None:
        with self.assertRaises(BundleImportError):
            validate_instruction_filename_stem("Copilot")
        with self.assertRaises(BundleImportError):
            validate_instruction_filename_stem("copilot-instructions.md")

    def test_validate_target_skills_directory_name(self) -> None:
        self.assertEqual(
            validate_target_skills_directory_name("copilot"),
            "copilot",
        )
        with self.assertRaises(BundleImportError):
            validate_target_skills_directory_name(".copilot")

    def test_resolve_import_target_overrides_with_no_flags(self) -> None:
        resolved = resolve_import_target_overrides()
        self.assertIsNone(resolved.target_name)
        self.assertIsNone(resolved.instruction_filename)
        self.assertIsNone(resolved.skills_directory_name)

    def test_resolve_import_target_overrides_derives_from_target(self) -> None:
        resolved = resolve_import_target_overrides(target="copilot")
        self.assertEqual(resolved.target_name, "copilot")
        self.assertEqual(resolved.instruction_filename, "COPILOT.md")
        self.assertEqual(resolved.skills_directory_name, "copilot")

    def test_resolve_import_target_overrides_honors_overrides(self) -> None:
        resolved = resolve_import_target_overrides(
            target="copilot",
            target_instructions_file_name="copilot-instructions",
            target_skills_directory="customskills",
        )
        self.assertEqual(resolved.target_name, "copilot")
        self.assertEqual(resolved.instruction_filename, "copilot-instructions.md")
        self.assertEqual(resolved.skills_directory_name, "customskills")

    def test_import_defaults_unchanged_when_no_target_flags(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-import-defaults-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            root_paths = create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=resolve_import_target_overrides(),
            )
            mirror_roots = mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=resolve_import_target_overrides(),
            )

            self.assertEqual(
                root_paths,
                (
                    (target_repo / "AGENTS.md").resolve(),
                    (target_repo / "CLAUDE.md").resolve(),
                ),
            )
            self.assertEqual(
                mirror_roots,
                (
                    (target_repo / ".agent" / "skills").resolve(),
                    (target_repo / ".claude" / "skills").resolve(),
                ),
            )

    def test_doctor_defaults_unchanged_when_no_target_flags(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-doctor-defaults-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=resolve_import_target_overrides(),
            )
            mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=resolve_import_target_overrides(),
            )
            (target_repo / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

            result = run_doctor(target_repo=target_repo)
            self.assertTrue(result.passed)
            self.assertFalse(result.errors)
            self.assertIn("root-instruction-exists:AGENTS.md", result.checks_run)
            self.assertIn("root-instruction-exists:CLAUDE.md", result.checks_run)
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.agent' / 'skills').resolve()}",
                result.checks_run,
            )
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.claude' / 'skills').resolve()}",
                result.checks_run,
            )

    def test_import_derives_activated_paths_from_target_name(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-import-target-derive-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(target="copilot")
            root_paths = create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            mirror_roots = mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )

            self.assertEqual(root_paths, ((target_repo / "COPILOT.md").resolve(),))
            self.assertEqual(mirror_roots, ((target_repo / ".copilot" / "skills").resolve(),))
            self.assertFalse((target_repo / "AGENTS.md").exists())
            self.assertFalse((target_repo / "CLAUDE.md").exists())
            self.assertFalse((target_repo / ".agent" / "skills").exists())
            self.assertFalse((target_repo / ".claude" / "skills").exists())

    def test_doctor_derives_checks_from_target_name(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-doctor-target-derive-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(target="copilot")
            create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            (target_repo / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

            result = run_doctor(target_repo=target_repo, target="copilot")
            self.assertTrue(result.passed)
            self.assertFalse(result.errors)
            self.assertIn("root-instruction-exists:COPILOT.md", result.checks_run)
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.copilot' / 'skills').resolve()}",
                result.checks_run,
            )

    def test_import_honors_target_instructions_filename_partial_override(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-import-instr-partial-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(
                target_instructions_file_name="copilot-instructions",
            )
            root_paths = create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            mirror_roots = mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )

            self.assertEqual(
                root_paths,
                ((target_repo / "copilot-instructions.md").resolve(),),
            )
            self.assertFalse((target_repo / "AGENTS.md").exists())
            self.assertFalse((target_repo / "CLAUDE.md").exists())
            self.assertEqual(
                mirror_roots,
                (
                    (target_repo / ".agent" / "skills").resolve(),
                    (target_repo / ".claude" / "skills").resolve(),
                ),
            )

    def test_doctor_honors_target_instructions_filename_partial_override(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-doctor-instr-partial-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(
                target_instructions_file_name="copilot-instructions",
            )
            create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            (target_repo / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

            result = run_doctor(
                target_repo=target_repo,
                target_instructions_file_name="copilot-instructions",
            )
            self.assertTrue(result.passed)
            self.assertFalse(result.errors)
            self.assertIn(
                "root-instruction-exists:copilot-instructions.md",
                result.checks_run,
            )
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.agent' / 'skills').resolve()}",
                result.checks_run,
            )
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.claude' / 'skills').resolve()}",
                result.checks_run,
            )

    def test_import_honors_target_skills_directory_partial_override(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-import-skills-partial-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(
                target_skills_directory="copilot",
            )
            root_paths = create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            mirror_roots = mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )

            self.assertEqual(
                root_paths,
                (
                    (target_repo / "AGENTS.md").resolve(),
                    (target_repo / "CLAUDE.md").resolve(),
                ),
            )
            self.assertEqual(mirror_roots, ((target_repo / ".copilot" / "skills").resolve(),))

    def test_doctor_honors_target_skills_directory_partial_override(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-doctor-skills-partial-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(
                target_skills_directory="copilot",
            )
            create_root_instruction_shims(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            mirror_imported_skills(
                canonical_destination=canonical,
                plan=plan,
                target_repo=target_repo,
                overrides=overrides,
            )
            (target_repo / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

            result = run_doctor(
                target_repo=target_repo,
                target_skills_directory="copilot",
            )
            self.assertTrue(result.passed)
            self.assertFalse(result.errors)
            self.assertIn("root-instruction-exists:AGENTS.md", result.checks_run)
            self.assertIn("root-instruction-exists:CLAUDE.md", result.checks_run)
            self.assertIn(
                f"mirrored-skills-dir-exists:{(target_repo / '.copilot' / 'skills').resolve()}",
                result.checks_run,
            )

    def test_import_fails_on_custom_root_instruction_filename_conflict(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-import-custom-root-conflict-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(
                target_instructions_file_name="copilot-instructions",
            )
            (target_repo / "copilot-instructions.md").write_text("existing", encoding="utf-8")

            with self.assertRaises(BundleImportError) as ctx:
                create_root_instruction_shims(
                    canonical_destination=canonical,
                    plan=plan,
                    target_repo=target_repo,
                    overrides=overrides,
                )

            self.assertIn("Root instruction shim already exists", str(ctx.exception))

    def test_import_fails_on_custom_mirrored_skills_directory_conflict(self) -> None:
        fixture = PROJECT_ROOT / "examples" / "synthetic-fixture" / "agent.yaml"
        with tempfile.TemporaryDirectory(prefix="vaen-test-import-custom-skills-conflict-") as tmp:
            root = Path(tmp)
            archive = root / "synthetic.agent"
            target_repo = root / "target-repo"
            target_repo.mkdir()

            build_agent(manifest_path=fixture, output_path=archive)
            plan = prepare_import_plan(archive)
            canonical = extract_canonical_bundle(archive_path=archive, target_repo=target_repo)
            overrides = resolve_import_target_overrides(target_skills_directory="copilot")
            (target_repo / ".copilot" / "skills" / "code-review").mkdir(parents=True)

            with self.assertRaises(BundleImportError) as ctx:
                mirror_imported_skills(
                    canonical_destination=canonical,
                    plan=plan,
                    target_repo=target_repo,
                    overrides=overrides,
                )

            self.assertIn("Mirrored skill name already exists", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
