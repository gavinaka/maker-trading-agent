from __future__ import annotations

from pathlib import Path
import unittest

from runtime.state_store import LOGIC_FILES


ROOT = Path(__file__).resolve().parents[1]

CLAUDE_CODE_GUARDRAIL_REFS = {
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
    def test_committed_authority_carries_claude_code_guardrail_refs(self):
        sop = _sop_text()
        entry = _codex_entry_text()
        for ref in sorted(CLAUDE_CODE_GUARDRAIL_REFS):
            with self.subTest(ref=ref):
                self.assertIn(ref, LOGIC_FILES.values())
                self.assertTrue((ROOT / ref).is_file())
                self.assertIn(ref, sop)
                self.assertIn(ref, entry)

    def test_cleanup_mechanism_is_part_of_codex_committed_authority(self):
        sop = _sop_text()
        entry = _codex_entry_text()
        for text in (sop, entry):
            with self.subTest(source=text[:20]):
                self.assertIn("cleanup.js", text)
                self.assertIn("CLEANUP_KEEP_DAYS", text)
                self.assertIn("sessions/_*.txt", text)

    def test_codex_does_not_delegate_execution_authority_to_ignored_claude_mirror(self):
        sop = _sop_text()
        entry = _codex_entry_text()
        self.assertNotIn("运行命令以 `.claude/skills/daily-report/SKILL.md", sop)
        self.assertIn(".agents/skills/daily-report/SKILL.md", sop)
        self.assertIn("committed executable authority for Codex runs", entry)
        self.assertIn("compatibility mirror", entry)

    def test_claude_code_completion_trigger_is_committed_for_codex(self):
        sop = _sop_text()
        entry = _codex_entry_text()
        for text in (sop, entry):
            with self.subTest(source=text[:20]):
                self.assertIn("收工", text)
                self.assertIn("Word-QA", text)
                self.assertIn("publish manifest", text)
                self.assertIn("context_log.md", text)
                self.assertIn("session_runner.py deliver", text)
                self.assertIn("sessions/_*.txt", text)
                self.assertIn("runtime/usage_logger.py", text)
                self.assertIn("render_docx", text)
                self.assertIn("word_export", text)
                self.assertIn("visual_qa", text)
                self.assertIn("delivery", text)


if __name__ == "__main__":
    unittest.main()
