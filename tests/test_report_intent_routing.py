from __future__ import annotations

import unittest
from pathlib import Path

from runtime.intent_router import classify_intent


class ReportIntentRoutingTests(unittest.TestCase):
    def test_session_reports_always_route_to_daily_report(self):
        prompts = [
            "写早报",
            "出早间日报",
            "跑午报",
            "写午间日报",
            "生成晚报",
            "开始晚间日报",
            "写日报",
            "写早报，不要给我其他总结",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_intent(prompt), "daily-report")

    def test_external_summary_language_is_not_a_workflow_in_this_workspace(self):
        self.assertEqual(classify_intent("跑跨仓库总结"), "none")
        self.assertEqual(classify_intent("跨库点评"), "none")

    def test_unrelated_report_language_does_not_guess(self):
        self.assertEqual(classify_intent("今天有哪些更新"), "none")
        self.assertEqual(classify_intent("生成今天的报告"), "none")

    def test_negation_and_meta_discussion_do_not_execute(self):
        prompts = [
            "不要写早报",
            "别跑午报",
            "早报是什么",
            "检查写晚报的路由",
            "解释午报规则",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_intent(prompt), "none")

    def test_codex_workspace_entries_enforce_isolation(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "AGENTS.md",
            ".agents/skills/daily-report/SKILL.md",
        ):
            text = (root / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertTrue(
                    "外部报告" in text
                    or "cross-workflow" in text
                    or "Do not invoke" in text
                    or "禁止调用" in text
                )
                self.assertIn("lease", text.lower())
                self.assertIn("MAX", text)


if __name__ == "__main__":
    unittest.main()
