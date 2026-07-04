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
BlockBeats / Coinglass / Exocharts / FedWatch / TradingView
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
        self.assertIn("source_evidence:tradingview", omissions)


if __name__ == "__main__":
    unittest.main()
