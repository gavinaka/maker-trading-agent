from __future__ import annotations

import unittest

from runtime.report_state_extract import extract_report_state, validate_report_state


REPORT = """
> 门禁 6/29：可交易／正常
> 评分：盘口 57 + 盘面 20 = 总分 77；胜率自估 66%。

不能做：（追）做空
基本面：中性偏空（测试）价格部分兑现
盘口（合约）：
CVD下降　价格下降　资金费率上升（为正值）　持仓上升
日线级别　日线摘要　利空
小时级别　小时摘要　中性
趋势确认：空头趋势（中短线）
日内支撑：58,900-59,200　　　日内压力：60,350-60,600
策略：
主账户等待独立中线触发。
## ② Maker 计划
反弹空：60,500-60,650
## ③ 后附
- **盘口 57／70**
- **盘面 20／30**
- **总分 57+20＝77，达到技术门槛。**
- **胜率自估 66%**
- **风险验算**：风险低于3%。
BlockBeats / Coinglass / Exocharts / FedWatch / Farside / TradingView
"""

CANONICAL_REPORT = """# 2026.7.11 早间日报

> 门禁 7/11：可交易／正常

## ① 正文

## 不能做

不能做：（追）做空

### 基本面

基本面：中性偏空（测试）价格部分兑现

### 技术面

盘口（合约）：
CVD下降　价格下降　资金费率上升（为正值）　持仓上升

### 解读

解读：看跌背离
盘面：
日线级别：日线摘要　利空
小时级别：小时摘要　中性

### 趋势确认

趋势确认：空头趋势（中短线）

### 日内支撑/压力

日内支撑：58,900-59,200　　日内压力：60,350-60,600

### 策略

策略：
主账户等待独立中线触发。

## ② Maker 计划

BTC（策略）：执行概率65%（已执行0%）　胜率66%
反弹空：60,500-60,650　持仓500刀　OKX　Maker　左侧　5倍　盈亏比1:2以上
止盈：59,500（TP1）减仓50% ／ 58,900（TP2·清剩余仓位）
止损：61,000

### 防守计划

第一层：成交后等待4H结构性极点确认再移动止损。
第二层：价格触及59,800，设置保本损。
注意事项：价格不到不成交，不追空。
⚠️取消价≠止损：成交前失效与成交后止损分离。
独立边界：本报告只由本时段锁定六源推导。

## ③ 后附

- 盘口：57／70
- 盘面：20／30
- 总分：77
- 胜率自估：66%
- 风险验算：风险低于3%。
BlockBeats / Coinglass / Exocharts / FedWatch / Farside / TradingView
"""


class ReportStateExtractTests(unittest.TestCase):
    def test_extracts_business_fields_without_reinterpreting(self):
        payload = extract_report_state(REPORT)
        archive = payload["analysis_archive"]
        self.assertEqual(archive["reuse_policy"], "post_analysis_audit_only")
        self.assertEqual(archive["features"]["orderflow"]["cvd"], "下降")
        self.assertEqual(
            archive["features"]["orderflow"]["funding_sign"], "为正值"
        )
        self.assertEqual(archive["scores"]["orderflow"], 57)
        self.assertEqual(archive["scores"]["chart"]["total"], 20)
        self.assertEqual(archive["scores"]["total"], 77)
        self.assertEqual(archive["scores"]["winrate"], 66)
        self.assertEqual(payload["decision"]["cannot_do"], "（追）做空")
        self.assertIn("反弹空", payload["decision"]["maker"]["raw"])

    def test_complete_report_has_no_lock_omissions(self):
        self.assertEqual(validate_report_state(REPORT), [])

    def test_canonical_payload_structure_and_state_extractor_share_one_contract(self):
        payload = extract_report_state(
            CANONICAL_REPORT,
            trading_date="2026-07-11",
            slot="morning",
        )
        self.assertEqual(validate_report_state(CANONICAL_REPORT, payload), [])
        self.assertEqual(
            payload["analysis_archive"]["features"]["orderflow"]["cvd"],
            "下降",
        )
        self.assertEqual(payload["analysis_archive"]["scores"]["total"], 77)
        self.assertEqual(
            payload["decision"]["main_account"]["strategy"],
            "主账户等待独立中线触发。",
        )

    def test_position_coupling_blocks_lock(self):
        omissions = validate_report_state(
            REPORT + "\nBTC（策略）：观望·不挂单（Maker账户已有BTC空单成交50%，先补齐风控，禁止新增或补仓）\n"
        )
        self.assertTrue(
            any(item.startswith("position_coupling:") for item in omissions)
        )

    def test_empty_report_cannot_be_locked(self):
        omissions = validate_report_state("空报告")
        self.assertIn("score_total", omissions)
        self.assertIn("source_evidence:farside_btc_etf", omissions)
        self.assertIn("source_evidence:tradingview", omissions)


if __name__ == "__main__":
    unittest.main()
