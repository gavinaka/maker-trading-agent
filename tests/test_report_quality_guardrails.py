from __future__ import annotations

import unittest

from outputs import report_lint


def _golden_quality_sample(*, complete: bool) -> list[str]:
    if not complete:
        return """
# 2026.6.27 早间日报
## ③ 后附
BlockBeats 给出事件，rubric 只写一次，60,000。
""".splitlines()
    return f"""
# 2026.6.25 早间日报
## ③ 后附
BlockBeats Exocharts Coinglass FedWatch TradingView
胜率 rubric 锚点从 60 出发，盘口次因 +2，盘面次因 -1，真实落值 61，高于 60 门槛。
总分 rubric 由 Coinglass CVD/OI、Exocharts Delta、TradingView VRVP/VAH/VAL/POC 和 SMA20 合成。
""".splitlines()


class ReportQualityGuardrailTests(unittest.TestCase):
    def test_tool_wrapper_metadata_is_rejected_before_render(self):
        lines = [
            "# 2026.7.12 早间日报",
            "Exit code: 0",
            "Wall time: 0.3 seconds",
            "Output:",
        ]
        hits = report_lint.tool_wrapper_leak_check(lines)
        self.assertEqual(len(hits), 3)

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

    def test_current_maker_format_is_covered_by_ledger_and_defense_gate(self):
        lines = """
## ② Maker 计划
### BTC（反弹空）：执行概率58%（已执行0%）　胜率64%
策略：62,700-62,760 挂空，持仓800美元，OKX，左侧，盈亏比不低于1:2.5。
入场：62,700-62,760。
止损：63,040。
TP1：61,850，减仓50%。
TP2：60,920，清理剩余50%仓位。
撤单：若未成交前价格先跌破62,120，则取消此策略，不追空。
浮盈防守：成交后以62,700为风险基准。价格下行至62,190后，触发第一层防守，止损下移至成交后新形成并确认的4小时级别K线结构性极点高点，并取消所有加仓。价格触及61,850后，触发第二层防守，止损维持在不高于62,700的保本损，不允许回退第一层保护。
""".splitlines()
        ledger_issues, ledger_skip = report_lint.ledger_check(lines)
        self.assertIsNone(ledger_skip)
        self.assertEqual(ledger_issues, [])
        self.assertEqual(report_lint.maker_defense_check(lines), [])

    def test_maker_position_ledger_rejects_70_30_drift(self):
        lines = """
## ② Maker 计划
止盈：64,750（TP1）减仓70%；65,200（TP2）处理剩余30%仓位。
""".splitlines()
        issues, skip = report_lint.ledger_check(lines)
        self.assertIsNone(skip)
        self.assertTrue(any("TP1 必须减仓50%" in desc for desc, _ in issues))
        self.assertTrue(any("TP2 必须显式清剩余50%" in desc for desc, _ in issues))

    def test_first_defense_layer_must_not_prefill_future_4h_extreme_price(self):
        lines = """
## ② Maker 计划
### BTC（反弹空）：执行概率58%（已执行0%）　胜率64%
TP1：61,850，减仓50%。
TP2：60,920，清理剩余仓位。
浮盈防守：价格下行至62,190后，触发第一层防守，止损下移至4小时级别K线极点高点62,674.47，并取消所有加仓。价格触及61,850后，触发第二层防守，止损维持保本损。
""".splitlines()
        hits = report_lint.maker_defense_check(lines)
        self.assertTrue(any("预填" in desc for _, desc, _, _ in hits))
        self.assertTrue(any("后续形成" in desc for _, desc, _, _ in hits))

    def test_inline_defense_layer_bad_timeframe_is_rejected(self):
        lines = """
## ② Maker 计划
### BTC（反弹空）：执行概率58%（已执行0%）　胜率64%
TP1：61,850，减仓50%。
TP2：60,920，清理剩余仓位。
浮盈防守：价格下行至62,190后，触发第一层防守，止损下移至15分钟级别K线极点高点62,674.47。价格触及61,850后，触发第二层防守，止损维持保本损。
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

    def test_golden_quality_accepts_semantically_complete_compact_sample(self):
        self.assertEqual(report_lint.golden_quality_check(_golden_quality_sample(complete=True)), [])

    def test_golden_quality_rejects_missing_sources_and_rubric(self):
        hits = report_lint.golden_quality_check(_golden_quality_sample(complete=False))
        self.assertTrue(hits)
        self.assertTrue(any("golden-quality" in desc for _, desc, _, _ in hits))

    def test_strict_reasoning_trace_gate_exempts_only_20260706_morning(self):
        thin_0706 = """
