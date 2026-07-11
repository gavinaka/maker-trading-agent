from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

AUTHORITY_FILES = (
    ".agents/skills/daily-report/SKILL.md",
    "sessions/日报SOP.md",
    "memory/independent-report-no-user-reference.md",
    "memory/stability-contract.md",
    "agents/emotional_agent.md",
    "agents/risk_agent.md",
    "agents/session_orchestrator.md",
    "execution/session_rules.md",
    "risk/state_gate.md",
)

FORBIDDEN_PRETRADE_REVIEW_COUPLINGS = (
    "门禁/心力硬前置",
    "门禁/心力前置",
    "开仓前门禁 / 心力监控",
    "开仓前门禁/心力监控",
    "供次日早间门禁读取",
    "供次日早间链 A Step1 门禁读取",
    "门禁与心力事实",
)


class DailyGateContractTests(unittest.TestCase):
    def test_committed_authority_uses_one_pretrade_gate(self):
        sop = (ROOT / "sessions" / "日报SOP.md").read_text(encoding="utf-8")
        skill = (
            ROOT / ".agents" / "skills" / "daily-report" / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("唯一事前硬门禁", sop)
        self.assertIn("开仓前状态门禁", sop)
        self.assertIn("exactly one pre-report and pre-trade gate", skill)

    def test_end_of_day_review_cannot_be_a_gate_input(self):
        for relative_path in AUTHORITY_FILES:
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_PRETRADE_REVIEW_COUPLINGS:
                with self.subTest(path=relative_path, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)

        emotional_agent = (ROOT / "agents" / "emotional_agent.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("不得写入、推导或覆盖任何 `state_gate.*` 字段", emotional_agent)
        self.assertIn("不供次日门禁自动读取", emotional_agent)
        self.assertNotIn("自动派生", emotional_agent)
        self.assertNotIn("允许交易但仓位回归标准", emotional_agent)

    def test_missing_gate_requires_confirmation_not_review_substitution(self):
        sop = (ROOT / "sessions" / "日报SOP.md").read_text(encoding="utf-8")
        self.assertIn("硬停并要求人工确认", sop)
        self.assertIn("禁止用其它日志替代门禁", sop)


if __name__ == "__main__":
    unittest.main()
