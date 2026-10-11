from __future__ import annotations

from pathlib import Path
import unittest

from runtime.state_store import LOGIC_FILES
from runtime_vnext.methodology import CONTROL_PLANE_FILES, PHASE_FILES


ROOT = Path(__file__).resolve().parents[1]

LEGACY_GUARDRAIL_REFS = {
    "memory/independent-report-no-user-reference.md",
    "memory/precise-numbers-no-fuzzy.md",
    "memory/report-chinese-only-narrative.md",
    "memory/notion-publish-checklist.md",
    "memory/stability-contract.md",
}


def _sop_text() -> str:
    return next((ROOT / "sessions").glob("*SOP.md")).read_text(encoding="utf-8")


def _codex_entry_text() -> str:
    return (ROOT / ".agents" / "skills" / "daily-report" / "SKILL.md").read_text(
        encoding="utf-8"
    )


class CodexClaudeParityTests(unittest.TestCase):
    def test_legacy_branch_carries_committed_guardrail_refs(self):
        sop = _sop_text()
        entry = _codex_entry_text()
        for ref in sorted(LEGACY_GUARDRAIL_REFS):
            with self.subTest(ref=ref):
                self.assertIn(ref, LOGIC_FILES.values())
                self.assertTrue((ROOT / ref).is_file())
                self.assertIn(ref, sop)
                self.assertIn(ref, entry)

    def test_legacy_cleanup_and_completion_contracts_remain_in_both_entries(self):
        sop = _sop_text()
        entry = _codex_entry_text()
        for text in (sop, entry):
            with self.subTest(source=text[:20]):
                for marker in (
                    "cleanup.js",
                    "CLEANUP_KEEP_DAYS",
                    "runtime/report_retention.py",
                    "REPORT_RETENTION_KEEP_DAYS",
                    "session_runner.py deliver",
                    "--skip-retention-cleanup",
                    "retention_cleanup_<slot>.json",
                    "sessions/_*.txt",
                    "收工",
                    "Word-QA",
                    "publish manifest",
                    "context_log.md",
                    "runtime/usage_logger.py",
                    "render_docx",
                    "word_export",
                    "visual_qa",
                    "delivery",
                ):
                    self.assertIn(marker, text)

    def test_codex_does_not_delegate_authority_to_ignored_claude_mirror(self):
        sop = _sop_text()
        entry = _codex_entry_text()
        self.assertNotIn("运行命令以 `.claude/skills/daily-report/SKILL.md", sop)
        self.assertIn(".agents/skills/daily-report/SKILL.md", sop)
        self.assertIn("committed executable authority for legacy Codex runs", entry)
        self.assertIn("Local ignored files never override committed authority", entry)

    def test_vnext_business_manifest_isolated_from_legacy_parity_material(self):
        phase_files = {item for values in PHASE_FILES.values() for item in values}
        self.assertNotIn("sessions/日报SOP.md", phase_files)
        self.assertNotIn(".agents/skills/daily-report/SKILL.md", phase_files)
        self.assertNotIn("AGENTS.md", phase_files)
        self.assertTrue(LEGACY_GUARDRAIL_REFS.isdisjoint(phase_files))

        control_files = set(CONTROL_PLANE_FILES)
        self.assertIn(".agents/skills/daily-report/SKILL.md", control_files)
        self.assertIn("AGENTS.md", control_files)

        entry = _codex_entry_text()
        self.assertIn("## Engine isolation", entry)
        self.assertIn("do not read or transport `sessions/日报SOP.md`", entry)
        self.assertIn("Steps 8–9 are legacy-engine-only", entry)
        self.assertIn("notion_published=false", entry)


if __name__ == "__main__":
    unittest.main()