# 2026.7.6 早间日报
## ③ 后附
胜率 58。
""".splitlines()
        self.assertEqual(
            report_lint.strict_reasoning_trace_check(
                thin_0706,
                "outputs/2026-07-06_morning_combined.md",
            ),
            [],
        )

        thin_0706_midday = """
# 2026.7.6 午间日报
## ③ 后附
胜率 58。
""".splitlines()
        midday_hits = report_lint.strict_reasoning_trace_check(
            thin_0706_midday,
            "outputs/2026-07-06_midday_combined.md",
        )
        self.assertTrue(midday_hits)

        no_title_date_hits = report_lint.strict_reasoning_trace_check(
            ["## ③ 后附", "胜率 58。"],
            "outputs/2026-07-06_evening_combined.md",
        )
        self.assertTrue(no_title_date_hits)

        thin_0707 = """
# 2026.7.7 早间日报
## ③ 后附
胜率 58。
""".splitlines()
        hits = report_lint.strict_reasoning_trace_check(thin_0707)
        self.assertTrue(hits)
        self.assertTrue(any("胜率" in desc for _, desc, _, _ in hits))

    def test_strict_reasoning_trace_accepts_explicit_chains(self):
        lines = """
# 2026.7.7 早间日报
## ③ 后附
评分明细：盘口 45、盘面 18，总分 63；合成来自 Coinglass 的 CVD/OI/资金费率、Exocharts Delta 与 TradingView 的 VRVP/VAH/VAL/POC，分项落值后再推导总分。
胜率 rubric 锚=60 → 次因 -2 → 落值 58 → 比 60 门槛不达标，因此不把临界胜率倒推到可开单。
方向主判：CVD 与 OI 给出空头占优，SMA20 与 pivot 摆动结构确认未破；最强反证是价格重新站回 VAH，失效路径是放量上破后情景改为观望。
""".splitlines()
        self.assertEqual(report_lint.strict_reasoning_trace_check(lines), [])

    def test_v3_semantics_rejects_representative_entry_and_ambiguous_range(self):
        lines = """
# 2026.7.12 午间日报
总分：71　胜率自估：66%
策略：入场区间63,100-63,400，以63,250为代表入场。
风险验算：代表入场63,250计算达到1:2.5。
""".splitlines()
        hits = report_lint.v3_semantics_check(
            lines, "outputs/2026-07-12_midday_combined.md"
        )
        self.assertTrue(any("代表价" in desc for _, desc, _, _ in hits))
        self.assertTrue(any("订单语义" in desc for _, desc, _, _ in hits))
        self.assertTrue(any("置信度" in desc for _, desc, _, _ in hits))

    def test_v3_semantics_accepts_canonical_ladder_language(self):
        lines = """
# 2026.7.12 午间日报
盘口：50/70　盘面：21/30　总分：71　胜率自估（计划时置信度，非回测命中率）：66%
分档入场：63,100占50%，63,300占50%。
风险验算：ladder订单共3种非空成交情景，最差TP1盈亏比1:2.5，最高5倍杠杆名义风险3%；全部情景均达到1:2.5且不高于3%。
""".splitlines()
        self.assertEqual(
            report_lint.v3_semantics_check(
                lines, "outputs/2026-07-12_midday_combined.md"
            ),
            [],
        )

    def test_v3_report_cannot_self_attest_max_host_reasoning(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "MAX reasoning confirmed by the report author",
            "无可执行 Maker 计划",
        ]
        hits = report_lint.v3_semantics_check(
            lines, "outputs/2026-07-12_midday_combined.md"
        )
        self.assertTrue(any("MAX" in hit[2] for hit in hits))


if __name__ == "__main__":
    unittest.main()
