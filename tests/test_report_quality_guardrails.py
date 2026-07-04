from __future__ import annotations

from pathlib import Path
import unittest

from outputs import report_lint


ROOT = Path(__file__).resolve().parents[1]


def _output_lines(name: str) -> list[str]:
    return (ROOT / "outputs" / name).read_text(encoding="utf-8").splitlines()


class ReportQualityGuardrailTests(unittest.TestCase):
    def test_maker_first_defense_layer_must_use_4h_extreme(self):
        lines = """
## ② Maker 计划
BTC（策略）：执行概率55%（已执行0%）　胜率64%
低多：59,600-59,900　持仓500刀　Binance　左侧　盈亏比1:2.5以上
止盈：60,650（TP1）减仓50% ／ 61,300（TP2·清剩余仓位）
止损：59,400
浮盈防守计划：
第一层：价格触及60,275，设59,800这一15分钟级别极点为止损，且取消所有加仓
第二层：价格触及60,650，设立59,750保本损（只移损·不减仓）
""".splitlines()
        hits = report_lint.maker_defense_check(lines)
        self.assertTrue(any("4H" in desc for _, desc, _, _ in hits))
        self.assertTrue(any("1H/15m" in desc for _, desc, _, _ in hits))

    def test_position_coupling_is_not_exempted_by_decoupling_words(self):
        lines = [
            "BTC（策略）：观望·不挂单（Maker账户已有BTC空单成交50%，先补齐风控，禁止新增或补仓；本报告声称解耦）"
        ]
        hits = report_lint.coupling_check(lines)
        self.assertTrue(hits)

    def test_exocharts_current_price_must_fit_declared_daily_ohlc(self):
        lines = [
            "  - 当日未完成K线：开59,689.8、高60,649.9、低58,205.5、收59,977.9；当前图面价格61,437.9。"
        ]
        hits = report_lint.exocharts_ohlc_check(lines)
        self.assertTrue(hits)

    def test_golden_quality_floor_accepts_local_pre_626_benchmarks(self):
        for name in [
            "2026-06-25_morning_combined.md",
            "2026-06-25_midday_combined.md",
            "2026-06-26_morning_combined.md",
            "2026-06-26_midday_combined.md",
        ]:
            with self.subTest(name=name):
                self.assertEqual(report_lint.golden_quality_check(_output_lines(name)), [])

    def test_golden_quality_floor_rejects_post_626_quality_cliff(self):
        for name in [
            "2026-06-27_morning_combined.md",
            "2026-07-03_morning_combined.md",
        ]:
            with self.subTest(name=name):
                hits = report_lint.golden_quality_check(_output_lines(name))
                self.assertTrue(hits)
                self.assertTrue(any("golden-quality" in desc for _, desc, _, _ in hits))


if __name__ == "__main__":
    unittest.main()
