from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from outputs import report_lint


ROOT = Path(__file__).resolve().parents[1]


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
总分 rubric 由 Coinglass CVD/OI、Exocharts Delta、TradingView 多周期结构、用户手绘价值区和 SMA20 合成。
""".splitlines()


class ReportQualityGuardrailTests(unittest.TestCase):
    @staticmethod
    def strict_timeframe_pattern():
        return report_lint.load_timeframe_display_pattern(
            ROOT / "governance" / "vnext_report_presentation_contract.json"
        )

    def test_vnext_liquidity_timeframe_matrix_accepts_only_canonical_labels(self):
        pattern = self.strict_timeframe_pattern()
        for label in ("1D", "4H", "1H", "15m", "3天", "48H", "24H"):
            with self.subTest(label=label):
                self.assertEqual(
                    report_lint.liquidity_check(
                        [f"流动性认证区间=61500-64400({label})"],
                        period_pattern=pattern,
                    ),
                    [],
                )

        for stale in (
            "1d",
            "4h",
            "1h",
            "15M",
            "3d",
            "48h",
            "24h",
            "日线",
            "周线",
            "周期",
            "小时级别",
            "日内",
            "2H",
            "11D",
            "未认证",
        ):
            with self.subTest(stale=stale):
                self.assertTrue(
                    report_lint.liquidity_check(
                        [f"流动性认证区间=61500-64400({stale})"],
                        period_pattern=pattern,
                    )
                )

        self.assertEqual(
            report_lint.liquidity_check(
                ["宏观流动性尚未回归。"],
                period_pattern=pattern,
            ),
            [],
        )
        self.assertEqual(
            report_lint.liquidity_check(
                ["影响通道：流动性；比特币现价=63000；仅作宏观事件观察。"],
                period_pattern=pattern,
            ),
            [],
        )
        self.assertTrue(
            report_lint.liquidity_check(
                ["流动性认证区间=61500-64400(日线)；其它参考周期=1H。"],
                period_pattern=pattern,
            )
        )
        self.assertTrue(
            report_lint.liquidity_check(
                ["清算图周期：3天；辅助位置=上方63350（3d；强）、下方62150（3天；强）。"],
                period_pattern=pattern,
            )
        )
        self.assertTrue(
            report_lint.liquidity_check(
                ["清算地图辅助位置=上方63350（3d）。"],
                period_pattern=pattern,
            )
        )
        self.assertEqual(
            report_lint.liquidity_check(
                ["清算图周期：3天；辅助位置=上方63350（3天；强）、下方62150（3天；强）。"],
                period_pattern=pattern,
            ),
            [],
        )

    def test_vnext_liquidity_timeframe_contract_fails_closed(self):
        contract = json.loads(
            (ROOT / "governance" / "vnext_report_presentation_contract.json").read_text(
                encoding="utf-8"
            )
        )
        mutations = []
        missing = copy.deepcopy(contract)
        del missing["timeframe_display_contract"]["canonical_by_code"]["1d"]
        mutations.append(missing)
        duplicate = copy.deepcopy(contract)
        duplicate["timeframe_display_contract"]["canonical_by_code"]["1d"] = "4H"
        mutations.append(duplicate)
        stale = copy.deepcopy(contract)
        stale["schema_version"] = "vnext-report-presentation-contract-v10"
        mutations.append(stale)
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                with self.assertRaises(ValueError):
                    report_lint.canonical_timeframe_pattern(mutated)

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
浮盈防守：成交后以实际加权成交价为风险基准。触及实际加权成交价 - 1.5R后，触发第一层防守，止损下移至成交后新形成并确认的4小时级别K线结构性极点高点，并取消所有加仓。触及实际加权成交价 - 2R后，触发第二层防守，剩余仓位仅移至保本损，不允许回退第一层保护。
""".splitlines()
        ledger_issues, ledger_skip = report_lint.ledger_check(lines)
        self.assertIsNone(ledger_skip)
        self.assertEqual(ledger_issues, [])
        self.assertEqual(report_lint.maker_defense_check(lines), [])

    def test_ladder_defense_accepts_actual_weighted_fill_formulas(self):
        lines = """
## ② Maker 计划
### BTC（反弹空）：执行概率58%　胜率64%
第一层：触及实际加权成交价 ± 1.5R后，成交后若后续形成并确认4H新极点则按新极点规则处理，不预填极点价
第二层：触及实际加权成交价 ± 2R后，仅把剩余仓位止损移至保本损
""".splitlines()
        self.assertEqual(report_lint.maker_defense_check(lines), [])

    def test_maker_defense_accepts_exact_non_executable_observe_placeholders(self):
        lines = """
## ② Maker 计划
### BTC（候选策略）
候选计划结论：本轮计划条件不成立，保持观察。
第一层：无可执行 Maker 计划，第一层防守暂不触发。
第二层：无可执行 Maker 计划，第二层防守暂不触发。
""".splitlines()
        self.assertEqual(report_lint.maker_defense_check(lines), [])

    def test_observe_placeholders_do_not_mask_an_executable_defense_defect(self):
        lines = """
## ② Maker 计划
### BTC（候选策略）
计划状态：仅观望、不挂单。
第一层：无可执行 Maker 计划，第一层防守暂不触发。
第二层：无可执行 Maker 计划，第二层防守暂不触发。
第一层：价格触及66,800后，把止损移到15分钟级别极点。
""".splitlines()
        hits = report_lint.maker_defense_check(lines)
        self.assertTrue(any("4H" in desc for _, desc, _, _ in hits))
        self.assertTrue(any("1H/15m" in desc for _, desc, _, _ in hits))

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

    def test_conditional_system_plan_empty_state_is_not_actual_position(self):
        lines = [
            "控制边界：若回撤后结构确认则重新评估偏多；若结构失效则主账户继续空仓。"
        ]
        self.assertEqual(report_lint.coupling_check(lines), [])

    def test_explicit_current_account_position_remains_blocked(self):
        lines = ["主账户当前继续空仓，Maker账户已有BTC空单成交50%。"]
        hits = report_lint.coupling_check(lines)
        self.assertGreaterEqual(len(hits), 2)
        self.assertTrue(all("实际持仓" in item[1] for item in hits[:2]))

    def test_exocharts_current_price_must_fit_declared_daily_ohlc(self):
        lines = [
            "  - 当日未完成K线：开59,689.8、高60,649.9、低58,205.5、收59,977.9；当前图面价格61,437.9。"
        ]
        hits = report_lint.exocharts_ohlc_check(lines)
        self.assertTrue(hits)

    def test_manual_profile_insufficiency_satisfies_only_the_profile_depth_dimension(self):
        lines = """
## ③ 后附
BlockBeats、Coinglass、Exocharts、FedWatch、Farside 与 TradingView 均已逐源复核。
用户手绘成交量分布本轮证据不足且不可读，因此不生成位置与猎杀概率。
清算图仅辅助观察且不替代用户手绘成交量分布，不承担方向翻转。
胜率按认证评分链推导，风险按止损距离验算，并保留反证、失效与情景路径。
""".splitlines()
        self.assertEqual(report_lint.manual_profile_boundary_check(lines), [])
        self.assertEqual(report_lint.analysis_depth_check(lines), [])

    def test_manual_profile_insufficiency_rejects_invented_profile_level(self):
        lines = """
## ③ 后附
用户手绘成交量分布本轮证据不足且不可读，因此不生成位置与猎杀概率。
用户手绘价格区域64,100仍作为反抽落点。
""".splitlines()
        hits = report_lint.manual_profile_boundary_check(lines)
        self.assertTrue(any("禁止输出" in item[1] for item in hits))

    def test_liquidation_map_cannot_fill_an_insufficient_manual_profile(self):
        lines = """
## ③ 后附
用户手绘成交量分布本轮证据不足且不可读，因此不生成位置与猎杀概率。
Coinglass 清算热力图显示上方磁吸。
""".splitlines()
        hits = report_lint.manual_profile_boundary_check(lines)
        self.assertTrue(any("必须明确不替代" in item[1] for item in hits))

        bounded = lines + ["清算图仅辅助观察且不替代该维度，不承担方向翻转。"]
        self.assertEqual(report_lint.manual_profile_boundary_check(bounded), [])

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
评分明细：盘口 45、盘面 18，总分 63；合成来自 Coinglass 的 CVD/OI/资金费率、Exocharts Delta、TradingView 多周期结构与用户手绘价值区，分项落值后再推导总分。
胜率 rubric 锚=60 → 次因 -2 → 落值 58 → 比 60 门槛不达标，因此不把临界胜率倒推到可开单。
方向主判：CVD 与 OI 给出空头占优，SMA20 与 pivot 摆动结构确认未破；最强反证是价格重新站回用户手绘价值区上沿，失效路径是放量上破后情景改为观望。
""".splitlines()
        self.assertEqual(report_lint.strict_reasoning_trace_check(lines), [])

    def test_strict_reasoning_trace_accepts_chinese_baseline_chain(self):
        lines = """
