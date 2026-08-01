from __future__ import annotations

import unittest

from runtime_vnext.gates import _execution_parameter_leak


class Sma20ExecutionLeakUnitTests(unittest.TestCase):
    def test_descriptive_sma20_period_is_not_an_execution_parameter(self) -> None:
        for text in (
            "多周期结构偏空且价格低于SMA20，但急跌后临近支撑并缺少可认证入场区。",
            "多周期结构偏空且价格低于二十期均线，但该指标不构成止损或取消价。",
            "二十周期均线附近存在潜在入场区。",
            "SMA20只用于趋势判断，不作为入场、止损或取消价。",
            "不将SMA20作为止损。",
            "不得将SMA20作为入场或止损。",
            "禁止将SMA20作为入场或止损。",
            "止损不设在SMA20。",
        ):
            with self.subTest(text=text):
                self.assertIsNone(_execution_parameter_leak(text))

    def test_sma20_cannot_be_a_dynamic_execution_owner(self) -> None:
        for text in (
            "止损设在SMA20。",
            "入场价按SMA20确定。",
            "取消价设为SMA20。",
            "将SMA20作为止损。",
            "将SMA20作为入场。",
            "将SMA20作为取消价。",
            "价格回到SMA20即入场。",
            "不将SMA20作为止损，但将SMA20作为入场。",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(_execution_parameter_leak(text))

    def test_explicit_execution_numbers_near_sma20_remain_blocked(self) -> None:
        for text, expected in (
            ("SMA20附近入场区62800", "62800"),
            ("二十周期均线附近入场区62800-62900", "62800"),
            ("SMA20附近入场区，止损63100", "63100"),
            ("SMA20附近入场区，仓位750 USDT", "750"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_execution_parameter_leak(text), expected)


class Sma20ExecutionLeakReasoningGateTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.test_vnext_workflow import VNextWorkflowTests

        self.harness = VNextWorkflowTests(methodName="runTest")
        self.harness.setUp()
        self.evidence = self.harness.evidence()

    def tearDown(self) -> None:
        self.harness.tearDown()

    def _candidate_with_claim_text(self, text: str) -> dict:
        payload = self.harness.reasoning(self.evidence)
        maker_claim = next(
            item
            for item in payload["claims"]
            if item["claim_type"] == "maker_thesis"
        )
        maker_claim["conclusion"] += text
        return payload

    def test_descriptive_sma20_text_passes_the_execution_leak_gate(self) -> None:
        for text in (
            "价格低于SMA20，但该指标只描述结构，不构成入场、止损或取消价。",
            "不将SMA20作为止损。",
            "不得将SMA20作为入场或止损。",
            "禁止将SMA20作为入场或止损。",
            "止损不设在SMA20。",
        ):
            with self.subTest(text=text):
                payload = self._candidate_with_claim_text(text)
                result = self.harness.evaluate_reasoning_candidate(
                    self.evidence,
                    payload,
                )
                self.assertNotIn(
                    "claim.execution_parameter_second_truth",
                    {item.code for item in result.defects},
                )

    def test_dynamic_sma20_execution_anchors_fail_the_full_reasoning_gate(
        self,
    ) -> None:
        for text in (
            "止损设在SMA20。",
            "入场价按SMA20确定。",
            "取消价设为SMA20。",
            "将SMA20作为止损。",
            "将SMA20作为入场。",
            "将SMA20作为取消价。",
        ):
            with self.subTest(text=text):
                payload = self._candidate_with_claim_text(text)
                result = self.harness.evaluate_reasoning_candidate(
                    self.evidence,
                    payload,
                )
                self.assertFalse(result.passed)
                self.assertIn(
                    "claim.execution_parameter_second_truth",
                    {item.code for item in result.defects},
                )

if __name__ == "__main__":
    unittest.main()
