from __future__ import annotations

import unittest
from pathlib import Path

from runtime.automation_memory_guard import AUTOMATION_SCOPES


ROOT = Path(__file__).resolve().parents[1]


class PeriodicReviewContractTests(unittest.TestCase):
    def test_weekly_and_monthly_are_committed_codex_authorities(self):
        for kind in ("weekly", "monthly"):
            path = ROOT / ".agents" / "skills" / f"{kind}-review" / "SKILL.md"
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("periodic_review_contract.md", text)
            self.assertIn("不读取 `.claude/skills` 作为权威", text)
            self.assertNotIn(f".claude/skills/{kind}-review/SKILL.md", text)
            self.assertNotIn("ntn_", text)
            self.assertNotIn("_notion_push_", text)

    def test_periodic_contract_separates_external_accuracy(self):
        text = (ROOT / "governance" / "periodic_review_contract.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("只归外置 `Technical expert`", text)
        self.assertIn("不得自动修改评分、胜率、风控或开单阈值", text)
        self.assertIn("禁止读取 ignored `.claude` 火种", text)
        self.assertIn("Decimal", text)

    def test_active_templates_do_not_embed_stale_balance_or_state_truth(self):
        combined = "\n".join(
            (ROOT / "templates" / name).read_text(encoding="utf-8")
            for name in ("weekly_review.md", "monthly_review.md")
        )
        self.assertNotIn("固定 $1200", combined)
        self.assertNotIn("state/main_account_state.json", combined)
        self.assertNotIn("state/maker_state.json", combined)
        self.assertIn("periodic_review_contract.md", combined)

    def test_memory_guard_covers_periodic_automations(self):
        self.assertIn("weekly", AUTOMATION_SCOPES)
        self.assertIn("monthly", AUTOMATION_SCOPES)


if __name__ == "__main__":
    unittest.main()