# 2026.7.7 早间日报
## ③ 后附
评分明细：盘口 45、盘面 18，总分 63；合成来自 Coinglass 的 CVD/OI/资金费率、Exocharts Delta、TradingView 多周期结构与用户手绘价值区，分项落值后再推导总分。
胜率基准推导链：基准锚 60，次因 -2，落值 58，再与 60 门槛比较，不把临界胜率倒推成可开单。
方向主判：CVD 与 OI 给出空头占优，SMA20 与 pivot 摆动结构确认未破；最强反证是价格重新站回用户手绘价值区上沿，失效路径是放量上破后情景改为观望。
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

    def test_v3_semantics_rejects_bare_platform_profile_level(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "TradingView VRVP 的 VAH 位于64,100，作为反弹阻力。",
            "无可执行 Maker 计划",
        ]
        hits = report_lint.v3_semantics_check(
            lines, "outputs/2026-07-12_midday_combined.md"
        )
        self.assertTrue(any("平台" in desc for _, desc, _, _ in hits))

    def test_v3_semantics_accepts_explicit_user_drawn_profile_level(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "用户手绘价值区上沿位于64,100，只表达位置阻力概率，不单变量翻向。",
            "无可执行 Maker 计划",
        ]
        self.assertEqual(
            report_lint.v3_semantics_check(
                lines, "outputs/2026-07-12_midday_combined.md"
            ),
            [],
        )

    def test_v3_semantics_rejects_one_shot_full_maker_entry(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "Maker在64,100一次性100%入场。",
            "无可执行 Maker 计划",
        ]
        hits = report_lint.v3_semantics_check(
            lines, "outputs/2026-07-12_midday_combined.md"
        )
        self.assertTrue(any("单点或一次性" in desc for _, desc, _, _ in hits))

    def test_v3_semantics_allows_explicit_rejection_of_one_shot_entry(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "Maker禁止一次性100%入场，必须采用真实分档。",
            "无可执行 Maker 计划",
        ]
        self.assertEqual(
            report_lint.v3_semantics_check(
                lines, "outputs/2026-07-12_midday_combined.md"
            ),
            [],
        )

    def test_v3_semantics_rejects_clause_scope_single_entry_bypasses(self):
        attacks = [
            "Maker一次性100％入场。",
            "Maker单档投入全部仓位。",
            "不是观望，而是一次性100%入场。",
            "禁止分档，改用一次性100%入场。",
            "全部仓位使用单价64,100。",
        ]
        for attack in attacks:
            with self.subTest(attack=attack):
                hits = report_lint.v3_semantics_check(
                    [
                        "胜率自估（计划时置信度，非回测命中率）",
                        attack,
                        "无可执行 Maker 计划",
                    ],
                    "outputs/2026-07-12_midday_combined.md",
                )
                self.assertTrue(
                    any("单点或一次性" in desc for _, desc, _, _ in hits),
                    hits,
                )

    def test_v3_semantics_rejects_mixed_manual_and_platform_profile_bypasses(self):
        attacks = [
            "用户手绘价值区已复核；平台VRVP的VAH位于64,100。",
            "平台内置POC位于64,100，作为反弹阻力。",
            "VAH位于64,100，作为反弹阻力。",
        ]
        for attack in attacks:
            with self.subTest(attack=attack):
                hits = report_lint.v3_semantics_check(
                    [
                        "胜率自估（计划时置信度，非回测命中率）",
                        attack,
                        "无可执行 Maker 计划",
                    ],
                    "outputs/2026-07-12_midday_combined.md",
                )
                self.assertTrue(
                    any("平台" in desc for _, desc, _, _ in hits),
                    hits,
                )

    def test_v3_semantics_rejects_reverse_inferred_actual_fill(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "根据止损与1.5R倒推出实际加权成交价为64,100。",
            "无可执行 Maker 计划",
        ]
        hits = report_lint.v3_semantics_check(
            lines, "outputs/2026-07-12_midday_combined.md"
        )
        self.assertTrue(any("反推实际成交均价" in desc for _, desc, _, _ in hits))

    def test_v3_semantics_allows_explicit_no_reverse_inference_boundary(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "禁止从1.5R、止盈或止损反推实际加权成交价；缺少成交明细时保持未知。",
            "无可执行 Maker 计划",
        ]
        self.assertEqual(
            report_lint.v3_semantics_check(
                lines, "outputs/2026-07-12_midday_combined.md"
            ),
            [],
        )

    def test_v3_semantics_keeps_exocharts_poc_separate_from_platform_profile(self):
        lines = [
            "胜率自估（计划时置信度，非回测命中率）",
            "**6. TradingView｜多周期结构、用户手绘成交量分布与机会质量**",
            "Exocharts POC位于64,100，只用于足迹确认。",
            "用户手绘价值区上沿位于64,300；平台VRVP禁用且不取值。",
            "使用边界：负责多周期结构、SMA20、用户手绘成交量分布区域和机会质量；平台内置VRVP与自动数值禁止使用，手绘区域不可读时只把该维度记为证据不足。",
            "无可执行 Maker 计划",
        ]
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
