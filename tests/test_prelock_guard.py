from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.prelock_guard import (
    activate_prelock_guard,
    assert_no_active_prelock_guard,
    prelock_guard_targets,
    restore_all_active_prelock_guards,
    restore_prelock_guard,
    sha256_file,
)
from runtime.prelock_read_policy import (
    PrelockReadViolation,
    assert_prelock_read_allowed,
    classify_prelock_read,
    prelock_policy_manifest,
    prelock_rg_exclude_args,
)


class PrelockGuardTests(unittest.TestCase):
    def _seed(self, root: Path) -> dict[str, Path]:
        runtime = root / "runtime_state" / "2026-07-06"
        outputs = root / "outputs"
        sessions = root / "sessions"
        runtime.mkdir(parents=True)
        outputs.mkdir()
        sessions.mkdir()
        files = {
            "context": sessions / "context_log.md",
            "analysis": runtime / "analysis_midday.json",
            "decision": runtime / "decision_midday.json",
            "combined": outputs / "2026-07-06_midday_combined.md",
            "payload": outputs / "2026-07-06_midday_publish_payload.json",
            "render": outputs / "2026-07-06_midday_render.docx",
        }
        files["context"].write_text("midday judgment in ledger\n", encoding="utf-8")
        files["analysis"].write_text(
            json.dumps({"score": 67}), encoding="utf-8"
        )
        files["decision"].write_text(
            json.dumps({"maker": "prior short"}), encoding="utf-8"
        )
        files["combined"].write_text("prior report judgment\n", encoding="utf-8")
        files["payload"].write_text(
            json.dumps({"children": ["prior report"]}), encoding="utf-8"
        )
        files["render"].write_bytes(b"prior docx")
        return files

    def test_guard_hides_prior_judgment_files_until_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self._seed(root)
            before = {name: sha256_file(path) for name, path in files.items()}

            targets = {
                path.relative_to(root).as_posix()
                for path in prelock_guard_targets("2026-07-06", "evening", root=root)
            }
            self.assertIn("runtime_state/2026-07-06/decision_midday.json", targets)
            self.assertIn("sessions/context_log.md", targets)

            payload, manifest = activate_prelock_guard(
                "2026-07-06", "evening", root=root
            )
            self.assertEqual(payload["status"], "active")
            self.assertEqual(len(payload["entries"]), len(files))
            for path in files.values():
                self.assertFalse(path.exists())
            with self.assertRaisesRegex(RuntimeError, "pre-lock guard is still active"):
                assert_no_active_prelock_guard("2026-07-06", "evening", root=root)

            restored, _ = restore_prelock_guard(
                "2026-07-06", "evening", root=root, reason="test"
            )
            self.assertEqual(restored["status"], "restored")
            self.assertTrue(manifest.exists())
            for name, path in files.items():
                self.assertTrue(path.exists(), name)
                self.assertEqual(sha256_file(path), before[name])
            assert_no_active_prelock_guard("2026-07-06", "evening", root=root)

    def test_recovery_restores_all_active_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self._seed(root)
            activate_prelock_guard("2026-07-06", "evening", root=root)
            for path in files.values():
                self.assertFalse(path.exists())

            restored = restore_all_active_prelock_guards(root=root, reason="test")
            self.assertEqual(len(restored), 1)
            for path in files.values():
                self.assertTrue(path.exists())

    def test_guard_hides_broad_prior_surfaces_but_keeps_current_slot_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = [
                root / "sessions" / "archive" / "old_context.md",
                root / "reviews" / "daily_review_structure.md",
                root / "outputs" / "2026-07-05_morning_combined.md",
                root / "runtime_state" / "2026-07-05" / "context_morning.json",
                root / "runtime_state" / "2026-07-05" / "base.json",
                root / "memory" / "MEMORY.md",
            ]
            generated_cache = root / "outputs" / "__pycache__" / "report_structure_gate.cpython-314.pyc"
            current_allowed = [
                root / "runtime_state" / "2026-07-07" / "context_morning.json",
                root / "runtime_state" / "2026-07-07" / "transition_morning.json",
                root
                / "runtime_state"
                / "2026-07-07"
                / "captures"
                / "morning"
                / "full_base_run.json",
                root
                / "runtime_state"
                / "2026-07-07"
                / "evidence"
                / "morning"
                / "run"
                / "blockbeats.json",
            ]
            for path in prior + current_allowed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("payload\n", encoding="utf-8")
            generated_cache.parent.mkdir(parents=True, exist_ok=True)
            generated_cache.write_bytes(b"compiled cache")

            targets = {
                path.relative_to(root).as_posix()
                for path in prelock_guard_targets("2026-07-07", "morning", root=root)
            }
            for path in prior:
                self.assertIn(path.relative_to(root).as_posix(), targets)
            for path in current_allowed:
                self.assertNotIn(path.relative_to(root).as_posix(), targets)
            self.assertNotIn(generated_cache.relative_to(root).as_posix(), targets)

            activate_prelock_guard("2026-07-07", "morning", root=root)
            for path in prior:
                self.assertFalse(path.exists(), path)
            for path in current_allowed:
                self.assertTrue(path.exists(), path)
            self.assertTrue(generated_cache.exists())

            restore_prelock_guard("2026-07-07", "morning", root=root)
            for path in prior + current_allowed:
                self.assertTrue(path.exists(), path)

    def test_certified_recovery_preserves_only_current_slot_recovery_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = [
                root / "runtime_state" / "2026-07-07" / "decision_input_midday.json",
                root / "runtime_state" / "2026-07-07" / "decision_contract_midday.json",
                root / "outputs" / "2026-07-07_midday_cards.json",
                root / "outputs" / "2026-07-07_midday_combined.md",
                root / "outputs" / "blockbeats" / "2026-07-07_midday_01.png",
            ]
            still_quarantined = [
                root / "runtime_state" / "2026-07-07" / "decision_contract_morning.json",
                root / "runtime_state" / "2026-07-06" / "decision_contract_evening.json",
                root / "outputs" / "2026-07-07_midday_render.docx",
                root / "outputs" / "2026-07-07_morning_combined.md",
            ]
            for path in current + still_quarantined:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("payload\n", encoding="utf-8")

            ordinary_targets = {
                path.relative_to(root).as_posix()
                for path in prelock_guard_targets("2026-07-07", "midday", root=root)
            }
            for path in current:
                self.assertIn(path.relative_to(root).as_posix(), ordinary_targets)

            payload, _ = activate_prelock_guard(
                "2026-07-07",
                "midday",
                root=root,
                preserve_certified_recovery_artifacts=True,
                preserve_certified_draft_artifacts=True,
            )
            self.assertTrue(payload["certified_recovery_artifacts_preserved"])
            self.assertTrue(payload["certified_draft_artifacts_preserved"])
            for path in current:
                self.assertTrue(path.exists(), path)
            for path in still_quarantined:
                self.assertFalse(path.exists(), path)

    def test_recovery_quarantines_stale_reasoning_boundary_and_supersedes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state" / "2026-07-07"
            readiness = state / "reasoning_readiness_midday.json"
            lock = state / "reasoning_lock_midday.json"
            for path in (readiness, lock):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("old\n", encoding="utf-8")

            payload, _ = activate_prelock_guard(
                "2026-07-07",
                "midday",
                root=root,
                preserve_certified_recovery_artifacts=True,
            )
            quarantined = {entry["original_path"] for entry in payload["entries"]}
            self.assertIn(
                "runtime_state/2026-07-07/reasoning_readiness_midday.json",
                quarantined,
            )
            self.assertIn(
                "runtime_state/2026-07-07/reasoning_lock_midday.json",
                quarantined,
            )

            readiness.write_text("new readiness\n", encoding="utf-8")
            lock.write_text("new lock\n", encoding="utf-8")
            restored, _ = restore_prelock_guard(
                "2026-07-07",
                "midday",
                root=root,
                reason="reasoning_lock_success",
            )

            self.assertEqual(readiness.read_text(encoding="utf-8"), "new readiness\n")
            self.assertEqual(lock.read_text(encoding="utf-8"), "new lock\n")
            self.assertIn(
                "runtime_state/2026-07-07/reasoning_readiness_midday.json",
                restored["superseded_current_outputs"],
            )
            self.assertIn(
                "runtime_state/2026-07-07/reasoning_lock_midday.json",
                restored["superseded_current_outputs"],
            )

    def test_logic_replacement_abandon_does_not_resurrect_stale_generated_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = root / "runtime_state" / "2026-07-07" / "reasoning_contract_morning.json"
            stale_work = root / "runtime_state" / "2026-07-07" / "reasoning_work_morning.md"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("old reasoning\n", encoding="utf-8")
            stale_work.write_text("old reasoning work\n", encoding="utf-8")

            payload, _ = activate_prelock_guard(
                "2026-07-07",
                "morning",
                root=root,
                discard_stale_generated_on_abandon=True,
            )
            self.assertFalse(stale.exists())
            self.assertFalse(stale_work.exists())
            self.assertTrue(payload["discard_stale_generated_on_abandon"])

            restored, _ = restore_prelock_guard(
                "2026-07-07", "morning", root=root, reason="abandon-session"
            )
            self.assertFalse(stale.exists())
            self.assertFalse(stale_work.exists())
            self.assertIn(
                "runtime_state/2026-07-07/reasoning_contract_morning.json",
                restored["superseded_current_outputs"],
            )
            self.assertIn(
                "runtime_state/2026-07-07/reasoning_work_morning.md",
                restored["superseded_current_outputs"],
            )

    def test_restore_tolerates_regenerated_python_cache_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "outputs" / "__pycache__" / "report_structure_gate.cpython-314.pyc"
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(b"old cache")

            payload, _ = activate_prelock_guard("2026-07-07", "morning", root=root)
            self.assertEqual(len(payload["entries"]), 0)

            quarantine = (
                root
                / "runtime_state"
                / "2026-07-07"
                / ".prelock_quarantine"
                / "morning"
                / "manual_cache"
            )
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            quarantine.write_bytes(b"old cache")
            manifest = root / "runtime_state" / "2026-07-07" / "prelock_guard_morning.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "active",
                        "trading_date": "2026-07-07",
                        "slot": "morning",
                        "entries": [
                            {
                                "original_path": cache.relative_to(root).as_posix(),
                                "quarantine_path": quarantine.relative_to(root).as_posix(),
                                "sha256": sha256_file(quarantine),
                                "bytes": quarantine.stat().st_size,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cache.write_bytes(b"regenerated cache")

            restored, _ = restore_prelock_guard("2026-07-07", "morning", root=root)
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(cache.read_bytes(), b"old cache")

    def test_restore_is_idempotent_after_partial_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self._seed(root)
            payload, _ = activate_prelock_guard("2026-07-06", "evening", root=root)
            first_entry = payload["entries"][0]
            original = root / first_entry["original_path"]
            quarantine = root / first_entry["quarantine_path"]
            quarantine.replace(original)

            restored, _ = restore_prelock_guard("2026-07-06", "evening", root=root)
            self.assertEqual(restored["status"], "restored")
            for path in files.values():
                self.assertTrue(path.exists(), path)

    def test_analysis_lock_restore_discards_superseded_current_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "outputs" / "2026-07-07_morning_combined.md"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("old report\n", encoding="utf-8")

            payload, _ = activate_prelock_guard("2026-07-07", "morning", root=root)
            self.assertTrue(
                any(
                    entry["original_path"] == "outputs/2026-07-07_morning_combined.md"
                    for entry in payload["entries"]
                )
            )
            self.assertFalse(report.exists())
            report.write_text("new locked report\n", encoding="utf-8")

            restored, _ = restore_prelock_guard(
                "2026-07-07",
                "morning",
                root=root,
                reason="analysis_lock_success",
            )
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(report.read_text(encoding="utf-8"), "new locked report\n")
            self.assertIn(
                "outputs/2026-07-07_morning_combined.md",
                restored["superseded_current_outputs"],
            )

    def test_analysis_lock_restore_discards_stale_current_payload_and_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cards = root / "outputs" / "2026-07-07_morning_cards.json"
            payload_file = root / "outputs" / "2026-07-07_morning_publish_payload.json"
            render = root / "outputs" / "2026-07-07_morning_render.docx"
            for path, content in (
                (cards, "old cards\n"),
                (payload_file, "old payload\n"),
                (render, "old render\n"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            activate_prelock_guard("2026-07-07", "morning", root=root)
            restored, _ = restore_prelock_guard(
                "2026-07-07",
                "morning",
                root=root,
                reason="analysis_lock_success",
            )

            self.assertEqual(restored["status"], "restored")
            self.assertFalse(cards.exists())
            self.assertFalse(payload_file.exists())
            self.assertFalse(render.exists())
            self.assertEqual(
                sorted(restored["superseded_current_outputs"]),
                [
                    "outputs/2026-07-07_morning_cards.json",
                    "outputs/2026-07-07_morning_publish_payload.json",
                    "outputs/2026-07-07_morning_render.docx",
                ],
            )

    def test_analysis_lock_restore_discards_stale_current_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state" / "2026-07-07"
            stale_files = [
                state / "analysis_lock_morning.json",
                state / "analysis_morning.json",
                state / "decision_morning.json",
                state / "base.json",
                state / "current.json",
                state / "render_morning.json",
                state / "word_qa_morning.json",
            ]
            for path in stale_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"old {path.name}\n", encoding="utf-8")

            activate_prelock_guard("2026-07-07", "morning", root=root)
            new_lock = state / "analysis_lock_morning.json"
            new_lock.write_text("new lock\n", encoding="utf-8")

            restored, _ = restore_prelock_guard(
                "2026-07-07",
                "morning",
                root=root,
                reason="analysis_lock_success",
            )

            self.assertEqual(restored["status"], "restored")
            self.assertEqual(new_lock.read_text(encoding="utf-8"), "new lock\n")
            for path in stale_files[1:]:
                self.assertFalse(path.exists(), path)
            self.assertIn(
                "runtime_state/2026-07-07/analysis_lock_morning.json",
                restored["superseded_current_outputs"],
            )

    def test_analysis_lock_restore_is_idempotent_after_superseded_discard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "outputs" / "2026-07-07_morning_combined.md"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("old report\n", encoding="utf-8")

            payload, _ = activate_prelock_guard("2026-07-07", "morning", root=root)
            entry = next(
                item
                for item in payload["entries"]
                if item["original_path"] == "outputs/2026-07-07_morning_combined.md"
            )
            (root / entry["quarantine_path"]).unlink()
            report.write_text("new locked report\n", encoding="utf-8")

            restored, _ = restore_prelock_guard(
                "2026-07-07",
                "morning",
                root=root,
                reason="analysis_lock_success",
            )

            self.assertEqual(restored["status"], "restored")
            self.assertEqual(report.read_text(encoding="utf-8"), "new locked report\n")
            self.assertIn(
                "outputs/2026-07-07_morning_combined.md",
                restored["superseded_current_outputs"],
            )

    def test_analysis_lock_restore_preserves_new_certified_recovery_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            date = "2026-07-07"
            slot = "morning"
            paths = [
                root / "runtime_state" / date / f"decision_input_{slot}.json",
                root / "runtime_state" / date / f"decision_contract_{slot}.json",
                root / "outputs" / f"{date}_{slot}_cards.json",
                root / "outputs" / f"{date}_{slot}_combined.md",
                *[
                    root / "outputs" / "blockbeats" / f"{date}_{slot}_{index}.png"
                    for index in range(3)
                ],
            ]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"old {path.name}\n", encoding="utf-8")

            activate_prelock_guard(date, slot, root=root)
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"new {path.name}\n", encoding="utf-8")

            restored, _ = restore_prelock_guard(
                date,
                slot,
                root=root,
                reason="analysis_lock_success",
            )

            self.assertEqual(restored["status"], "restored")
            for path in paths:
                self.assertEqual(
                    path.read_text(encoding="utf-8"),
                    f"new {path.name}\n",
                )
                self.assertIn(
                    path.relative_to(root).as_posix(),
                    restored["superseded_current_outputs"],
                )

    def test_prelock_safe_read_blocks_prior_judgment_surfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            forbidden = [
                root / "sessions" / "context_log.md",
                root / "sessions" / "archive" / "context_log_old.md",
                root / "outputs" / "2026-07-05_morning_combined.md",
                root / "runtime_state" / "2026-07-05" / "base.json",
                root
                / "runtime_state"
                / "2026-07-07"
                / ".prelock_quarantine"
                / "morning"
                / "old.md",
                root / "reviews" / "2026-07-05.md",
                root / "memory" / "MEMORY.md",
            ]
            for path in forbidden:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("prior judgment\n", encoding="utf-8")

            for path in forbidden:
                with self.subTest(path=path):
                    result = classify_prelock_read(
                        path,
                        trading_date="2026-07-07",
                        slot="morning",
                        root=root,
                    )
                    self.assertFalse(result["allowed"])
                    with self.assertRaises(PrelockReadViolation):
                        assert_prelock_read_allowed(
                            path,
                            trading_date="2026-07-07",
                            slot="morning",
                            root=root,
                        )

    def test_prelock_safe_read_allows_authority_and_current_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = [
                root / ".agents" / "skills" / "daily-report" / "SKILL.md",
                root / "sessions" / "日报SOP.md",
                root / "risk" / "state_gate.md",
                root / "agents" / "emotional_agent.md",
                root
                / "runtime_state"
                / "2026-07-07"
                / "context_morning.json",
                root
                / "runtime_state"
                / "2026-07-07"
                / "transition_morning.json",
                root
                / "runtime_state"
                / "2026-07-07"
                / "captures"
                / "morning"
                / "full_base_abc.json",
                root
                / "runtime_state"
                / "2026-07-07"
                / "evidence"
                / "morning"
                / "run"
                / "blockbeats.json",
                root / "outputs" / "2026-07-07_morning_combined.md",
            ]
            for path in allowed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("current authority or evidence\n", encoding="utf-8")

            for path in allowed:
                with self.subTest(path=path):
                    self.assertEqual(
                        assert_prelock_read_allowed(
                            path,
                            trading_date="2026-07-07",
                            slot="morning",
                            root=root,
                        ),
                        path.relative_to(root).as_posix(),
                    )

    def test_prelock_policy_manifest_contains_safe_search_denylists(self):
        manifest = prelock_policy_manifest("2026-07-07", "morning")
        self.assertIn("sessions/archive/**", manifest["forbidden_prior_judgment_paths"])
        self.assertIn("runtime_state/**", manifest["safe_rg_excludes"])
        self.assertIn("reviews/**", manifest["safe_rg_excludes"])
        self.assertIn("-g", prelock_rg_exclude_args())


if __name__ == "__main__":
    unittest.main()
