from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.adversarial_review import build_adversarial_review
from runtime.reasoning_contract import build_reasoning_contract
from tests.test_reasoning_contract import ReasoningContractTests


class AdversarialReviewTests(unittest.TestCase):
    def seed(self, root: Path):
        capture, payload = ReasoningContractTests().seed(root)
        reasoning = build_reasoning_contract(payload, capture_manifest_path=capture, root=root)
        reasoning_path = root / "runtime_state" / "2026-07-12" / "reasoning_contract_midday.json"
        reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False), encoding="utf-8")
        high_impact = [
            item["id"]
            for item in reasoning["claims"]
            if item["claim_type"]
            in {
                "market_regime",
                "main_account_thesis",
                "maker_thesis",
                "strongest_counterevidence",
                "invalidation_path",
            }
        ]
        checks = []
        for index, check_type in enumerate(
            (
                "source_integrity",
                "claim_support",
                "competing_interpretation",
                "score_contamination",
                "risk_semantics",
            )
        ):
            checks.append(
                {
                    "id": f"check.{index}",
                    "check_type": check_type,
                    "status": "pass",
                    "node_ids": [high_impact[index % len(high_impact)]],
                    "challenge": "按最不利解释重新检查证据、推理边界及可能的反向路径。",
                    "resolution": "冻结证据仍能支撑有限结论，但不消除市场不确定性。",
                    "residual_risk": "后续市场路径和视觉转录仍可能变化。",
                }
            )
        review = {
            "reasoning_contract_sha256": reasoning["contract_sha256"],
            "reviewer_mode": "isolated_second_pass",
            "reviewed_claim_ids": high_impact,
            "claim_verdicts": [
                {
                    "claim_id": claim_id,
                    "status": "uphold",
                    "challenged_support_ids": [
                        next(item for item in reasoning["claims"] if item["id"] == claim_id)["support_ids"][0]
                    ],
                    "challenged_counter_ids": [
                        next(item for item in reasoning["claims"] if item["id"] == claim_id)["counter_ids"][0]
                    ],
                    "resolution_node_ids": [
                        next(item for item in reasoning["claims"] if item["id"] == claim_id)["support_ids"][0]
                    ],
                    "why_counter_does_not_flip": "反方证据会降低强度，但当前同锚证据和跨源确认仍未被反向条件推翻。",
                    "residual_uncertainty": "后续价格路径及视觉转录仍有不确定性。",
                }
                for claim_id in high_impact
            ],
            "checks": checks,
            "conclusion": "第二遍反证没有发现需要阻断的证据断链，但保留明确剩余风险。",
        }
        return reasoning_path, review

    def test_complete_pass_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reasoning, review = self.seed(root)
            result = build_adversarial_review(
                review,
                reasoning_contract_path=reasoning,
                trading_date="2026-07-12",
                slot="midday",
                root=root,
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                result["independence_claim"],
                "process_isolated_not_external_independent_oracle",
            )

    def test_missing_claim_coverage_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reasoning, review = self.seed(root)
            review["reviewed_claim_ids"].pop()
            with self.assertRaisesRegex(ValueError, "coverage invalid"):
                build_adversarial_review(
                    review,
                    reasoning_contract_path=reasoning,
                    trading_date="2026-07-12",
                    slot="midday",
                    root=root,
                )

    def test_any_reject_blocks_certification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reasoning, review = self.seed(root)
            review["checks"][0]["status"] = "reject"
            with self.assertRaisesRegex(ValueError, "rejected frozen reasoning"):
                build_adversarial_review(
                    review,
                    reasoning_contract_path=reasoning,
                    trading_date="2026-07-12",
                    slot="midday",
                    root=root,
                )

    def test_claimed_review_coverage_requires_concrete_check_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reasoning, review = self.seed(root)
            review["checks"][0]["node_ids"] = review["checks"][1]["node_ids"]
            with self.assertRaisesRegex(ValueError, "lack concrete checks"):
                build_adversarial_review(
                    review,
                    reasoning_contract_path=reasoning,
                    trading_date="2026-07-12",
                    slot="midday",
                    root=root,
                )

    def test_generic_verdict_without_concrete_counter_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reasoning, review = self.seed(root)
            review["claim_verdicts"][0]["challenged_counter_ids"] = []
            with self.assertRaisesRegex(ValueError, "concrete counter"):
                build_adversarial_review(
                    review,
                    reasoning_contract_path=reasoning,
                    trading_date="2026-07-12",
                    slot="midday",
                    root=root,
                )


if __name__ == "__main__":
    unittest.main()
