from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime.reasoning_contract import (
    build_reasoning_contract,
    validate_reasoning_contract_file,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReasoningContractTests(unittest.TestCase):
    def seed(self, root: Path) -> tuple[Path, dict]:
        scoring = root / "scoring"
        scoring.mkdir(parents=True)
        source_contract = Path(__file__).resolve().parents[1] / "scoring" / "scoring_contract.json"
        (scoring / "scoring_contract.json").write_text(
            source_contract.read_text(encoding="utf-8"), encoding="utf-8"
        )
        date_root = root / "runtime_state" / "2026-07-12"
        snapshot = date_root / "evidence" / "midday" / "run-1"
        snapshot.mkdir(parents=True)
        names = [
            "blockbeats.json",
            "coinglass.png",
            "liqheatmap_3d.png",
            "exocharts.png",
            "fedwatch.png",
            "farside_btc_etf.json",
            "tradingview_btc_1h.png",
        ]
        files = []
        for name in names:
            path = snapshot / name
            path.write_bytes(("fixture:" + name).encode())
            files.append({"path": name, "sha256": _hash(path), "size": path.stat().st_size})
        capture_dir = date_root / "captures" / "midday"
        capture_dir.mkdir(parents=True)
        capture = capture_dir / "capture.json"
        capture.write_text(
            json.dumps(
                {
                    "date": "2026-07-12",
                    "slot": "midday",
                    "success": True,
                    "evidence_snapshot": {
                        "root": "evidence/midday/run-1",
                        "files": files,
                    },
                }
            ),
            encoding="utf-8",
        )
        observations = [
            self.obs("obs.blockbeats", "blockbeats", "structured_observation", "blockbeats.json", {"tier": 2, "event_window_hours": 12, "selected_event_count": 3}),
            self.obs("obs.coinglass", "coinglass", "visual_judgment", ["coinglass.png", "liqheatmap_3d.png"], {
                "pivot": {"timeframe": "1h", "start_price": 100, "end_price": 103, "dominant_leg": "up", "trendline_status": "intact", "anchor_reset": False},
                "price_direction": "up", "cvd_direction": "up", "oi_direction": "up",
                "funding_direction": "down", "funding_sign": "near_zero",
                "combination_id": "C03",
                "effect_divergence": {
                    "cvd_break": "higher_high",
                    "price_confirmation": "confirmed",
                    "interpretation": "none",
                },
                "price_break_status": "new_high_or_breakout",
                "oi_price_context": "new_long_expansion",
                "main_triad_direction": "bullish",
                "main_triad_rationale": "CVD、价格与OI在同一主腿同步上行，主体三件套先形成偏多方向。",
                "funding_effect": "weaken",
                "final_direction": "bullish",
                "funding_single_variable_flip": False,
                "liquidation_map": {
                    "role": "auxiliary_only",
                    "threshold": 0.85,
                    "captured_timeframes": ["3d"],
                    "current_price": 103,
                    "levels": [
                        {
                            "side": "above", "price": 105,
                            "timeframe": "3d", "strength": "strong",
                        }
                    ],
                },
            }),
            self.obs("obs.exocharts", "exocharts", "visual_judgment", "exocharts.png", {
                "ohlc": {"open": 100, "high": 104, "low": 99, "close": 103},
                "poc": 102, "delta": 12, "cvd": 24, "volume": 1200,
            }),
            self.obs("obs.fedwatch", "fedwatch", "visual_judgment", "fedwatch.png", {
                "data_as_of": "2026-07-12T14:00:00-05:00", "next_fomc_date": "2026-07-29",
                "current_probabilities": {"hold": 65, "hike": 35},
                "change_1d": {"hold": -2, "hike": 2},
                "change_1w": {"hold": -6, "hike": 6},
                "change_1m": {"hold": -12, "hike": 12},
            }),
            self.obs("obs.farside", "farside_btc_etf", "structured_observation", "farside_btc_etf.json", {"latest_complete_date": "2026-07-10", "latest_total_usd_m": 90.4, "flow_direction": "inflow"}),
            self.obs("obs.tradingview", "tradingview", "visual_judgment", "tradingview_btc_1h.png", {
                "timeframes": {
                    "1d": {"price": 103, "sma20": 98, "structure": "bearish"},
                    "4h": {"price": 103, "sma20": 101, "structure": "bullish"},
                    "1h": {"price": 103, "sma20": 102, "structure": "bullish"},
                    "15m": {"price": 103, "sma20": 102.5, "structure": "range"},
                },
                "volume_profile": {"poc": 102, "value_area_position": "inside", "hvn_levels": [101, 102], "lvn_levels": [104]},
            }),
        ]
        claims = [
            self.claim("claim.fundamental", "fundamental_context", ["obs.blockbeats", "obs.fedwatch", "obs.farside"]),
            self.claim("claim.orderflow", "orderflow_interpretation", ["obs.coinglass", "obs.exocharts"]),
            self.claim("claim.chart", "chart_interpretation", ["obs.tradingview"]),
            self.claim("claim.counter", "strongest_counterevidence", ["claim.chart"], ["claim.orderflow"]),
            self.claim("claim.regime", "market_regime", ["claim.orderflow", "claim.chart"], ["claim.counter"]),
            self.claim("claim.invalidation", "invalidation_path", ["claim.counter"], ["claim.regime"]),
            self.claim("claim.main", "main_account_thesis", ["claim.regime", "claim.fundamental"], ["claim.counter"]),
            self.claim("claim.maker", "maker_thesis", ["claim.orderflow", "claim.chart"], ["claim.counter"]),
            self.claim("claim.cannot", "cannot_do", ["claim.maker", "claim.invalidation"]),
        ]
        components = {
            "chart.support_resistance": {"points": 8, "claim_ids": ["claim.chart"], "rationale": "多周期支撑阻力已由当前TradingView结构逐级核对。", "directional_use": False},
            "chart.liquidity_hunt": {"points": 7, "claim_ids": ["claim.chart"], "rationale": "VRVP主判价值区并由清算层级做辅助印证。", "directional_use": False},
            "chart.sma20_interaction": {"points": 3, "claim_ids": ["claim.chart"], "rationale": "四周期现价与SMA20关系已分别读取。", "directional_use": False},
            "chart.volume_price": {"points": 2, "claim_ids": ["claim.chart"], "rationale": "量价结构仅评价机会质量并保留周期冲突。", "directional_use": False},
            "chart.fibonacci_trendline": {"points": 1, "claim_ids": ["claim.chart"], "rationale": "趋势线与回撤工具只作结构位置评估。", "directional_use": False},
        }
        dimensions = {
            key: ["claim.orderflow"]
            for key in (
                "orderflow.pivot",
                "orderflow.price_cvd",
                "orderflow.oi",
                "orderflow.funding",
                "orderflow.footprint_confirmation",
            )
        }
        payload = {
            "trading_date": "2026-07-12",
            "slot": "midday",
            "observations": observations,
            "claims": claims,
            "score": {
                "orderflow": {
                    "value": 50,
                    "extreme_confirmed": False,
                    "dimensions": dimensions,
                    "holistic_rationale": "四维同一pivot后由足迹确认，存在反证所以不走极端分。",
                },
                "chart": {
                    "components": components,
                    "total": 21,
                    "score_semantics": "opportunity_quality_not_direction",
                },
                "total": 71,
            },
            "conviction": {
                "metric_kind": "plan_time_conviction",
                "calibrated_probability": False,
                "anchor": 64,
                "adjustments": [
                    {
                        "id": "adjust.counter",
                        "delta": -2,
                        "claim_ids": ["claim.counter"],
                        "rationale": "最强反证仍未失效，因此下调置信度。",
                    }
                ],
                "final": 62,
            },
            "methodology": self.methodology(),
            "report_projection": self.report_projection(),
            "decision": {
                "primary_claim_id": "claim.maker",
                "competing_claim_ids": ["claim.main", "claim.counter"],
                "strongest_counter_claim_id": "claim.counter",
                "invalidation_claim_id": "claim.invalidation",
                "residual_uncertainty": "视觉图表仍有转录误差和后续路径不确定性。",
            },
        }
        return capture, payload

    @staticmethod
    def methodology():
        return {
            "independent_synthesis": {
                "market_stage_claim_id": "claim.regime",
                "dominant_leg": "up",
                "primary_evidence_claim_ids": ["claim.orderflow", "claim.chart"],
                "strongest_counter_claim_id": "claim.counter",
                "action_claim_id": "claim.maker",
            },
            "fundamental_price_realization": {
                "fundamental_claim_id": "claim.fundamental",
                "price_claim_id": "claim.chart",
                "synthesis_claim_id": "claim.main",
                "realization_state": "partially_realized",
                "historical_market_fact_used": False,
            },
            "same_pivot_orderflow": {
                "observation_id": "obs.coinglass", "claim_id": "claim.orderflow",
                "leg_selected": True, "pullback_anchor_checked": True,
                "four_dimensions_same_anchor": True,
            },
            "footprint_cross_check": {
                "observation_id": "obs.exocharts", "claim_id": "claim.orderflow",
                "relationship": "confirm",
            },
            "multi_timeframe_transition": {
                "observation_id": "obs.tradingview", "claim_id": "claim.chart",
                "transition_summary": "日线反转未完成，但四小时与一小时处于同向修复，十五分钟仍在价值区震荡。",
            },
            "volume_profile_liquidity": {
                "claim_id": "claim.chart",
                "liquidation_observation_id": "obs.coinglass",
                "vrvp_primary": True,
                "liquidation_auxiliary": True,
                "liquidation_confirmation": "confirm",
            },
            "etf_flow_relation": {
                "observation_id": "obs.farside", "claim_id": "claim.fundamental",
                "price_relation": "confirm",
            },
            "account_separation": {
                "main_priority": ["fundamentals", "chart", "orderflow"],
                "maker_priority": ["orderflow", "chart", "fundamentals"],
                "main_claim_id": "claim.main", "maker_claim_id": "claim.maker",
                "conflict_resolution_claim_id": "claim.regime", "forced_consensus": False,
            },
            "scenario_tree": [
                {"kind": "base", "claim_id": "claim.maker", "trigger_claim_ids": ["claim.orderflow"], "action": "按认证计划继续等待高质量交易边缘"},
                {"kind": "counter", "claim_id": "claim.counter", "trigger_claim_ids": ["claim.chart"], "action": "反证持续增强时停止新增订单并等待"},
                {"kind": "invalidation", "claim_id": "claim.invalidation", "trigger_claim_ids": ["claim.regime"], "action": "结构确认失效后撤销计划并重新评估"},
            ],
            "cannot_do_derivation": {
                "claim_id": "claim.cannot", "basis_claim_ids": ["claim.maker", "claim.invalidation"],
                "filled_after_full_analysis": True,
            },
        }

    @staticmethod
    def report_projection():
        visible = [
            ("projection.visible.synthesis", "independent_synthesis", "opening_quote", ["claim.regime", "claim.main", "claim.counter"], "当前阶段由103附近的价格与多源证据独立合成，保留最强反证后再落主账户动作。", [("obs.coinglass", "pivot.end_price")]),
            ("projection.visible.realization", "fundamental_price_realization", "fundamentals", ["claim.fundamental", "claim.chart", "claim.main"], "BlockBeats按12小时事件窗分层后，再与当前盘面核对，结论为利好只部分兑现而不是新闻直接决定方向。", [("obs.blockbeats", "event_window_hours")]),
            ("projection.visible.pivot", "same_pivot_orderflow", "interpretation", ["claim.orderflow", "claim.counter"], "同一1小时锚点从100走到103，价格、CVD、OI与资金费率在同一主腿解释，回调没有被误当新腿。", [("obs.coinglass", "pivot.start_price"), ("obs.coinglass", "pivot.end_price")]),
            ("projection.visible.multi", "multi_timeframe_transition", "daily_line", ["claim.chart"], "日线现价103相对SMA20的98仍需结合四小时、一小时和十五分钟状态转换判断。", [("obs.tradingview", "timeframes.1d.price"), ("obs.tradingview", "timeframes.1d.sma20")]),
            ("projection.visible.accounts", "account_separation", "strategy", ["claim.main", "claim.maker"], "主账户按基本面、盘面、盘口排序，Maker按盘口、盘面、基本面排序，允许两者暂时不同向。", []),
            ("projection.visible.scenarios", "scenario_tree", "strategy", ["claim.maker", "claim.counter", "claim.invalidation"], "基准路径执行认证计划，反证增强则停止新增，结构失效则撤销并重新评估。", []),
            ("projection.visible.cannot", "cannot_do_derivation", "cannot_do", ["claim.cannot"], "不能做结论在完整分析后由拥挤侧、位置与失效路径共同推出。", []),
        ]
        appendix = [
            ("projection.appendix.synthesis", "independent_synthesis", ["claim.regime", "claim.counter"], "独立压缩结论以103为当前阶段值，并保留反方路径而不强行统一叙事。", [("obs.coinglass", "pivot.end_price")]),
            ("projection.appendix.realization", "fundamental_price_realization", ["claim.fundamental", "claim.chart", "claim.main"], "基本面先检查12小时事件层级，再由当期价格结构判定兑现、部分兑现、未兑现或冲突，禁止新闻单源翻向。", [("obs.blockbeats", "event_window_hours")]),
            ("projection.appendix.pivot", "same_pivot_orderflow", ["claim.orderflow"], "盘口三问完成：主腿100到103、回调未重置锚、四维保持同一pivot。", [("obs.coinglass", "pivot.start_price"), ("obs.coinglass", "pivot.end_price")]),
            ("projection.appendix.footprint", "footprint_cross_check", ["claim.orderflow"], "足迹以POC 102、Delta 12、CVD 24和成交量1200校验盘口强弱。", [("obs.exocharts", "poc"), ("obs.exocharts", "delta"), ("obs.exocharts", "cvd"), ("obs.exocharts", "volume")]),
            ("projection.appendix.multi", "multi_timeframe_transition", ["claim.chart"], "多周期从日线103到四小时、一小时、十五分钟逐级校准，日线SMA20为98。", [("obs.tradingview", "timeframes.1d.price"), ("obs.tradingview", "timeframes.1d.sma20")]),
            ("projection.appendix.liquidity", "volume_profile_liquidity", ["claim.chart"], "VRVP以POC 102主判，Coinglass清算图105仅作为辅助印证而不单独翻向。", [("obs.tradingview", "volume_profile.poc"), ("obs.coinglass", "liquidation_map.levels.0.price")]),
            ("projection.appendix.etf", "etf_flow_relation", ["claim.fundamental"], "ETF最新总流量90.4与价格关系只作现货侧确认，不污染盘口评分。", [("obs.farside", "latest_total_usd_m")]),
            ("projection.appendix.accounts", "account_separation", ["claim.main", "claim.maker"], "主账户与Maker分别按各自优先级形成判断，冲突时不强制压成同一方向。", []),
            ("projection.appendix.scenarios", "scenario_tree", ["claim.maker", "claim.counter", "claim.invalidation"], "基准、最强反证和硬失效三条路径都绑定具体触发与动作。", []),
            ("projection.appendix.cannot", "cannot_do_derivation", ["claim.cannot", "claim.invalidation"], "不能做只在完整推理后回填，并由拥挤侧与失效路径共同承重。", []),
        ]
        items = []
        for item_id, unit, section, claims, text, refs in visible:
            items.append({"id": item_id, "semantic_unit": unit, "surface": "visible", "section": section, "claim_ids": claims, "text": text, "value_refs": [{"observation_id": obs, "path": path} for obs, path in refs]})
        for item_id, unit, claims, text, refs in appendix:
            items.append({"id": item_id, "semantic_unit": unit, "surface": "appendix", "section": "appendix", "claim_ids": claims, "text": text, "value_refs": [{"observation_id": obs, "path": path} for obs, path in refs]})
        return {"items": items}

    @staticmethod
    def obs(item_id, source, kind, evidence, values=None):
        return {
            "id": item_id,
            "source": source,
            "kind": kind,
            "observed_at": "2026-07-12T14:00:00+08:00",
            "window": "current-slot",
            "freshness_status": "current_slot_valid",
            "statement": f"{source} 当前时段的可复核观察值。",
            "values": values,
            "uncertainty": "存在截图转录或数据窗口不完整风险",
            "alternate_interpretation": (
                "同一视觉结构也可能只是短时噪声而非有效信号"
                if kind == "visual_judgment"
                else None
            ),
            "evidence_refs": evidence if isinstance(evidence, list) else [evidence],
        }

    @staticmethod
    def claim(item_id, claim_type, support, counter=None):
        return {
            "id": item_id,
            "claim_type": claim_type,
            "statement": f"{claim_type} 的完整判断陈述并保留条件边界。",
            "support_ids": support,
            "counter_ids": counter or [],
            "inference": "由列出的当前证据与上游判断推出，不使用历史方向或分数。",
            "confidence_band": "medium",
            "invalidation": "若上游证据反向变化或关键结构被突破则失效。",
        }

    @staticmethod
    def set_orderflow_score(payload, value, *, extreme=False):
        payload["score"]["orderflow"]["value"] = value
        payload["score"]["orderflow"]["extreme_confirmed"] = extreme
        payload["score"]["total"] = value + payload["score"]["chart"]["total"]

    @staticmethod
    def set_orderflow_states(
        payload, *, cvd, price, oi, funding_sign, combination_id,
        cvd_break, price_confirmation, interpretation, oi_price_context,
        direction,
    ):
        values = payload["observations"][1]["values"]
        values.update({
            "cvd_direction": cvd,
            "price_direction": price,
            "oi_direction": oi,
            "funding_sign": funding_sign,
            "combination_id": combination_id,
            "effect_divergence": {
                "cvd_break": cvd_break,
                "price_confirmation": price_confirmation,
                "interpretation": interpretation,
            },
            "price_break_status": (
                "stalled_no_new_high"
                if price == "up" and oi == "down"
                else "new_low_or_breakdown"
                if price == "down"
                else "new_high_or_breakout"
                if price == "up"
                else "not_applicable"
            ),
            "oi_price_context": oi_price_context,
            "main_triad_direction": direction,
            "main_triad_rationale": (
                "主体三件套与效果背离共同形成看涨方向，资金费率只用于调整强弱。"
                if direction == "bullish"
                else "主体三件套与效果背离共同形成看跌方向，资金费率只用于调整强弱。"
            ),
            "final_direction": direction,
        })

    def test_valid_contract_is_deterministic_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            contract = build_reasoning_contract(payload, capture_manifest_path=capture, root=root)
            target = root / "runtime_state" / "2026-07-12" / "reasoning_contract_midday.json"
            target.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                validate_reasoning_contract_file(
                    target, "2026-07-12", "midday", root=root
                ),
                contract,
            )
            self.assertEqual(contract["score"]["total"], 71)
            self.assertFalse(contract["conviction"]["calibrated_probability"])

    def test_visual_judgment_requires_alternative_interpretation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][1]["alternate_interpretation"] = ""
            with self.assertRaisesRegex(ValueError, "alternate_interpretation"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_source_cannot_borrow_another_sources_screenshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][1]["evidence_refs"] = ["fedwatch.png"]
            with self.assertRaisesRegex(ValueError, "source/evidence mismatch"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_capture_must_be_current_date_and_slot_immutable_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            outside = root / "runtime_state" / "2026-07-12" / "capture.json"
            outside.write_bytes(capture.read_bytes())
            with self.assertRaisesRegex(ValueError, "outside current date/slot"):
                build_reasoning_contract(payload, capture_manifest_path=outside, root=root)

    def test_fundamentals_cannot_contaminate_orderflow_score(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["claims"][1]["support_ids"].append("obs.blockbeats")
            with self.assertRaisesRegex(
                ValueError, r"source-role violation|Coinglass\+Exocharts-only"
            ):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_tradingview_cannot_contaminate_orderflow_score(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["score"]["orderflow"]["dimensions"]["orderflow.pivot"] = [
                "claim.regime"
            ]
            with self.assertRaisesRegex(ValueError, r"Coinglass\+Exocharts-only"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_forward_or_missing_reasoning_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["claims"][0]["support_ids"] = ["claim.maker"]
            with self.assertRaisesRegex(ValueError, "forward support"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_chart_total_and_component_caps_are_mechanical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["score"]["chart"]["components"]["chart.sma20_interaction"]["points"] = 6
            with self.assertRaisesRegex(ValueError, "exceeds allowed range"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_contract_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            contract = build_reasoning_contract(payload, capture_manifest_path=capture, root=root)
            contract["score"]["total"] = 99
            target = root / "runtime_state" / "2026-07-12" / "reasoning_contract_midday.json"
            target.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_reasoning_contract_file(
                    target, "2026-07-12", "midday", root=root
                )

    def test_same_pivot_three_question_check_is_mandatory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["methodology"]["same_pivot_orderflow"]["pullback_anchor_checked"] = False
            with self.assertRaisesRegex(ValueError, "pullback_anchor_checked"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_visible_projection_must_render_bound_evidence_value(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["report_projection"]["items"][0]["text"] = (
                "当前阶段只有通用结论，没有把绑定的证据数值投影到人类可见报告。"
            )
            with self.assertRaisesRegex(ValueError, "does not render bound value"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_account_priority_cannot_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["methodology"]["account_separation"]["main_priority"] = [
                "orderflow", "chart", "fundamentals"
            ]
            with self.assertRaisesRegex(ValueError, "main account priority"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_load_bearing_claim_requires_two_independent_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["claims"][7]["support_ids"] = ["claim.chart"]
            with self.assertRaisesRegex(ValueError, "independent sources"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_gold_refined_integer_orderflow_scores_are_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, seed_payload = self.seed(root)
            for value in (52, 53, 55, 56, 57, 58):
                with self.subTest(value=value):
                    payload = copy.deepcopy(seed_payload)
                    self.set_orderflow_score(payload, value)
                    contract = build_reasoning_contract(
                        payload, capture_manifest_path=capture, root=root
                    )
                    self.assertEqual(contract["score"]["orderflow"]["value"], value)

    def test_orderflow_score_must_be_integer_inside_zero_to_seventy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, seed_payload = self.seed(root)
            for value, message in ((55.5, "integer"), (-1, "0..70"), (71, "0..70")):
                with self.subTest(value=value):
                    payload = copy.deepcopy(seed_payload)
                    self.set_orderflow_score(payload, value)
                    with self.assertRaisesRegex(ValueError, message):
                        build_reasoning_contract(
                            payload, capture_manifest_path=capture, root=root
                        )

    def test_c01_c81_combination_id_is_derived_not_trusted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][1]["values"]["combination_id"] = "C01"
            with self.assertRaisesRegex(ValueError, "must be C03"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_true_extreme_candidates_are_the_only_combinations_allowed_at_seventy(self):
        cases = (
            ("C19", "up", "down", "up", "positive", "higher_high", "not_confirmed", "bearish", "new_short_expansion", "bearish"),
            ("C22", "up", "down", "flat", "positive", "higher_high", "not_confirmed", "bearish", "mixed", "bearish"),
            ("C56", "down", "up", "up", "negative", "lower_low", "not_confirmed", "bullish", "new_long_expansion", "bullish"),
            ("C59", "down", "up", "flat", "negative", "lower_low", "not_confirmed", "bullish", "mixed", "bullish"),
        )
        for case in cases:
            with self.subTest(combination_id=case[0]), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                capture, payload = self.seed(root)
                self.set_orderflow_states(
                    payload,
                    combination_id=case[0], cvd=case[1], price=case[2], oi=case[3],
                    funding_sign=case[4], cvd_break=case[5],
                    price_confirmation=case[6], interpretation=case[7],
                    oi_price_context=case[8], direction=case[9],
                )
                self.set_orderflow_score(payload, 70, extreme=True)
                contract = build_reasoning_contract(
                    payload, capture_manifest_path=capture, root=root
                )
                self.assertTrue(contract["score"]["orderflow"]["extreme_candidate"])

    def test_non_candidate_cannot_claim_seventy_and_candidate_may_remain_sixty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            self.set_orderflow_score(payload, 70, extreme=True)
            with self.assertRaisesRegex(ValueError, "requires one of"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            self.set_orderflow_states(
                payload, combination_id="C19", cvd="up", price="down", oi="up",
                funding_sign="positive", cvd_break="higher_high",
                price_confirmation="not_confirmed", interpretation="bearish",
                oi_price_context="new_short_expansion", direction="bearish",
            )
            self.set_orderflow_score(payload, 60)
            contract = build_reasoning_contract(
                payload, capture_manifest_path=capture, root=root
            )
            self.assertTrue(contract["score"]["orderflow"]["extreme_candidate"])
            self.assertFalse(contract["score"]["orderflow"]["extreme_confirmed"])

    def test_effect_divergence_and_oi_context_must_match_observed_states(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][1]["values"]["effect_divergence"]["interpretation"] = "bearish"
            with self.assertRaisesRegex(ValueError, "effect divergence interpretation"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][1]["values"]["oi_price_context"] = "short_cover_squeeze"
            with self.assertRaisesRegex(ValueError, "conflicts with price/OI"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_price_up_oi_down_distinguishes_squeeze_from_profit_taking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            self.set_orderflow_states(
                payload, combination_id="C09", cvd="up", price="up", oi="down",
                funding_sign="near_zero", cvd_break="higher_high",
                price_confirmation="confirmed", interpretation="none",
                oi_price_context="profit_taking_plus_spot_supply", direction="bullish",
            )
            build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

            payload["observations"][1]["values"]["price_break_status"] = "new_high_or_breakout"
            payload["observations"][1]["values"]["oi_price_context"] = "short_cover_squeeze"
            build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

            payload["observations"][1]["values"]["oi_price_context"] = (
                "profit_taking_plus_spot_supply"
            )
            with self.assertRaisesRegex(ValueError, "distinguish breakout squeeze"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_funding_cannot_flip_the_main_triad_direction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][1]["values"]["final_direction"] = "bearish"
            with self.assertRaisesRegex(ValueError, r"preserve the CVD\+price\+OI direction"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_chart_score_is_tradingview_only_direction_neutral_and_explained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["score"]["chart"]["components"]["chart.support_resistance"]["claim_ids"] = ["claim.regime"]
            with self.assertRaisesRegex(ValueError, "TradingView-only provenance"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["score"]["chart"]["components"]["chart.support_resistance"]["directional_use"] = True
            with self.assertRaisesRegex(ValueError, "directional_use=false"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["score"]["chart"]["score_semantics"] = "bullish_score"
            with self.assertRaisesRegex(ValueError, "opportunity_quality_not_direction"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_15m_sma20_is_optional_but_scored_timeframe_sma20_is_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            del payload["observations"][5]["values"]["timeframes"]["15m"]["sma20"]
            contract = build_reasoning_contract(
                payload, capture_manifest_path=capture, root=root
            )
            self.assertNotIn(
                "sma20", contract["methodology"]["multi_timeframe_transition"]
                ["timeframes"]["15m"]
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            del payload["observations"][5]["values"]["timeframes"]["1h"]["sma20"]
            with self.assertRaisesRegex(ValueError, "TradingView 1h.sma20"):
                build_reasoning_contract(
                    payload, capture_manifest_path=capture, root=root
                )

    def test_liquidation_map_must_be_coinglass_auxiliary_not_tradingview(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["methodology"]["volume_profile_liquidity"][
                "liquidation_observation_id"
            ] = "obs.tradingview"
            with self.assertRaisesRegex(ValueError, "must reference coinglass"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            liquidation = payload["observations"][1]["values"].pop("liquidation_map")
            payload["observations"][5]["values"]["liquidation_map"] = liquidation
            with self.assertRaisesRegex(ValueError, "missing required judgment value"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_liquidation_map_enforces_weekend_window_threshold_side_and_role(self):
        mutations = (
            (lambda value: value.update({"captured_timeframes": ["48h"]}), r"requires \['3d'\]"),
            (lambda value: value.update({"threshold": 0.9}), "threshold must match"),
            (
                lambda value: value["levels"][0].update({"side": "below"}),
                "side conflicts with current price",
            ),
        )
        for mutate, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                capture, payload = self.seed(root)
                mutate(payload["observations"][1]["values"]["liquidation_map"])
                with self.assertRaisesRegex(ValueError, message):
                    build_reasoning_contract(
                        payload, capture_manifest_path=capture, root=root
                    )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["methodology"]["volume_profile_liquidity"]["vrvp_primary"] = False
            with self.assertRaisesRegex(ValueError, "VRVP must remain the primary"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_source_cannot_directly_support_claim_outside_its_method(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["claims"][2]["support_ids"] = ["obs.tradingview", "obs.exocharts"]
            with self.assertRaisesRegex(ValueError, "source-role violation"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_missing_source_judgment_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            del payload["observations"][3]["values"]["change_1m"]
            with self.assertRaisesRegex(ValueError, "missing required judgment value"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_fundamental_price_realization_cannot_borrow_historical_market_fact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["methodology"]["fundamental_price_realization"][
                "historical_market_fact_used"
            ] = True
            with self.assertRaisesRegex(ValueError, "current-slot facts only"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_fedwatch_probability_distribution_must_balance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][3]["values"]["current_probabilities"]["hold"] = 80
            with self.assertRaisesRegex(ValueError, "sum to approximately 100"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_farside_flow_label_must_match_signed_total(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][4]["values"]["flow_direction"] = "outflow"
            with self.assertRaisesRegex(ValueError, "conflicts with latest total"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)

    def test_exocharts_poc_must_be_inside_captured_ohlc(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture, payload = self.seed(root)
            payload["observations"][2]["values"]["poc"] = 110
            with self.assertRaisesRegex(ValueError, "POC must lie inside"):
                build_reasoning_contract(payload, capture_manifest_path=capture, root=root)


if __name__ == "__main__":
    unittest.main()
