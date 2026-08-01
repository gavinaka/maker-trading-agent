from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_vnext.report_compiler as compiler
import tests.test_vnext_workflow as workflow_fixtures
from outputs import report_lint


CME_PROVIDER_META = {
    "provider_id": "cme_fedwatch_ui",
    "selection_mode": "cme_primary",
    "series_ticker": None,
    "acquisition_channel": "rendered_official_ui",
    "method_class": "cme_target_rate_probability",
    "method_equivalence": "canonical",
    "sample_source_class": "cme_canonical",
    "quote_basis_code": "cme_rendered_probability_table_v1",
    "normalization_method_code": "identity_cme_distribution_v1",
    "fallback_reason_code": "none",
    "provenance_sha256": "f" * 64,
}

KALSHI_PROVIDER_META = {
    "provider_id": "kalshi_public_market_data_api",
    "selection_mode": "kalshi_plan_c_fallback",
    "series_ticker": "KXFEDDECISION",
    "acquisition_channel": "public_market_data_api",
    "method_class": "independent_event_contract_market",
    "method_equivalence": "non_equivalent",
    "sample_source_class": "kalshi_plan_c_observation",
    "quote_basis_code": "kalshi_yes_bid_ask_midpoint_dollars_v1",
    "normalization_method_code": "kalshi_bounded_simplex_other_unlisted_v1",
    "fallback_reason_code": "cme_tool_content_load_error",
    "provenance_sha256": "e" * 64,
}


class ReportCompilerSemanticProjectionTests(unittest.TestCase):
    @staticmethod
    def fedwatch_outcome_pattern():
        return compiler._fedwatch_outcome_pattern(compiler.load_scoring_policy())

    def test_timeframe_display_contract_projects_all_codes_and_rejects_drift(self) -> None:
        presentation = compiler.load_presentation_contract(
            Path(compiler.__file__).resolve().parents[1]
        )
        display = compiler._validated_timeframe_display_contract(presentation)
        expected = {
            "1d": "1D",
            "4h": "4H",
            "1h": "1H",
            "15m": "15m",
            "3d": "3天",
            "48h": "48H",
            "24h": "24H",
        }
        self.assertEqual(
            {
                code: compiler._timeframe_display_label(display, code)
                for code in expected
            },
            expected,
        )
        for stale in ("", "2h", "1D", "15M", "日线", None):
            with self.subTest(stale=stale):
                with self.assertRaises(ValueError):
                    compiler._timeframe_display_label(display, stale)
        self.assertIn(
            "3天认证价",
            compiler._entry_reach_probability_text(
                {
                    "reference_source": "TradingView",
                    "reference_timeframe": "3d",
                    "reference_price": 63000,
                    "reference_entry": 62000,
                    "entry_distance": 1000,
                    "reach_direction": "down_to_entry",
                },
                projection={"applicability": "applicable"},
                timeframe_contract=display,
            ),
        )

    @staticmethod
    def complete_scoring_contract(
        reasoning: dict,
        maker: dict,
        *,
        orderflow_claim_id: str = "cl_anchor_orderflow",
        extra_adjustments: list[dict] | None = None,
    ) -> dict:
        claims = reasoning.setdefault("claims", [])
        observations_by_id = {
            str(item.get("id")): item
            for item in reasoning.get("observations", [])
            if isinstance(item, dict) and item.get("id")
        }
        tv_structure = (
            (((observations_by_id.get("obs_tv") or {}).get("metrics") or {}).get(
                "timeframes"
            )
            or {}).get("15m", {}).get("structure")
        )
        claims_by_id = {
            str(item.get("id")): item
            for item in claims
            if isinstance(item, dict) and item.get("id")
        }
        if orderflow_claim_id not in claims_by_id:
            claims.append(
                {
                    "id": orderflow_claim_id,
                    "claim_type": "orderflow_interpretation",
                    "account": "shared",
                    "support_ids": ["obs_cg", "obs_exo"],
                }
            )
        else:
            claims_by_id[orderflow_claim_id].setdefault("account", "shared")
        chart_claim_id = "cl_anchor_chart"
        if chart_claim_id not in claims_by_id:
            claims.append(
                {
                    "id": chart_claim_id,
                    "claim_type": "chart_interpretation",
                    "account": "shared",
                    "support_ids": ["obs_tv"],
                }
            )
        if not any(
            item.get("claim_type") == "liquidation_confirmation"
            for item in claims
            if isinstance(item, dict)
        ):
            claims.append(
                {
                    "id": "cl_liquidation_confirmation",
                    "claim_type": "liquidation_confirmation",
                    "account": "shared",
                    "confirmation_result": "neutral",
                    "support_ids": ["obs_cg", chart_claim_id],
                    "method_tags": ["liquidation.auxiliary_only"],
                }
            )
        counter_claim_id = "cl_counter_maker"
        claims.append(
            {
                "id": counter_claim_id,
                "claim_type": "strongest_counterevidence",
                "account": "maker",
                "support_ids": [orderflow_claim_id, chart_claim_id],
                "current_basis": {
                    "mode": "all",
                    "clauses": [
                        {
                            "owner_type": "observation",
                            "owner_id": "obs_tv",
                            "field": "timeframes.15m.structure",
                            "operator": "equals",
                            "value": tv_structure,
                        },
                    ],
                },
            }
        )
        reasoning.setdefault("methodology", {})["account_separation"] = {
            "maker_counter_claim_id": counter_claim_id
        }
        adjustments = [
            {
                "reason_code": "maker_counter_current",
                "label": "自由文本不得投影",
                "delta": -2,
                "claim_ids": [counter_claim_id],
                "rationale": "自由文本不得投影为业务事实。",
            },
            *(extra_adjustments or []),
        ]
        maker["winrate_rubric"] = {
            "anchor": 64,
            "anchor_claim_ids": [orderflow_claim_id, chart_claim_id],
            "anchor_rationale": "盘口轴与结构位置轴均已按类型化 claim 和可达来源认证；基准锚不读取计划状态、60%门槛或开单结果。",
            "adjustments": adjustments,
            "counter_resolution": {
                "counter_claim_id": counter_claim_id,
                "disposition": "adjusted",
                "adjustment_reason_code": "maker_counter_current",
                "residual_clause_indexes": [0],
                "resolution_claim_ids": [],
            },
            "final": 64 + sum(item["delta"] for item in adjustments),
        }
        return maker

    def test_legacy_vrvp_demo_mappings_and_prices_are_absent(self) -> None:
        for legacy_key in compiler.METRIC_VALUE_CN:
            with self.subTest(legacy_key=legacy_key):
                self.assertNotIn("VRVP", legacy_key)
                self.assertNotIn("VAH=", legacy_key)
                self.assertNotIn("POC=", legacy_key)

        self.assertNotIn(
            "liquidation_confirmation_result",
            compiler.METRIC_LABEL_CN,
        )
        self.assertNotIn("VRVP", compiler.METRIC_LABEL_CN["vrvp"])

    def test_human_visible_enum_projection_is_domain_qualified_and_closed(
        self,
    ) -> None:
        expected = {
            "tradingview.chart_basis.volume_price_state": {
                "confirm": "确认",
                "weaken": "削弱",
                "neutral": "中性",
                "conflicted": "存在冲突",
                "not_available": "不可用",
            },
            "tradingview.chart_basis.trendline_status": {
                "intact": "保持有效",
                "broken": "已破坏",
                "ambiguous": "不明确",
                "not_available": "不可用",
            },
            "maker.entry_type": {
                "left": "左侧",
                "right": "右侧",
                "not_applicable": "不适用",
            },
        }
        self.assertEqual(compiler.VISIBLE_ENUM_CN_BY_DOMAIN, expected)
        for domain, values in expected.items():
            for raw, projected in values.items():
                with self.subTest(domain=domain, raw=raw):
                    self.assertEqual(
                        compiler._visible_enum(domain, raw),
                        projected,
                    )
        with self.assertRaisesRegex(ValueError, "unknown human-visible enum domain"):
            compiler._visible_enum("unknown.domain", "left")
        for value in (None, True, ["left"], " left", "left ", "LEFT", "unknown"):
            with self.subTest(invalid_value=value):
                with self.assertRaisesRegex(ValueError, "outside the closed domain"):
                    compiler._visible_enum("maker.entry_type", value)
        self.assertEqual(compiler._metric_value("CVD"), "CVD")
        self.assertEqual(compiler._metric_value("bearish"), "偏空")
        with self.assertRaisesRegex(
            ValueError,
            "lacks a deterministic translation",
        ):
            compiler._metric_value("future_unknown_enum")

    def test_orderflow_method_keeps_each_source_in_its_role(self) -> None:
        method = compiler.ORDERFLOW_DIRECTION_METHOD_CN
        self.assertIn("价格、CVD 与 OI 形成主体主判", method)
        self.assertIn("资金费率只修正强度", method)
        self.assertIn("Exocharts 只作确认、削弱或反证", method)
        self.assertIn("不得单变量翻向", method)

        self.assertIn("不承担盘口方向", compiler.SOURCE_BOUNDARY_CN["Coinglass"])
        self.assertIn("不得另起方向或单方翻向", compiler.SOURCE_BOUNDARY_CN["Exocharts"])

    def test_fundamental_events_bind_sealed_rank_hash_and_typed_owners(self) -> None:
        hashes = ["a" * 64, "b" * 64, "c" * 64]
        cards = [
            {
                "source_event_sha256": event_hash,
                "time": f"7/18 0{index}:00",
                "title": f"重要事件{index}",
                "body": f"本轮封存事件事实{index}只来自结构化卡片。",
            }
            for index, event_hash in enumerate(hashes, start=1)
        ]
        event_claims = [
            {
                "id": f"claim.event.{index}",
                "claim_type": "fundamental_event_realization",
                "account": "shared",
                "selected_event_sha256": event_hash,
                "realization_state": state,
            }
            for index, (event_hash, state) in enumerate(
                zip(
                    hashes,
                    ("realized", "partially_realized", "conflicted"),
                    strict=True,
                ),
                start=1,
            )
        ]
        reasoning = {
            "observations": [
                {
                    "id": "obs.bb",
                    "source": "BlockBeats",
                    "metrics": {"selected_event_sha256": hashes},
                }
            ],
            "claims": [
                {
                    "id": "claim.orderflow",
                    "claim_type": "orderflow_interpretation",
                    "account": "shared",
                },
                {
                    "id": "claim.chart",
                    "claim_type": "chart_interpretation",
                    "account": "shared",
                },
                *event_claims,
                {
                    "id": "claim.main.sentinel",
                    "claim_type": "strongest_counterevidence",
                    "account": "main",
                    "conclusion": "MAIN-SENTINEL-MUST-NOT-PROJECT",
                },
            ],
            "methodology": {
                "fundamental_event_assessments": [
                    {
                        "selected_event_sha256": event_hash,
                        "impact_channel": channel,
                        "expected_effect": effect,
                        "realization_claim_id": f"claim.event.{index}",
                        "counter_claim_ids": ["claim.orderflow", "claim.chart"],
                        "boundary_code": "no_standalone_direction_requires_cross_source_realization",
                    }
                    for index, (event_hash, channel, effect) in enumerate(
                        zip(
                            hashes,
                            ("liquidity", "regulation", "risk_appetite"),
                            (
                                "supportive_for_risk_assets",
                                "two_sided_or_conditional",
                                "adverse_for_risk_assets",
                            ),
                            strict=True,
                        ),
                        start=1,
                    )
                ]
            },
        }
        policy = compiler.load_scoring_policy()["gold_methodology"][
            "fundamental_event_assessment_policy"
        ]

        projected = compiler._typed_fundamental_event_projections(
            reasoning,
            cards,
            event_policy=policy,
        )
        self.assertEqual(
            [item["selected_event_sha256"] for item in projected], hashes
        )
        self.assertEqual(
            [item["realization_state"] for item in projected],
            ["realized", "partially_realized", "conflicted"],
        )
        self.assertNotIn(
            "MAIN-SENTINEL-MUST-NOT-PROJECT",
            json.dumps(projected, ensure_ascii=False),
        )

        reordered = copy.deepcopy(reasoning)
        reordered["methodology"]["fundamental_event_assessments"].reverse()
        reordered["claims"][2:5] = reversed(reordered["claims"][2:5])
        reordered_projection = compiler._typed_fundamental_event_projections(
            reordered,
            cards,
            event_policy=policy,
        )
        self.assertEqual(
            [item["selected_event_sha256"] for item in reordered_projection], hashes
        )

        mismatched = copy.deepcopy(reasoning)
        mismatched["claims"][2]["selected_event_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "cover the sealed event hashes"):
            compiler._typed_fundamental_event_projections(
                mismatched,
                cards,
                event_policy=policy,
            )

        missing_counter = copy.deepcopy(reasoning)
        missing_counter["methodology"]["fundamental_event_assessments"][0][
            "counter_claim_ids"
        ] = []
        with self.assertRaisesRegex(ValueError, "invalid counter_claim_ids"):
            compiler._typed_fundamental_event_projections(
                missing_counter,
                cards,
                event_policy=policy,
            )

    def test_source_explanations_project_triad_funding_and_footprint_separately(self) -> None:
        reasoning = {
            "observations": [
                {
                    "id": "obs_bb",
                    "source": "BlockBeats",
                    "fact": "本轮事件已按影响层级筛选。",
                    "metrics": {
                        "tier": 2,
                        "event_window_hours": 12,
                        "selected_event_count": 3,
                        "selected_event_sha256": ["a" * 64, "b" * 64, "c" * 64],
                    },
                },
                {
                    "id": "obs_cg",
                    "source": "Coinglass",
                    "fact": "同一价格主腿的结构化盘口事实已认证。",
                    "metrics": {
                        "combination_id": "C80",
                        "price_direction": "down",
                        "cvd_direction": "down",
                        "oi_direction": "down",
                        "main_triad_direction": "bearish",
                        "funding_direction": "down",
                        "funding_sign": "negative",
                        "funding_effect": "weaken",
                        "pivot": {
                            "timeframe": "1h",
                            "start_price": 104,
                            "end_price": 100,
                            "dominant_leg": "down",
                            "trendline_status": "intact",
                            "anchor_reset": False,
                        },
                        "effect_divergence": {
                            "cvd_break": "lower_low",
                            "price_confirmation": "confirmed",
                            "interpretation": "none",
                        },
                        "price_break_status": "new_low_or_breakdown",
                        "oi_price_context": "position_reduction",
                        "final_direction": "bearish",
                    },
                },
                {
                    "id": "obs_exo",
                    "source": "Exocharts",
                    "fact": "足迹只对主体盘口结论进行交叉核验。",
                    "metrics": {
                        "capture_profile": {
                            "exchange": "Bybit",
                            "symbol": "BTCUSD",
                            "timeframe": "D",
                            "tick_multiplier": 120,
                            "cluster_type": "Bid-Ask Profile",
                            "text_type": "Imbalance",
                            "candle_type": "None",
                        },
                        "ohlc": {"open": 100, "high": 104, "low": 99, "close": 103},
                        "poc": 102,
                        "delta": -12,
                        "cvd": -24,
                        "volume": 1200,
                        "cross_check_result": "contradict",
                    },
                },
                {"id": "obs_fw", "source": "FedWatch", "fact": "宏观概率环境已认证。", "metrics": {}},
                {"id": "obs_fs", "source": "Farside", "fact": "ETF 现货侧数据已认证。", "metrics": {}},
                {
                    "id": "obs_tv",
                    "source": "TradingView",
                    "fact": "多周期结构与手绘区域已认证。",
                    "metrics": {
                        "timeframes": {
                            "1d": {"price": 100, "sma20": 101, "structure": "bearish"},
                            "4h": {"price": 100, "sma20": 102, "structure": "bearish"},
                            "1h": {"price": 100, "sma20": 103, "structure": "bearish"},
                            "15m": {"price": 100, "sma20": None, "structure": "range"},
                        },
                        "volume_profile": {
                            "source_mode": "user_drawn_manual_only",
                            "status": "readable",
                            "platform_indicator_state": "hidden",
                            "platform_vrvp_used": False,
                            "automated_values_used": False,
                            "zones": [
                                {
                                    "lower_bound": 98,
                                    "upper_bound": 99,
                                    "timeframe": "1h",
                                    "role": "value_area",
                                }
                            ],
                        },
                    },
                },
            ],
            "claims": [],
        }

        reasoning["observations"][3]["metrics"].update(
            {
                "data_as_of": "2026-07-16T06:00:00-05:00",
                "next_fomc_date": "2026-07-29",
                "current_probabilities": {"hold": 65, "hike_25bp": 35},
                "change_1d": {"hold": -2, "hike_25bp": 2},
                "change_1w": {"hold": -6, "hike_25bp": 6},
                "change_1m": {"hold": -12, "hike_25bp": 12},
            }
        )
        explanations = compiler._source_explanations(
            reasoning,
            fedwatch_outcome_pattern=self.fedwatch_outcome_pattern(),
        )
        coinglass = explanations["Coinglass"]["fact"]
        exocharts = explanations["Exocharts"]["fact"]

        self.assertIn("主体三项=价格下降、CVD下降、OI下降，主判偏空", coinglass)
        self.assertIn("资金费率下降（负值），仅作削弱修正", coinglass)
        self.assertIn("对主体主判的交叉核验=反证", exocharts)

        fedwatch = explanations["FedWatch"]["fact"]
        self.assertIn("Data as of", fedwatch)
        self.assertIn("1日边际=", fedwatch)
        self.assertIn("1周边际=", fedwatch)
        self.assertIn("1月边际=", fedwatch)
        self.assertIn("+2个百分点", fedwatch)
        self.assertIn("OHLC=100/104/99/103", exocharts)
        self.assertIn("POC=102", exocharts)
        self.assertIn("Delta=-12", exocharts)
        self.assertIn("CVD=-24", exocharts)
        self.assertIn("Volume=1200", exocharts)

        blockbeats = explanations["BlockBeats"]["fact"]
        self.assertIn("事件影响层级=T2", blockbeats)
        self.assertIn("入选重要事件3条", blockbeats)

        self.assertIn("1H pivot=104→100", coinglass)
        self.assertIn("主腿=下降", coinglass)
        self.assertIn("是否重置新锚=否", coinglass)
        self.assertIn("价格突破状态=创新低或下破", coinglass)
        self.assertIn("OI×价格语义=持仓收缩", coinglass)

        tradingview = explanations["TradingView"]["fact"]
        self.assertIn("1D价格=100、SMA20=101、结构=偏空", tradingview)
        self.assertIn("15m价格=100、SMA20=未提供（15m非必需）、结构=震荡", tradingview)
        self.assertIn("认证手绘区间=98-99（1H；手绘价值区域）", tradingview)
        self.assertIn("平台内置相关指标已隐藏，用户手绘区间已认证可读", tradingview)

        profile = reasoning["observations"][5]["metrics"]["volume_profile"]
        profile.update(
            {
                "status": "insufficient",
                "platform_indicator_state": "visible",
                "zones": [],
                "reason": "RAW-NARRATIVE-MUST-NOT-RENDER",
            }
        )
        insufficient_projection = compiler._source_explanations(
            reasoning,
            fedwatch_outcome_pattern=self.fedwatch_outcome_pattern(),
        )["TradingView"]
        insufficient = insufficient_projection["fact"]
        self.assertIn("认证手绘区间=无认证手绘区间", insufficient)
        self.assertIn(
            "平台内置相关指标仍可见，用户手绘证据维度不得认证并按0分处理",
            insufficient,
        )
        self.assertNotIn("RAW-NARRATIVE-MUST-NOT-RENDER", insufficient)
        self.assertIn(
            "平台内置相关指标仍可见，用户手绘证据维度不得认证并按0分处理",
            insufficient_projection["decision_value"],
        )
        self.assertNotIn("保持隐藏", insufficient_projection["decision_value"])

    def test_chart_structure_zones_do_not_reuse_manual_profile_zones(self) -> None:
        reasoning = {
            "observations": [
                {
                    "id": "obs_cg",
                    "source": "Coinglass",
                    "metrics": {
                        "combination_id": "C52",
                        "price_direction": "down",
                        "cvd_direction": "down",
                        "oi_direction": "down",
                        "funding_direction": "neutral",
                        "funding_sign": "neutral",
                        "funding_effect": "neutral",
                    },
                },
                {
                    "id": "obs_exo",
                    "source": "Exocharts",
                    "metrics": {"cross_check_result": "confirm"},
                },
                {
                    "id": "obs_tv",
                    "source": "TradingView",
                    "metrics": {
                        "timeframes": {
                            "1d": {"price": 100, "sma20": 101, "structure": "bearish"},
                            "4h": {"price": 100, "sma20": 102, "structure": "bearish"},
                            "1h": {"price": 100, "sma20": 103, "structure": "bearish"},
                            "15m": {"price": 100, "sma20": None, "structure": "range"},
                        },
                        "volume_profile": {
                            "status": "readable",
                            "zones": [{"lower_bound": 61500, "upper_bound": 64400, "timeframe": "1d"}],
                        },
                        "chart_basis": {
                            "support_levels": [97],
                            "resistance_levels": [104],
                            "structure_zones": [{"lower_bound": 90, "upper_bound": 91, "timeframe": "4h"}],
                            "volume_price_state": "weaken",
                            "fibonacci_levels": [96],
                            "trendline_status": "intact",
                        },
                    },
                },
            ],
            "claims": [],
        }
        maker = self.complete_scoring_contract(
            reasoning,
            maker={
                "direction": "short",
                "plan_state": "qualified",
                "orderflow_score": 52,
                "chart_score": 24,
            },
        )
        projected = compiler._typed_scoring_explanations(reasoning, maker=maker)
        support = projected["chart"]["chart.support_resistance"]
        profile = projected["chart"]["chart.liquidity_hunt"]
        self.assertIn("结构区间=90-91(4H)", support)
        self.assertNotIn("61500-64400", support)
        self.assertIn("认证区间=61500-64400(1D)", profile)
        self.assertNotIn("90-91", profile)
        strict_pattern = report_lint.load_timeframe_display_pattern(
            Path(compiler.__file__).resolve().parents[1]
            / "governance"
            / "vnext_report_presentation_contract.json"
        )
        self.assertEqual(
            report_lint.liquidity_check(
                [profile],
                period_pattern=strict_pattern,
            ),
            [],
        )
        self.assertIn("盘口轴", projected["winrate_anchor"])
        self.assertIn("结构位置轴", projected["winrate_anchor"])
        self.assertIn("不读取计划状态", projected["winrate_anchor"])
        self.assertEqual(projected["winrate_anchor"].count("不读取计划状态"), 1)
        self.assertNotIn("及计划状态", projected["winrate_anchor"])
        self.assertIn("全部类型化当前基线条款", projected["counter_resolution"])

        unavailable = copy.deepcopy(reasoning)
        unavailable_basis = unavailable["observations"][2]["metrics"]["chart_basis"]
        unavailable_basis["volume_price_state"] = "not_available"
        unavailable_basis["trendline_status"] = "not_available"
        unavailable_basis["fibonacci_levels"] = []
        unavailable_projection = compiler._typed_scoring_explanations(
            unavailable,
            maker=maker,
        )
        unavailable_text = json.dumps(
            unavailable_projection,
            ensure_ascii=False,
        )
        self.assertIn(
            "TradingView量价状态=不可用",
            unavailable_projection["chart"]["chart.volume_price"],
        )
        self.assertIn(
            "趋势线状态=不可用",
            unavailable_projection["chart"]["chart.fibonacci_trendline"],
        )
        self.assertNotIn("not_available", unavailable_text)

        invalid_domain_value = copy.deepcopy(unavailable)
        invalid_domain_value["observations"][2]["metrics"]["chart_basis"][
            "trendline_status"
        ] = "future_state"
        with self.assertRaisesRegex(
            ValueError,
            "tradingview.chart_basis.trendline_status",
        ):
            compiler._typed_scoring_explanations(
                invalid_domain_value,
                maker=maker,
            )

        injected_anchor = copy.deepcopy(maker)
        injected_anchor["winrate_rubric"]["anchor_rationale"] = (
            "机构现货持续买入且鲸鱼托底，因此采用更高基准锚。"
        )
        with self.assertRaisesRegex(ValueError, "authority-owned canonical"):
            compiler._typed_scoring_explanations(
                reasoning, maker=injected_anchor
            )

        missing_resolution = copy.deepcopy(maker)
        del missing_resolution["winrate_rubric"]["counter_resolution"]
        with self.assertRaisesRegex(ValueError, "closed schema"):
            compiler._typed_scoring_explanations(
                reasoning, maker=missing_resolution
            )

        partial_resolution = copy.deepcopy(maker)
        partial_resolution["winrate_rubric"]["counter_resolution"][
            "residual_clause_indexes"
        ] = []
        with self.assertRaisesRegex(ValueError, "residual clause indexes are invalid"):
            compiler._typed_scoring_explanations(
                reasoning, maker=partial_resolution
            )

    def test_winrate_adjustments_bind_true_claim_sources_without_model_narrative(self) -> None:
        reasoning = {
            "observations": [
                {"id": "obs_cg", "source": "Coinglass", "metrics": {}},
                {"id": "obs_exo", "source": "Exocharts", "metrics": {"cross_check_result": "confirm"}},
                {"id": "obs_farside", "source": "Farside", "metrics": {}},
                {
                    "id": "obs_tv",
                    "source": "TradingView",
                    "metrics": {
                        "timeframes": {
                            key: {"price": 100, "sma20": 101, "structure": "bearish"}
                            for key in ("1d", "4h", "1h", "15m")
                        },
                        "volume_profile": {"status": "insufficient", "zones": []},
                        "chart_basis": {
                            "support_levels": [],
                            "resistance_levels": [],
                            "structure_zones": [],
                            "volume_price_state": "not_available",
                            "fibonacci_levels": [],
                            "trendline_status": "not_available",
                        },
                    },
                },
            ],
            "claims": [
                {
                    "id": "cl_orderflow",
                    "claim_type": "orderflow_interpretation",
                    "conclusion": "日线足迹确认同锚盘口。",
                    "support_ids": ["obs_cg", "obs_exo"],
                },
                {
                    "id": "cl_etf",
                    "claim_type": "etf_confirmation",
                    "conclusion": "ETF净流入削弱偏空延续。",
                    "price_relation": "weaken",
                    "support_ids": ["obs_cg", "obs_farside"],
                },
            ],
        }
        maker = self.complete_scoring_contract(
            reasoning,
            maker={
                "direction": "short",
                "plan_state": "qualified",
                "orderflow_score": 52,
                "chart_score": 24,
            },
            orderflow_claim_id="cl_orderflow",
            extra_adjustments=[
                {
                    "reason_code": "etf_weaken",
                    "label": "自由文本不得投影",
                    "delta": -3,
                    "claim_ids": ["cl_etf"],
                    "rationale": "自由文本不得投影",
                }
            ],
        )
        projected = compiler._typed_scoring_explanations(
            reasoning, maker=maker
        )["winrate_adjustments"]
        self.assertEqual(projected[0]["source_binding"], ["TradingView"])
        self.assertEqual(projected[1]["source_binding"], ["Coinglass", "Farside"])
        self.assertIn("Maker当前最强反证残余", projected[0]["explanation"])
        self.assertIn("ETF现货削弱", projected[1]["explanation"])
        self.assertNotIn("自由文本不得投影", "".join(item["explanation"] for item in projected))

        reordered = copy.deepcopy(maker)
        reordered["winrate_rubric"]["adjustments"].reverse()
        with self.assertRaisesRegex(ValueError, "strongest-counter adjustment must be first"):
            compiler._typed_scoring_explanations(reasoning, maker=reordered)

        unreachable = copy.deepcopy(reasoning)
        next(
            claim
            for claim in unreachable["claims"]
            if claim["id"] == "cl_orderflow"
        )["support_ids"] = ["obs_cg"]
        with self.assertRaisesRegex(ValueError, "anchor axis lacks required sources"):
            compiler._typed_scoring_explanations(unreachable, maker=maker)

    def test_source_metrics_recursive_allowlist_drops_unknown_nested_keys(self) -> None:
        sentinel = "NARRATIVE-SECOND-TRUTH"
        zone = {
            "lower_bound": 98,
            "upper_bound": 100,
            "timeframe": "1h",
            "role": "value_area",
            "extra": sentinel,
        }
        observations = [
            {
                "source": "BlockBeats",
                "metrics": {
                    "tier": 2,
                    "event_window_hours": 12,
                    "selected_event_count": 1,
                    "selected_event_sha256": ["a" * 64],
                    "extra": sentinel,
                },
            },
            {
                "source": "Coinglass",
                "metrics": {
                    "pivot": {
                        "timeframe": "1h",
                        "start_price": 100,
                        "end_price": 99,
                        "dominant_leg": "down",
                        "trendline_status": "intact",
                        "anchor_reset": False,
                        "extra": sentinel,
                    },
                    "effect_divergence": {
                        "cvd_break": "lower_low",
                        "price_confirmation": "confirmed",
                        "interpretation": "none",
                        "extra": sentinel,
                    },
                    "liquidation_map": {
                        "role": "auxiliary_only",
                        "threshold": 0.85,
                        "captured_timeframes": ["48h"],
                        "current_price": 99,
                        "levels": [{
                            "side": "above",
                            "price": 101,
                            "timeframe": "48h",
                            "strength": "strong",
                            "extra": sentinel,
                        }],
                        "extra": sentinel,
                    },
                    "extra": sentinel,
                },
            },
            {
                "source": "Exocharts",
                "metrics": {
                    "capture_profile": {
                        "exchange": "Bybit",
                        "symbol": "BTCUSD",
                        "timeframe": "D",
                        "tick_multiplier": 120,
                        "cluster_type": "Bid-Ask Profile",
                        "text_type": "Imbalance",
                        "candle_type": "None",
                        "fpbs_enabled": True,
                        "vwap_enabled": True,
                        "extra": sentinel,
                    },
                    "ohlc": {
                        "open": 100,
                        "high": 101,
                        "low": 98,
                        "close": 99,
                        "extra": sentinel,
                    },
                    "extra": sentinel,
                },
            },
            {
                "source": "FedWatch",
                "metrics": {
                    "data_as_of": "2026-07-16T06:00:00-05:00",
                    "next_fomc_date": "2026-07-29",
                    "current_probabilities": {"hold": 75, "hike_25bp": 25},
                    "change_1d": {"hold": 0, "hike_25bp": 0},
                    "change_1w": {"hold": 0, "hike_25bp": 0},
                    "change_1m": {"hold": 0, "hike_25bp": 0},
                    "extra": sentinel,
                },
            },
            {
                "source": "Farside",
                "metrics": {
                    "latest_complete_date": "2026-07-15",
                    "latest_total_usd_m": 1,
                    "flow_direction": "inflow",
                    "extra": sentinel,
                },
            },
            {
                "source": "TradingView",
                "metrics": {
                    "timeframes": {
                        key: {
                            "price": 99,
                            "sma20": 100,
                            "structure": "bearish",
                            "extra": sentinel,
                        }
                        for key in ("1d", "4h", "1h", "15m")
                    },
                    "volume_profile": {
                        "source_mode": "user_drawn_manual_only",
                        "status": "readable",
                        "platform_indicator_state": "hidden",
                        "platform_vrvp_used": False,
                        "automated_values_used": False,
                        "zones": [copy.deepcopy(zone)],
                        "reason": sentinel,
                        "extra": sentinel,
                    },
                    "chart_basis": {
                        "support_levels": [98],
                        "resistance_levels": [100],
                        "structure_zones": [copy.deepcopy(zone)],
                        "volume_price_state": "confirm",
                        "fibonacci_levels": [99],
                        "trendline_status": "intact",
                        "extra": sentinel,
                    },
                    "chart_component_scores": {
                        "chart.support_resistance": 1,
                        "chart.liquidity_hunt": 1,
                        "chart.sma20_interaction": 1,
                        "chart.volume_price": 1,
                        "chart.fibonacci_trendline": 1,
                        "extra": sentinel,
                    },
                    "chart_scoring_basis": {
                        "included_timeframes": ["1d", "4h", "1h"],
                        "excluded_timeframes": ["15m"],
                        "fifteen_minute_role": "maker_entry_only",
                        "extra": sentinel,
                    },
                    "extra": sentinel,
                },
            },
        ]
        projected = compiler._source_metrics(
            {"observations": observations},
            fedwatch_outcome_pattern=self.fedwatch_outcome_pattern(),
        )
        self.assertNotIn(sentinel, json.dumps(projected, ensure_ascii=False))
        self.assertEqual(
            set(projected["Coinglass"]["pivot"]),
            {
                "timeframe",
                "start_price",
                "end_price",
                "dominant_leg",
                "trendline_status",
                "anchor_reset",
            },
        )
        self.assertEqual(
            set(projected["TradingView"]["volume_profile"]["zones"][0]),
            {"lower_bound", "upper_bound", "timeframe", "role"},
        )

    def test_fedwatch_outcome_projection_is_closed_and_human_labeled(self) -> None:
        pattern = self.fedwatch_outcome_pattern()
        with self.assertRaisesRegex(ValueError, "uncertified FedWatch"):
            compiler._project_fedwatch_numeric_map(
                {"Maker委托价63960": 100},
                outcome_pattern=pattern,
            )
        with self.assertRaisesRegex(ValueError, "uncertified FedWatch"):
            compiler._project_fedwatch_numeric_map(
                {"cut_gt_50bp": 100},
                outcome_pattern=pattern,
            )
        self.assertEqual(compiler._fedwatch_outcome_label("hold"), "维持利率")
        self.assertEqual(compiler._fedwatch_outcome_label("cut_25bp"), "降息25bp")
        self.assertEqual(compiler._fedwatch_outcome_label("hike_50bp"), "加息50bp")
        self.assertEqual(compiler._fedwatch_outcome_label("cut_gt_25bp"), "降息超过25bp")
        self.assertEqual(compiler._fedwatch_outcome_label("hike_gt_25bp"), "加息超过25bp")
        self.assertEqual(compiler._fedwatch_outcome_label("other_unlisted"), "其他未列出结果")
        rendered = compiler._fedwatch_map_text(
            {
                "cut_gt_25bp": 3,
                "cut_25bp": 12,
                "hold": 70,
                "hike_25bp": 10,
                "hike_gt_25bp": 2,
                "other_unlisted": 3,
            },
            outcome_pattern=pattern,
            signed_delta=False,
        )
        for label in (
            "降息超过25bp=3%",
            "降息25bp=12%",
            "维持利率=70%",
            "加息25bp=10%",
            "加息超过25bp=2%",
            "其他未列出结果=3%",
        ):
            self.assertIn(label, rendered)
        self.assertEqual(
            rendered,
            "降息超过25bp=3%、降息25bp=12%、维持利率=70%、"
            "加息25bp=10%、加息超过25bp=2%、其他未列出结果=3%",
        )

    def test_typed_maker_audit_projections_are_closed(self) -> None:
        sentinel = "NARRATIVE-SECOND-TRUTH"
        nonconstructible = {
            "plan_constructible": False,
            "entry_reach_probability": 33,
            "entry_reach_probability_basis": {
                "applicability": "applicable",
                "claim_ids": ["claim_maker"],
                "reference_source": "TradingView",
                "reference_timeframe": "1h",
                "reference_price": 97,
                "reference_entry": 99,
                "entry_distance": 2,
                "reach_direction": "up_to_entry",
                "extra": sentinel,
            },
            "risk_plan": {
                "entries": [99, 100],
                "entry_allocations_pct": [50, 50],
                "stop_basis": {
                    "observation_id": "obs_tv",
                    "claim_id": "cl_invalidation_maker",
                    "timeframe": "4h",
                    "anchor_kind": "certified_resistance_level",
                    "anchor_source_field": "metrics.chart_basis.resistance_levels[0]",
                    "anchor_price": 100.5,
                    "buffer_basis_code": "current_run_typed_market_noise_allowance",
                    "buffer_claim_id": "cl_invalidation_maker",
                    "outward_buffer_price": 0.5,
                    "buffer_backsolved_from_risk": False,
                    "derived_stop": 101,
                },
                "stop": 101,
                "tp1": 98,
                "tp2": 97,
                "tp1_close_pct": 50,
                "tp2_close_pct": 50,
                "leverage": 5,
                "cancel_before_fill": 96,
                "fake_price": 63960,
                "extra": sentinel,
            },
            "defense_plan": {"extra": sentinel},
        }
        rejected_risk = compiler._typed_risk_plan(nonconstructible)
        self.assertEqual(
            rejected_risk["candidate_status"], "rejected_not_executable"
        )
        self.assertNotIn("fake_price", rejected_risk)
        self.assertNotIn(sentinel, json.dumps(rejected_risk, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "candidate defense plan is incomplete"):
            compiler._typed_defense_plan(nonconstructible)
        self.assertEqual(
            compiler._typed_entry_reach_probability_basis(nonconstructible),
            {
                "applicability": "applicable",
                "claim_ids": ["claim_maker"],
                "reference_source": "TradingView",
                "reference_timeframe": "1h",
                "reference_price": 97,
                "reference_entry": 99,
                "entry_distance": 2,
                "reach_direction": "up_to_entry",
            },
        )

        constructible = copy.deepcopy(nonconstructible)
        constructible.update(
            {
                "plan_constructible": True,
                "entry_reach_probability_basis": {
                    "applicability": "applicable",
                    "claim_ids": ["claim_maker"],
                    "reference_source": "TradingView",
                    "reference_timeframe": "1h",
                    "reference_price": 97,
                    "reference_entry": 99,
                    "entry_distance": 2,
                    "reach_direction": "up_to_entry",
                    "extra": sentinel,
                },
                "risk_plan": {
                    "entries": [99, 100],
                    "entry_allocations_pct": [50, 50],
                    "stop_basis": {
                        "observation_id": "obs_tv",
                        "claim_id": "cl_invalidation_maker",
                        "timeframe": "4h",
                        "anchor_kind": "certified_resistance_level",
                        "anchor_source_field": "metrics.chart_basis.resistance_levels[0]",
                        "anchor_price": 100.5,
                        "buffer_basis_code": "current_run_typed_market_noise_allowance",
                        "buffer_claim_id": "cl_invalidation_maker",
                        "outward_buffer_price": 0.5,
                        "buffer_backsolved_from_risk": False,
                        "derived_stop": 101,
                    },
                    "stop": 101,
                    "tp1": 98,
                    "tp2": 97,
                    "tp1_close_pct": 50,
                    "tp2_close_pct": 50,
                    "leverage": 5,
                    "cancel_before_fill": 96,
                    "extra": sentinel,
                },
                "defense_plan": {
                    "mode": "ladder_prefill_exact_scenarios",
                    "prefill_anchor": {
                        "kind": "planned_full_ladder_weighted_fill",
                        "weighted_fill": "99.5",
                        "is_actual_fill": False,
                        "is_single_entry": False,
                    },
                    "trigger_scenarios": [
                        {
                            "risk_scenario_id": "fill-1-2",
                            "filled_level_indexes": [1, 2],
                            "weighted_fill": "99.5",
                            "first_trigger_price_raw": "97.25",
                            "second_trigger_price_raw": "96.5",
                            "rounding_rule": "exact_no_rounding",
                            "rounding_step": None,
                            "first_trigger_price": "97.25",
                            "second_trigger_price": "96.5",
                        }
                    ],
                    "postfill_recalculation": {
                        "required": True,
                        "anchor": "actual_weighted_fill",
                        "replace_prefill_projection": True,
                    },
                    "first_stop_rule": "confirmed_post_fill_4h_structural_extreme",
                    "second_action": "move_stop_to_breakeven_only",
                    "extra": sentinel,
                },
            }
        )
        combined = json.dumps(
            {
                "basis": compiler._typed_entry_reach_probability_basis(constructible),
                "risk": compiler._typed_risk_plan(constructible),
                "defense": compiler._typed_defense_plan(constructible),
            },
            ensure_ascii=False,
        )
        self.assertNotIn(sentinel, combined)
        broken = copy.deepcopy(constructible)
        broken["defense_plan"].pop("second_action")
        with self.assertRaisesRegex(ValueError, "defense plan is incomplete"):
            compiler._typed_defense_plan(broken)

    def test_entry_reach_probability_projection_distinguishes_zero_from_na(self) -> None:
        applicable = {
            "entry_reach_probability": 0,
            "entry_reach_probability_basis": {
                "applicability": "applicable",
                "claim_ids": ["claim_maker"],
                "reference_source": "TradingView",
                "reference_timeframe": "1h",
                "reference_price": 97,
                "reference_entry": 99,
                "entry_distance": 2,
                "reach_direction": "up_to_entry",
            },
        }
        zero_projection = compiler._typed_entry_reach_probability_projection(
            applicable
        )
        self.assertEqual(zero_projection["value_pct"], 0)
        self.assertEqual(
            compiler._entry_reach_probability_display(zero_projection), "0%"
        )

        not_applicable = copy.deepcopy(applicable)
        not_applicable["entry_reach_probability"] = None
        not_applicable["entry_reach_probability_basis"].update(
            {
                "applicability": "not_applicable_no_certified_entry_geometry",
                "reference_entry": None,
                "entry_distance": None,
                "reach_direction": None,
            }
        )
        na_projection = compiler._typed_entry_reach_probability_projection(
            not_applicable
        )
        na_display = compiler._entry_reach_probability_display(na_projection)
        self.assertIn("不适用", na_display)
        self.assertNotIn("0%", na_display)

        for field, value in (
            ("reference_source", "Unknown"),
            ("reference_timeframe", "4h"),
            ("reference_price", 0),
        ):
            with self.subTest(field=field):
                poisoned = copy.deepcopy(not_applicable)
                poisoned["entry_reach_probability_basis"][field] = value
                with self.assertRaisesRegex(
                    ValueError, "positive certified TradingView 1h reference price"
                ):
                    compiler._typed_entry_reach_probability_projection(poisoned)

    def test_report_separates_price_reach_from_fill_viability(self) -> None:
        maker = {
            "order_lifecycle": {
                "schema_version": "maker-order-lifecycle-v1",
                "state": "cancel_blocks_all_entries",
                "legal_fill_path_exists": False,
                "legal_cancel_path_exists": True,
                "fill_probability": None,
                "fill_probability_applicability": "not_applicable_no_legal_fill_path",
                "reason_code": "cancel_blocks_all_entries",
            }
        }
        lifecycle = compiler._typed_order_lifecycle(maker)
        self.assertIn("没有可成交路径", compiler._order_lifecycle_display(lifecycle))
        self.assertIsNone(lifecycle["fill_probability"])

        poisoned = copy.deepcopy(maker)
        poisoned["order_lifecycle"]["fill_probability"] = 0
        with self.assertRaisesRegex(ValueError, "may not fabricate"):
            compiler._typed_order_lifecycle(poisoned)
        with self.assertRaisesRegex(ValueError, "may not fabricate"):
            compiler._order_lifecycle_display(poisoned["order_lifecycle"])

        poisoned = copy.deepcopy(maker)
        poisoned["order_lifecycle"][
            "fill_probability_applicability"
        ] = "not_estimated_lifecycle_only"
        with self.assertRaisesRegex(ValueError, "internally inconsistent"):
            compiler._typed_order_lifecycle(poisoned)
        with self.assertRaisesRegex(ValueError, "internally inconsistent"):
            compiler._order_lifecycle_display(poisoned["order_lifecycle"])

    def test_canonical_price_projection_keeps_arabic_digits(self) -> None:
        maker = {
            "direction": "long",
            "risk_plan": {
                "entries": [63960, 64120],
                "entry_allocations_pct": [50, 50],
                "stop_basis": {
                    "observation_id": "obs_tv",
                    "claim_id": "cl_invalidation_maker",
                    "timeframe": "4h",
                    "anchor_kind": "structure_zone_outer_boundary",
                    "anchor_source_field": "metrics.chart_basis.structure_zones[0].lower_bound",
                    "anchor_price": 63760,
                    "buffer_basis_code": "current_run_typed_market_noise_allowance",
                    "buffer_claim_id": "cl_invalidation_maker",
                    "outward_buffer_price": 10,
                    "buffer_backsolved_from_risk": False,
                    "derived_stop": 63750,
                },
                "stop": 63750,
                "tp1": 65050,
                "tp2": 65500,
                "tp1_close_pct": 50,
                "tp2_close_pct": 50,
                "cancel_before_fill": 64280,
            },
        }

        invalidation_claim = {
            "id": "cl_invalidation_maker",
            "structural_noise_buffer": {
                "schema_version": "structural-noise-buffer-v2",
                "status": "certified",
                "method_code": "pre_risk_tradingview_structure_noise_judgment",
                "observation_id": "obs_tv",
                "timeframe": "4h",
                "visual_evidence_ref": "evidence/tradingview_4h.png",
                "anchor_kind": "structure_zone_outer_boundary",
                "anchor_source_field": "metrics.chart_basis.structure_zones[0].lower_bound",
                "anchor_price": 63760,
                "noise_outer_boundary": 63755,
                "price_distance": 10,
                "risk_budget_input_used": False,
                "insufficiency_reason_code": None,
            },
        }
        projected = compiler._canonical_risk_frontstage(
            maker,
            invalidation_claim=invalidation_claim,
        )
        combined = "\n".join(projected.values())
        for number in ("63960", "64120", "63750", "65050", "65500", "64280"):
            with self.subTest(number=number):
                self.assertIn(number, combined)
        for chinese_price in ("六万三千九百六十", "六万四千一百二十", "六万五千五百"):
            with self.subTest(chinese_price=chinese_price):
                self.assertNotIn(chinese_price, combined)

        drifted_claim = copy.deepcopy(invalidation_claim)
        drifted_claim["structural_noise_buffer"]["price_distance"] = 1
        with self.assertRaisesRegex(ValueError, "reasoning-stage observation"):
            compiler._canonical_risk_frontstage(
                maker,
                invalidation_claim=drifted_claim,
            )

        for field, drifted_value in (
            ("observation_id", "obs_cg"),
            ("timeframe", "1h"),
        ):
            with self.subTest(field=field):
                drifted_claim = copy.deepcopy(invalidation_claim)
                drifted_claim["structural_noise_buffer"][field] = drifted_value
                with self.assertRaisesRegex(ValueError, "reasoning-stage observation"):
                    compiler._canonical_risk_frontstage(
                        maker,
                        invalidation_claim=drifted_claim,
                    )

    def test_constructibility_reason_projection_covers_stop_and_defense_failures(self) -> None:
        expected = {
            "structural_stop_invalid": "推理阶段预先密封的外扩缓冲",
            "defense_trigger_invalid": "完整分档情景的确定性计算",
        }
        for reason_code, marker in expected.items():
            with self.subTest(reason_code=reason_code):
                projected = compiler._canonical_execution_frontstage(
                    {
                        "plan_state": "observe",
                        "direction": "short",
                        "threshold_eligible": False,
                        "plan_constructible": False,
                        "position_notional_usdt": None,
                        "entry_type": "not_applicable",
                        "risk_plan": {},
                        "defense_plan": {},
                        "entry_reach_probability_basis": {
                            "applicability": "not_applicable_no_certified_entry_geometry",
                        },
                        "order_lifecycle": {
                            "state": "not_applicable_no_candidate_geometry",
                        },
                        "plan_constructibility": {
                            "status": "nonconstructible",
                            "primary_reason_code": reason_code,
                            "failure_codes": [reason_code],
                        },
                        "execution_action": "not_attempted",
                    },
                    {"plan_valid_until": "2026-07-18T23:59:59+08:00"},
                    run_mode="shadow",
                    authorization={},
                )
                self.assertIn(marker, projected["maker_execution"])
                self.assertNotIn("计划条件未完成认证", projected["maker_execution"])

    def test_defense_projection_exposes_exact_final_prices_and_audit_math(self) -> None:
        maker = {
            "plan_constructible": True,
            "direction": "short",
            "risk_plan": {
                "entries": [63960, 64120],
                "entry_allocations_pct": [50, 50],
                "stop": 64300,
            },
            "defense_plan": {
                "mode": "ladder_prefill_exact_scenarios",
                "prefill_anchor": {
                    "kind": "planned_full_ladder_weighted_fill",
                    "weighted_fill": "64040",
                    "is_actual_fill": False,
                    "is_single_entry": False,
                },
                "trigger_scenarios": [
                    {
                        "risk_scenario_id": "fill-1-2",
                        "filled_level_indexes": [1, 2],
                        "weighted_fill": "64040",
                        "first_trigger_price_raw": "63650",
                        "second_trigger_price_raw": "63520",
                        "rounding_rule": "nearest_step_half_up",
                        "rounding_step": "10",
                        "first_trigger_price": "63650",
                        "second_trigger_price": "63520",
                    }
                ],
                "postfill_recalculation": {
                    "required": True,
                    "anchor": "actual_weighted_fill",
                    "replace_prefill_projection": True,
                },
                "first_stop_rule": "confirmed_post_fill_4h_structural_extreme",
                "second_action": "move_stop_to_breakeven_only",
            },
        }
        defense = compiler._typed_defense_plan(maker)
        front = compiler._canonical_defense_frontstage(maker, slot="evening")
        audit = "\n".join(compiler._defense_calculation_audit_lines(defense))
        self.assertIn("第一层预成交投影价为63650", front["defense_first"])
        self.assertIn("第二层预成交投影价为63520", front["defense_second"])
        self.assertIn("不是实际成交价，也不是单档价", front["defense_first"])
        self.assertIn("实际成交后按实际加权成交价重新计算并替换", front["defense_first"])
        self.assertIn("L1原始值63650", audit)
        self.assertIn("按价格步长10", audit)
        self.assertIn("最终L2=63520", audit)
        self.assertNotIn("+/-", json.dumps({"front": front, "audit": audit}, ensure_ascii=False))


class ReportCompilerV5ClosedProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = workflow_fixtures.VNextWorkflowTests(
            "test_shadow_complete_releases_active_and_allows_next_run"
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def build_model(
        self,
        *,
        evidence_mutator=None,
        reasoning_mutator=None,
        decision_mutator=None,
    ) -> dict:
        evidence = self.fixture.evidence()
        evidence["schema_version"] = "evidence-snapshot-v2"
        evidence["sources"]["FedWatch"]["meta"] = copy.deepcopy(CME_PROVIDER_META)
        if evidence_mutator is not None:
            evidence_mutator(evidence)
        reasoning = self.fixture.reasoning(evidence)
        if reasoning_mutator is not None:
            reasoning_mutator(reasoning)
        reasoning["reasoning_sha256"] = compiler.reasoning_model_sha256(reasoning)
        decision = self.fixture.decision(reasoning)
        if decision_mutator is not None:
            decision_mutator(decision)
        methodology = json.loads(
            (self.fixture.run_root / "methodology_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        return compiler.build_canonical_report_model(
            evidence=evidence,
            reasoning=reasoning,
            decision=decision,
            methodology_sha256=methodology["manifest_sha256"],
            report_contract_sha256="a" * 64,
            root=self.fixture.root,
        )

    @staticmethod
    def make_directional_thesis_only(decision: dict) -> None:
        maker = decision["maker"]
        maker.update(
            {
                "plan_state": "observe",
                "threshold_eligible": False,
                "plan_constructible": False,
                "entry_type": "not_applicable",
                "position_notional_usdt": None,
                "entry_reach_probability": None,
                "risk_plan": {},
                "defense_plan": {},
            }
        )
        maker["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "no_certified_entry_zone",
                "failure_codes": ["no_certified_entry_zone"],
                "entry_zone_basis": None,
            }
        )
        maker["entry_reach_probability_basis"].update(
            {
                "applicability": "not_applicable_no_certified_entry_geometry",
                "reference_entry": None,
                "entry_distance": None,
                "reach_direction": None,
            }
        )
        maker["order_lifecycle"] = {
            "schema_version": "maker-order-lifecycle-v1",
            "state": "not_applicable_no_candidate_geometry",
            "legal_fill_path_exists": False,
            "legal_cancel_path_exists": False,
            "fill_probability": None,
            "fill_probability_applicability": "not_applicable_no_candidate_geometry",
            "reason_code": "not_applicable_no_candidate_geometry",
        }

    @staticmethod
    def make_non_directional_reasoning(reasoning: dict) -> None:
        claims = {item["id"]: item for item in reasoning["claims"]}
        claims["claim_maker"].update(
            {
                "direction": "observe",
                "conclusion": "Maker 当前没有方向性执行结论，只保持观察",
                "invalidation": "出现一组闭合且一致的方向性替代证据后重新评估",
            }
        )
        claims["claim_cannot"].update(
            {
                "prohibition": "追多空",
                "conclusion": "Maker 本轮不能追多或追空，只能保持观察",
            }
        )
        claims["claim_invalidation_maker"]["structural_noise_buffer"].update(
            {
                "status": "insufficient",
                "anchor_kind": None,
                "anchor_source_field": None,
                "anchor_price": None,
                "noise_outer_boundary": None,
                "price_distance": None,
                "insufficiency_reason_code": "not_applicable_non_directional_thesis",
            }
        )
        reasoning["pipeline_units"] = workflow_fixtures.build_pipeline_units(
            reasoning
        )

    @classmethod
    def make_non_directional_observation(cls, decision: dict) -> None:
        cls.make_directional_thesis_only(decision)
        maker = decision["maker"]
        maker.update(
            {
                "direction": "observe",
                "strategy_type": "观望",
                "cannot_do_code": "追多空",
            }
        )
        maker["plan_constructibility"].update(
            {
                "primary_reason_code": "non_directional_thesis",
                "failure_codes": ["non_directional_thesis"],
            }
        )

    @staticmethod
    def make_main_observe(decision: dict) -> None:
        main = decision["main_account"]
        main.update(
            {
                "plan_state": "observe",
                "action": "observe",
                "position_notional_usdt": None,
                "leverage": None,
                "entry_mode": None,
                "entry_zone_basis": None,
                "entries": [],
                "entry_allocations_pct": [],
                "stop_basis": None,
                "stop": None,
                "tp1": None,
                "final_take_profit": None,
                "tp1_close_pct": None,
                "plan_state_reason_code": "no_typed_plan",
            }
        )

    def build_no_candidate_model(self, semantic_state: str) -> dict:
        if semantic_state == "directional_thesis_only":
            return self.build_model(
                decision_mutator=self.make_directional_thesis_only,
            )
        if semantic_state == "non_directional_observation":
            return self.build_model(
                reasoning_mutator=self.make_non_directional_reasoning,
                decision_mutator=self.make_non_directional_observation,
            )
        raise ValueError(f"unsupported no-candidate semantic state: {semantic_state}")

    def test_shadow_qualified_disclosure_rejects_observe_semantic_padding(
        self,
    ) -> None:
        model = self.build_model()
        self.assertEqual(model["maker_summary"]["plan_state"], "qualified")
        poisoned = copy.deepcopy(model)
        poisoned["frontstage"]["maker_continuity"] += (
            "；影子观察状态；本轮观察结论有效至2099-01-01T00:00:00+08:00"
        )
        depth = compiler.evaluate_human_reasoning_depth(
            poisoned,
            contract=compiler.load_presentation_contract(self.fixture.root),
        )
        self.assertFalse(depth["passed"])
        self.assertIn(
            "report_projection.shadow_semantic_state_conflict",
            {item["code"] for item in depth["defects"]},
        )

    def test_v5_compiler_does_not_consume_free_report_sections(self) -> None:
        sentinel = "REPORT-SECTIONS-MUST-NEVER-BECOME-A-SECOND-TRUTH"
        with self.assertRaisesRegex(ValueError, "reasoning-model-v5 typed field set"):
            self.build_model(
                reasoning_mutator=lambda reasoning: reasoning.__setitem__(
                    "report_sections",
                    {
                        "strategy": {
                            "text": sentinel,
                            "claim_ids": ["claim_main"],
                        }
                    },
                )
            )

    def test_report_v11_projects_cme_provider_from_sealed_evidence_meta(self) -> None:
        model = self.build_model(
            evidence_mutator=lambda evidence: evidence["sources"]["FedWatch"][
                "meta"
            ].__setitem__("provider_name", "UNTRUSTED DISPLAY NAME")
        )
        self.assertEqual(model["schema_version"], "canonical-report-model-v11")
        provider = model["audit"]["rate_expectation_provider"]
        self.assertEqual(provider["provider_id"], "cme_fedwatch_ui")
        self.assertEqual(provider["display_name"], "CME FedWatch（官方主源）")
        self.assertFalse(provider["observation_only"])
        rendered = compiler.render_combined_markdown(model)
        self.assertIn("CME FedWatch（官方主源）", rendered)
        self.assertNotIn("UNTRUSTED DISPLAY NAME", rendered)

    def test_full_report_translates_unavailable_chart_enums_and_entry_type(
        self,
    ) -> None:
        def mark_chart_fields_unavailable(reasoning: dict) -> None:
            observation = next(
                item
                for item in reasoning["observations"]
                if item["source"] == "TradingView"
            )
            chart_basis = observation["metrics"]["chart_basis"]
            chart_basis["volume_price_state"] = "not_available"
            chart_basis["trendline_status"] = "not_available"
            chart_basis["fibonacci_levels"] = []

        model = self.build_model(
            reasoning_mutator=mark_chart_fields_unavailable,
        )
        rendered = compiler.render_combined_markdown(model)
        contract = compiler.load_presentation_contract(self.fixture.root)
        fidelity = compiler.evaluate_gold_template_fidelity(
            rendered,
            contract=contract,
        )
        depth = compiler.evaluate_human_reasoning_depth(
            model,
            contract=contract,
        )

        self.assertTrue(fidelity["passed"], fidelity)
        self.assertTrue(depth["passed"], depth)
        self.assertIn("TradingView量价状态=不可用", rendered)
        self.assertIn("趋势线状态=不可用", rendered)
        self.assertIn("入场类型=左侧", rendered)
        self.assertNotIn("not_available", rendered)
        self.assertNotRegex(rendered, r"入场类型=(?:left|right|not_applicable)\b")
        poisoned = rendered.replace("入场类型=左侧", "入场类型=left", 1)
        poisoned_fidelity = compiler.evaluate_gold_template_fidelity(
            poisoned,
            contract=contract,
        )
        self.assertIn(
            "template.raw_enum",
            {item["code"] for item in poisoned_fidelity["defects"]},
        )

    def test_report_v11_projects_non_applicable_probability_without_zero_sentinel(self) -> None:
        def make_probability_not_applicable(decision: dict) -> None:
            self.make_directional_thesis_only(decision)

        model = self.build_model(
            decision_mutator=make_probability_not_applicable,
        )
        summary = model["maker_summary"]
        self.assertIsNone(summary["entry_reach_probability"])
        self.assertEqual(
            summary["entry_reach_probability_applicability"],
            "not_applicable_no_certified_entry_geometry",
        )
        self.assertEqual(
            model["audit"]["entry_reach_probability_projection"]["value_pct"],
            None,
        )
        proof = json.dumps(
            model["audit"]["reasoning_proof"], ensure_ascii=False
        )
        rendered = compiler.render_combined_markdown(model)
        self.assertIn("不适用", proof)
        self.assertIn("不适用", rendered)
        self.assertNotIn("候选触达概率：0%", rendered)
        self.assertNotIn("执行概率：0%", rendered)

    def test_maker_four_state_projection_is_closed_and_visible(self) -> None:
        def reject_submitted_candidate(decision: dict) -> None:
            maker = decision["maker"]
            maker.update(
                {
                    "plan_state": "observe",
                    "threshold_eligible": False,
                    "plan_constructible": False,
                }
            )
            maker["plan_constructibility"].update(
                {
                    "status": "not_constructible",
                    "primary_reason_code": "risk_math_invalid",
                    "failure_codes": ["risk_math_invalid"],
                }
            )

        models = {
            "qualified_candidate": self.build_model(),
            "rejected_submitted_candidate": self.build_model(
                decision_mutator=reject_submitted_candidate
            ),
            "directional_thesis_only": self.build_no_candidate_model(
                "directional_thesis_only"
            ),
            "non_directional_observation": self.build_no_candidate_model(
                "non_directional_observation"
            ),
        }
        expected_headings = {
            "qualified_candidate": "### BTC（候选策略）",
            "rejected_submitted_candidate": "### BTC（被拒候选审计）",
            "directional_thesis_only": "### BTC（方向观察）",
            "non_directional_observation": "### BTC（无方向观察）",
        }
        for state, model in models.items():
            with self.subTest(state=state):
                rendered = compiler.render_combined_markdown(model)
                self.assertEqual(model["maker_summary"]["semantic_state"], state)
                self.assertIn(expected_headings[state], rendered)
                for other_state, other_heading in expected_headings.items():
                    if other_state != state:
                        self.assertNotIn(other_heading, rendered)
                depth = compiler.evaluate_human_reasoning_depth(
                    model,
                    contract=compiler.load_presentation_contract(
                        self.fixture.root
                    ),
                )
                self.assertTrue(depth["passed"], depth)

        for state in ("directional_thesis_only", "non_directional_observation"):
            with self.subTest(no_ghost_candidate=state):
                model = models[state]
                rendered = compiler.render_combined_markdown(model)
                self.assertIsNone(
                    model["audit"]["maker_execution"]["position_notional_usdt"]
                )
                self.assertEqual(model["audit"]["risk_plan"], {})
                self.assertEqual(model["audit"]["defense_plan"], {})
                self.assertNotIn("### BTC（候选策略）", rendered)
                self.assertNotIn("### BTC（被拒候选审计）", rendered)

    def test_no_candidate_scenarios_are_exact_typed_projections(self) -> None:
        contract = compiler.load_presentation_contract(self.fixture.root)
        projection = contract["scenario_projection_contract"]
        canonical_fields = set(projection["canonical_audit_field_order"])
        for state in (
            "directional_thesis_only",
            "non_directional_observation",
        ):
            with self.subTest(state=state):
                model = self.build_no_candidate_model(state)
                depth = compiler.evaluate_human_reasoning_depth(
                    model,
                    contract=contract,
                )
                self.assertTrue(depth["passed"], depth)
                claims = {
                    item["id"]: item for item in model["audit"]["claims"]
                }
                controls = model["audit"]["account_controls"]
                scenarios = model["audit"]["scenario_tree"]
                self.assertEqual(len(scenarios), 6)
                for item in scenarios:
                    self.assertEqual(set(item), canonical_fields)
                    account = item["account"]
                    scenario_type = item["scenario_type"]
                    transition_code = projection["transition_code_by_type"][
                        scenario_type
                    ]
                    visible = projection[
                        "projection_by_account_and_transition_code"
                    ][account][transition_code]
                    self.assertEqual(item["transition_code"], transition_code)
                    self.assertEqual(item["expected_path"], visible["expected_path"])
                    self.assertEqual(item["action"], visible["action"])
                    if scenario_type == "base":
                        direction = claims[item["owner_claim_id"]]["direction"]
                        expected_condition = projection[
                            "base_condition_by_account_direction"
                        ][account][direction]
                    else:
                        expected_condition = controls[account][scenario_type][
                            "condition"
                        ]
                    self.assertEqual(item["condition"], expected_condition)

    def test_canonical_scenario_tampering_is_hard_failed(self) -> None:
        contract = compiler.load_presentation_contract(self.fixture.root)
        mutations = (
            ("id", "scenario_maker_unknown"),
            ("owner_claim_id", "claim_main"),
            ("transition_code", "unknown_transition"),
            ("condition", "tampered-condition"),
            ("expected_path", "tampered-expected-path"),
            ("action", "tampered-action"),
        )
        for state in (
            "directional_thesis_only",
            "non_directional_observation",
        ):
            model = self.build_no_candidate_model(state)
            for field, value in mutations:
                with self.subTest(state=state, field=field):
                    poisoned = copy.deepcopy(model)
                    maker_base = next(
                        item
                        for item in poisoned["audit"]["scenario_tree"]
                        if item.get("account") == "maker"
                        and item.get("scenario_type") == "base"
                    )
                    maker_base[field] = value
                    depth = compiler.evaluate_human_reasoning_depth(
                        poisoned,
                        contract=contract,
                    )
                    self.assertFalse(depth["passed"], depth)
                    self.assertIn(
                        "report_projection.scenario_typed_projection_drift",
                        {item["code"] for item in depth["defects"]},
                    )

    def test_no_candidate_projection_poisoning_is_hard_failed(self) -> None:
        contract = compiler.load_presentation_contract(self.fixture.root)
        mutations = (
            (
                "frontstage.maker_execution",
                lambda model: model["frontstage"].__setitem__(
                    "maker_execution",
                    model["frontstage"]["maker_execution"]
                    + "；候选计划持仓750 USDT；入场=66280；止损=64480",
                ),
            ),
            (
                "maker_summary.plan_summary",
                lambda model: model["maker_summary"].__setitem__(
                    "plan_summary",
                    "候选计划持仓750 USDT；入场=66280；止损=64480",
                ),
            ),
        )
        for state in (
            "directional_thesis_only",
            "non_directional_observation",
        ):
            model = self.build_no_candidate_model(state)
            baseline = compiler.evaluate_human_reasoning_depth(
                model,
                contract=contract,
            )
            self.assertTrue(baseline["passed"], baseline)
            for field, mutate in mutations:
                with self.subTest(state=state, field=field):
                    poisoned = copy.deepcopy(model)
                    mutate(poisoned)
                    depth = compiler.evaluate_human_reasoning_depth(
                        poisoned,
                        contract=contract,
                    )
                    self.assertFalse(depth["passed"], depth)
                    self.assertTrue(
                        any(
                            item.get("severity") == "hard"
                            for item in depth["defects"]
                        ),
                        depth,
                    )

    def test_maker_direction_and_plan_state_are_audit_owned(self) -> None:
        model = self.build_model()
        contract = compiler.load_presentation_contract(self.fixture.root)
        maker_summary = model["maker_summary"]
        maker_audit = model["audit"]["maker_execution"]
        self.assertEqual(maker_audit["direction"], maker_summary["direction"])
        self.assertEqual(maker_audit["plan_state"], maker_summary["plan_state"])

        mutations = (
            ("direction", "long"),
            ("plan_state", "observe"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                poisoned = copy.deepcopy(model)
                poisoned["maker_summary"][field] = value
                depth = compiler.evaluate_human_reasoning_depth(
                    poisoned,
                    contract=contract,
                )
                self.assertFalse(depth["passed"], depth)
                self.assertTrue(
                    any(
                        item.get("severity") == "hard"
                        for item in depth["defects"]
                    ),
                    depth,
                )

    def test_shadow_main_observe_uses_observation_authorization(self) -> None:
        model = self.build_model(decision_mutator=self.make_main_observe)
        self.assertEqual(model["run_mode"], "shadow")
        self.assertEqual(model["main_summary"]["plan_state"], "observe")
        authorization = model["frontstage"]["main_authorization"]
        self.assertIn("观察", authorization)
        self.assertIn("未尝试任何真实执行", authorization)
        self.assertNotIn("候选主账户计划", authorization)
        depth = compiler.evaluate_human_reasoning_depth(
            model,
            contract=compiler.load_presentation_contract(self.fixture.root),
        )
        self.assertTrue(depth["passed"], depth)

    def test_shadow_main_observe_candidate_authorization_poison_is_hard_failed(
        self,
    ) -> None:
        model = self.build_model(decision_mutator=self.make_main_observe)
        model["frontstage"]["main_authorization"] = (
            "影子候选主账户计划；未读取或改变真实持仓，未尝试任何真实执行。"
        )
        depth = compiler.evaluate_human_reasoning_depth(
            model,
            contract=compiler.load_presentation_contract(self.fixture.root),
        )
        self.assertFalse(depth["passed"], depth)
        self.assertTrue(
            any(
                item.get("severity") == "hard"
                for item in depth["defects"]
            ),
            depth,
        )

    def test_report_v11_projects_typed_liquidation_result_not_free_conclusion(self) -> None:
        sentinel = "RAW-LIQUIDATION-CONCLUSION-MUST-NOT-RENDER"

        def poison_liquidation_conclusion(reasoning: dict) -> None:
            claim = next(
                item for item in reasoning["claims"]
                if item["claim_type"] == "liquidation_confirmation"
            )
            claim["conclusion"] = sentinel

        model = self.build_model(reasoning_mutator=poison_liquidation_conclusion)
        july = model["audit"]["reasoning_proof"]["july_additions"]["conclusion"]
        rendered = compiler.render_combined_markdown(model)
        self.assertIn("清算图对已认证手绘区域的流动性概率形成辅助确认", july)
        self.assertNotIn(sentinel, july)
        self.assertNotIn(sentinel, rendered)

    def test_report_v11_projects_typed_etf_relation_not_free_conclusion(self) -> None:
        sentinel = "RAW-ETF-CONCLUSION-MUST-NOT-RENDER"

        def poison_etf_conclusion(reasoning: dict) -> None:
            claim = next(
                item
                for item in reasoning["claims"]
                if item["claim_type"] == "etf_confirmation"
            )
            claim["conclusion"] = sentinel

        model = self.build_model(reasoning_mutator=poison_etf_conclusion)
        july = model["audit"]["reasoning_proof"]["july_additions"]["conclusion"]
        rendered = compiler.render_combined_markdown(model)
        self.assertIn("ETF现货流与同锚价格方向一致，形成确认", july)
        self.assertNotIn(sentinel, july)
        self.assertNotIn(sentinel, rendered)

    def test_report_v11_does_not_project_typed_state_audit_narratives(self) -> None:
        realization_sentinel = "RAW-REALIZATION-CONCLUSION-MUST-NOT-RENDER"
        chart_rationale_sentinel = "RAW-CHART-RATIONALE-MUST-NOT-RENDER"

        def poison_audit_narratives(reasoning: dict) -> None:
            realization = next(
                item
                for item in reasoning["claims"]
                if item["claim_type"] == "fundamental_price_realization"
            )
            realization["conclusion"] = realization_sentinel
            tradingview = next(
                item
                for item in reasoning["observations"]
                if item["source"] == "TradingView"
            )
            for component in tradingview["metrics"]["chart_component_rationales"]:
                tradingview["metrics"]["chart_component_rationales"][
                    component
                ] = chart_rationale_sentinel

        model = self.build_model(reasoning_mutator=poison_audit_narratives)
        rendered = compiler.render_combined_markdown(model)
        proof = model["audit"]["reasoning_proof"]
        self.assertIn(
            "基本面逐事件v1只作价格归因观察",
            proof["fundamental_and_etf_realization"]["conclusion"],
        )
        self.assertNotIn(realization_sentinel, rendered)
        self.assertNotIn(chart_rationale_sentinel, rendered)

    def test_report_v11_discloses_kalshi_plan_c_without_cme_equivalence(self) -> None:
        def use_plan_c(evidence: dict) -> None:
            evidence["sources"]["FedWatch"]["meta"] = copy.deepcopy(
                KALSHI_PROVIDER_META
            )

        model = self.build_model(evidence_mutator=use_plan_c)
        provider = model["audit"]["rate_expectation_provider"]
        self.assertEqual(provider["provider_id"], "kalshi_public_market_data_api")
        self.assertEqual(provider["method_equivalence"], "non_equivalent")
        self.assertTrue(provider["observation_only"])
        rendered = compiler.render_combined_markdown(model)
        self.assertIn("Kalshi KXFEDDECISION（Plan C 备用观察源）", rendered)
        self.assertIn("Kalshi API数据时点", rendered)
        self.assertIn("独立事件合约市场口径，非CME等价，仅作observation", rendered)
        self.assertIn("不计clean", rendered)

    def test_report_rejects_provider_identity_method_conflict(self) -> None:
        def conflict(evidence: dict) -> None:
            evidence["sources"]["FedWatch"]["meta"]["method_equivalence"] = (
                "non_equivalent"
            )

        with self.assertRaisesRegex(ValueError, "conflicts at method_equivalence"):
            self.build_model(evidence_mutator=conflict)

    def test_report_rejects_arbitrary_safe_plan_c_fallback_reason(self) -> None:
        def arbitrary_reason(evidence: dict) -> None:
            evidence["sources"]["FedWatch"]["meta"] = copy.deepcopy(
                KALSHI_PROVIDER_META
            )
            evidence["sources"]["FedWatch"]["meta"]["fallback_reason_code"] = (
                "arbitrary_safe_code"
            )

        with self.assertRaisesRegex(ValueError, "closed eligible fallback reason"):
            self.build_model(evidence_mutator=arbitrary_reason)

    def test_legacy_v1_evidence_is_disclosed_as_unknown_observation(self) -> None:
        def legacy_unbound(evidence: dict) -> None:
            evidence["schema_version"] = "evidence-snapshot-v1"
            evidence["sources"]["FedWatch"]["meta"] = {}

        model = self.build_model(evidence_mutator=legacy_unbound)
        provider = model["audit"]["rate_expectation_provider"]
        self.assertEqual(provider["provider_id"], "unknown")
        self.assertTrue(provider["observation_only"])
        rendered = compiler.render_combined_markdown(model)
        self.assertIn("利率预期来源未绑定（旧版只读证据）", rendered)
        self.assertNotIn("CME FedWatch（官方主源）", rendered)

    def test_claim_audit_is_preserved_but_scenarios_are_typed_projections(self) -> None:
        evidence = self.fixture.evidence()
        reasoning = self.fixture.reasoning(evidence)
        model = self.build_model()
        claims = {item["id"]: item for item in model["audit"]["claims"]}
        source_claims = {item["id"]: item for item in reasoning["claims"]}
        self.assertEqual(
            claims["claim_maker"]["conclusion"],
            source_claims["claim_maker"]["conclusion"],
        )
        self.assertEqual(
            claims["claim_maker"]["invalidation"],
            source_claims["claim_maker"]["invalidation"],
        )

        contract = compiler.load_presentation_contract(self.fixture.root)
        projection = contract["scenario_projection_contract"]
        canonical_fields = set(projection["canonical_audit_field_order"])
        scenarios = {item["id"]: item for item in model["audit"]["scenario_tree"]}
        source_scenarios = {item["id"]: item for item in reasoning["scenario_tree"]}
        for source in source_scenarios.values():
            self.assertEqual(
                set(source),
                {"id", "account", "scenario_type", "owner_claim_id"},
            )

        controlled = {
            "scenario_main_counter": (
                model["audit"]["main_counter_trigger"],
                ["TradingView 1D结构", "Farside ETF流向"],
            ),
            "scenario_main_invalidation": (
                model["audit"]["main_invalidation_trigger"],
                [
                    "TradingView 1D结构",
                    "TradingView 4H结构",
                    "Farside ETF流向",
                ],
            ),
            "scenario_maker_counter": (
                model["audit"]["maker_counter_trigger"],
                [
                    "TradingView 1H结构",
                    "Coinglass最终主判",
                    "Exocharts交叉核验",
                ],
            ),
            "scenario_maker_invalidation": (
                model["audit"]["maker_invalidation_trigger"],
                [
                    "TradingView 1H结构",
                    "Coinglass新锚点重置",
                    "Coinglass最终主判",
                    "Exocharts交叉核验",
                ],
            ),
        }
        for scenario_id, (trigger, clause_labels) in controlled.items():
            self.assertEqual(scenarios[scenario_id]["condition"], trigger)
            positions = [trigger.index(label) for label in clause_labels]
            self.assertEqual(positions, sorted(positions))

        for scenario_id, scenario in scenarios.items():
            source = source_scenarios[scenario_id]
            self.assertEqual(set(scenario), canonical_fields)
            self.assertEqual(scenario["account"], source["account"])
            self.assertEqual(scenario["scenario_type"], source["scenario_type"])
            self.assertEqual(
                scenario["owner_claim_id"],
                source["owner_claim_id"],
            )
            transition_code = projection["transition_code_by_type"][
                scenario["scenario_type"]
            ]
            visible = projection["projection_by_account_and_transition_code"][
                scenario["account"]
            ][transition_code]
            self.assertEqual(scenario["transition_code"], transition_code)
            self.assertEqual(scenario["expected_path"], visible["expected_path"])
            self.assertEqual(scenario["action"], visible["action"])
            if scenario["scenario_type"] == "base":
                direction = claims[scenario["owner_claim_id"]]["direction"]
                self.assertEqual(
                    scenario["condition"],
                    projection["base_condition_by_account_direction"][
                        scenario["account"]
                    ][direction],
                )

        combined = compiler.render_combined_markdown(model)
        for trigger, _ in controlled.values():
            self.assertEqual(combined.count(trigger), 1)

    def test_compiler_refuses_free_scenario_condition(self) -> None:
        def free_condition(reasoning: dict) -> None:
            scenario = next(
                item
                for item in reasoning["scenario_tree"]
                if item["id"] == "scenario_main_counter"
            )
            scenario["condition"] = "日线和一小时多头结构重新形成一致。"

        with self.assertRaisesRegex(
            ValueError,
            "scenario does not use the exact typed ownership fields",
        ):
            self.build_model(reasoning_mutator=free_condition)

    def test_compiler_refuses_wrong_scenario_owner_or_methodology_transition(
        self,
    ) -> None:
        def wrong_owner(reasoning: dict) -> None:
            scenario = next(
                item
                for item in reasoning["scenario_tree"]
                if item["id"] == "scenario_maker_counter"
            )
            scenario["owner_claim_id"] = "claim_maker"

        with self.assertRaisesRegex(
            ValueError,
            "scenario typed owner does not match its exact matrix row",
        ):
            self.build_model(reasoning_mutator=wrong_owner)

        def drift_methodology(reasoning: dict) -> None:
            scenario = next(
                item
                for item in reasoning["methodology"]["scenario_tree"]
                if item["account"] == "maker" and item["kind"] == "counter"
            )
            scenario["action"] = "retain_certified_assessment"

        with self.assertRaisesRegex(
            ValueError,
            "methodology scenario owner or transition code drifted from the top-level scenario",
        ):
            self.build_model(reasoning_mutator=drift_methodology)

    def test_compiler_refuses_any_producer_owned_scenario_prose(self) -> None:
        cases = (
            ("condition", "producer-owned-condition"),
            ("expected_path", "producer-owned-expected-path"),
            ("action", "producer-owned-action"),
        )
        for field, submitted_value in cases:
            with self.subTest(field=field):
                def add_free_prose(
                    reasoning,
                    field=field,
                    submitted_value=submitted_value,
                ):
                    scenario = next(
                        item
                        for item in reasoning["scenario_tree"]
                        if item["id"] == "scenario_main_counter"
                    )
                    scenario[field] = submitted_value

                with self.assertRaisesRegex(
                    ValueError,
                    "scenario does not use the exact typed ownership fields",
                ):
                    self.build_model(reasoning_mutator=add_free_prose)

    def test_compiler_rejects_noncanonical_trigger_and_scenario_identifiers(
        self,
    ) -> None:
        def padded_mode(reasoning):
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_counter_maker"
            )
            claim["trigger_logic"]["mode"] = " all "

        def padded_operator(reasoning):
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_counter_maker"
            )
            claim["trigger_logic"]["clauses"][0]["operator"] = " becomes "

        def padded_scenario_type(reasoning):
            scenario = next(
                item
                for item in reasoning["scenario_tree"]
                if item["id"] == "scenario_main_counter"
            )
            scenario["scenario_type"] = " counter "

        def padded_current_basis_mode(reasoning):
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_counter_maker"
            )
            claim["current_basis"]["mode"] = " all "

        def padded_claim_id(reasoning):
            scenario = next(
                item
                for item in reasoning["scenario_tree"]
                if item["id"] == "scenario_main_counter"
            )
            scenario["owner_claim_id"] = f" {scenario['owner_claim_id']} "

        for label, mutator, message in (
            ("mode", padded_mode, "trigger mode is not canonical"),
            ("operator", padded_operator, "trigger identifiers are not canonical"),
            (
                "current_basis_mode",
                padded_current_basis_mode,
                "current_basis mode is not a canonical closed string",
            ),
            (
                "scenario_type",
                padded_scenario_type,
                "scenario ownership identifiers are not canonical",
            ),
            (
                "owner_claim_id",
                padded_claim_id,
                "scenario ownership identifiers are not canonical",
            ),
        ):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, message):
                    self.build_model(reasoning_mutator=mutator)

    def test_compiler_rejects_invalid_target_shapes_types_and_unreachable_all(
        self,
    ) -> None:
        def bool_as_int(reasoning):
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_invalidation_maker"
            )
            clause = next(
                item
                for item in claim["trigger_logic"]["clauses"]
                if item["field"] == "pivot.anchor_reset"
            )
            clause["value"] = 1

        with self.assertRaisesRegex(
            ValueError, "certified account trigger value is invalid"
        ):
            self.build_model(reasoning_mutator=bool_as_int)

        def current_basis_bool_as_int(reasoning):
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_invalidation_maker"
            )
            claim["current_basis"]["clauses"].append(
                {
                    "owner_type": "observation",
                    "owner_id": "obs_cg",
                    "field": "pivot.anchor_reset",
                    "operator": "equals",
                    "value": 0,
                }
            )

        with self.assertRaisesRegex(
            ValueError, "current_basis value differs from its typed current owner"
        ):
            self.build_model(reasoning_mutator=current_basis_bool_as_int)

        def string_one_of(reasoning):
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_counter_maker"
            )
            clause = next(
                item
                for item in claim["trigger_logic"]["clauses"]
                if item["field"] == "final_direction"
            )
            clause.pop("value")
            clause.update(
                {
                    "operator": "one_of_at_trigger",
                    "values": "bullish",
                }
            )

        with self.assertRaisesRegex(
            ValueError, "certified account trigger target shape is invalid"
        ):
            self.build_model(reasoning_mutator=string_one_of)

        def unreachable_all(reasoning):
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_counter_maker"
            )
            claim["trigger_logic"]["clauses"].append(
                {
                    "owner_type": "observation",
                    "owner_id": "obs_cg",
                    "field": "final_direction",
                    "operator": "equals_at_trigger",
                    "value": "bearish",
                }
            )

        with self.assertRaisesRegex(
            ValueError,
            "all-trigger has mutually exclusive same-field clauses",
        ):
            self.build_model(reasoning_mutator=unreachable_all)

    def test_compiler_preserves_typed_trigger_clause_tuples_in_source_order(
        self,
    ) -> None:
        evidence = self.fixture.evidence()
        reasoning = self.fixture.reasoning(evidence)
        reasoning["reasoning_sha256"] = compiler.reasoning_model_sha256(reasoning)
        decision = self.fixture.decision(reasoning)
        trigger_policy = compiler.load_scoring_policy(root=self.fixture.root)[
            "gold_methodology"
        ]["account_trigger_logic"]
        controls = compiler._typed_account_controls(
            reasoning,
            maker=decision["maker"],
            main=decision["main_account"],
            trigger_policy=trigger_policy,
        )
        claims = {
            (item["account"], item["claim_type"]): item
            for item in reasoning["claims"]
            if item["claim_type"]
            in {"strongest_counterevidence", "invalidation_path"}
        }

        for account, control_name, claim_type in (
            ("main", "counter", "strongest_counterevidence"),
            ("main", "invalidation", "invalidation_path"),
            ("maker", "counter", "strongest_counterevidence"),
            ("maker", "invalidation", "invalidation_path"),
        ):
            source_clauses = claims[(account, claim_type)]["trigger_logic"][
                "clauses"
            ]
            expected = [
                {
                    "owner_type": item["owner_type"],
                    "owner_id": item["owner_id"],
                    "field": item["field"],
                    "operator": item["operator"],
                    "targets": copy.deepcopy(
                        item["values"]
                        if item["operator"] == "one_of_at_trigger"
                        else [item["value"]]
                    ),
                }
                for item in source_clauses
            ]
            projected = [
                {
                    key: copy.deepcopy(item[key])
                    for key in (
                        "owner_type",
                        "owner_id",
                        "field",
                        "operator",
                        "targets",
                    )
                }
                for item in controls[account][control_name]["clauses"]
            ]
            self.assertEqual(projected, expected)

    def test_free_control_prose_poisoning_cannot_change_visible_projection(
        self,
    ) -> None:
        conclusion_sentinel = "POISON-CONTROL-CONCLUSION-MUST-NOT-PROJECT"
        invalidation_sentinel = "POISON-CONTROL-INVALIDATION-MUST-NOT-PROJECT"

        def poison_free_control_prose(reasoning: dict) -> None:
            for claim in reasoning["claims"]:
                if claim.get("claim_type") in {
                    "strongest_counterevidence",
                    "invalidation_path",
                }:
                    claim["conclusion"] = conclusion_sentinel
                    claim["invalidation"] = invalidation_sentinel

        baseline = self.build_model()
        poisoned = self.build_model(
            reasoning_mutator=poison_free_control_prose
        )
        baseline_visible = compiler.render_combined_markdown(baseline)
        poisoned_visible = compiler.render_combined_markdown(poisoned)

        self.assertNotEqual(
            baseline["reasoning_sha256"],
            poisoned["reasoning_sha256"],
        )
        self.assertNotEqual(
            baseline["audit"]["claims"],
            poisoned["audit"]["claims"],
        )
        self.assertEqual(
            baseline["audit"]["account_controls"],
            poisoned["audit"]["account_controls"],
        )
        self.assertEqual(baseline["frontstage"], poisoned["frontstage"])
        self.assertEqual(baseline_visible, poisoned_visible)
        self.assertNotIn(conclusion_sentinel, poisoned_visible)
        self.assertNotIn(invalidation_sentinel, poisoned_visible)

    def test_long_blockbeats_body_is_owned_once_not_repeated_by_compiler(self) -> None:
        long_body = (
            "这是用于验证编译器所有权的BlockBeats长正文。"
            "正文可以包含跨主题背景、时间窗口与多段事件描述，"
            "但只能保留在认证事件卡中，不能复制到基本面、趋势、策略、"
            "Maker计划与推理证明链形成重复放大。"
        )

        def replace_first_event(evidence: dict) -> None:
            record = evidence["sources"]["BlockBeats"]["artifacts"][0]
            path = self.fixture.root / record["path"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["selected_rows"][0]["body"] = long_body
            path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            record["sha256"] = compiler.sha256_file(path)
            record["bytes"] = path.stat().st_size

        model = self.build_model(evidence_mutator=replace_first_event)
        combined = compiler.render_combined_markdown(model)
        serialized = json.dumps(model, ensure_ascii=False)

        self.assertEqual(model["blockbeats_cards"][0]["body"], long_body)
        self.assertEqual(serialized.count(long_body), 1)
        self.assertEqual(
            json.dumps(model["audit"], ensure_ascii=False).count(long_body), 0
        )
        self.assertLessEqual(combined.count(long_body), 1)

    def test_rejected_maker_is_labeled_candidate_not_executable_plan(self) -> None:
        failure_codes = [
            "entry_zone_role_invalid",
            "maker_order_marketable",
            "entry_semantics_invalid",
            "cannot_do_conflict",
            "order_lifecycle_invalid",
            "structural_stop_invalid",
            "risk_math_invalid",
        ]

        def reject_maker(decision: dict) -> None:
            maker = decision["maker"]
            maker["direction"] = "long"
            maker["strategy_type"] = "低多"
            maker["entry_type"] = "left"
            maker["position_notional_usdt"] = 750
            maker["plan_state"] = "observe"
            maker["threshold_eligible"] = False
            maker["plan_constructible"] = False
            maker["plan_constructibility"].update(
                {
                    "status": "not_constructible",
                    "primary_reason_code": failure_codes[0],
                    "failure_codes": failure_codes,
                }
            )
            maker["execution_action"] = "not_attempted"
            maker["order_transition_action"] = "not_attempted"
            maker["risk_plan"].update(
                {
                    "entries": [66280, 66200],
                    "entry_allocations_pct": [50, 50],
                    "stop": 64480,
                    "tp1": 70800,
                    "tp2": 72500,
                    "leverage": 5,
                }
            )

        model = self.build_model(decision_mutator=reject_maker)
        proof = "\n".join(
            model["audit"]["reasoning_proof"]["risk_and_scenarios"]["evidence"]
        )
        combined = compiler.render_combined_markdown(model)

        self.assertEqual(
            model["audit"]["risk_plan"]["candidate_status"],
            "rejected_not_executable",
        )
        self.assertEqual(
            model["maker_summary"]["constructibility_failure_codes"],
            failure_codes,
        )
        self.assertEqual(
            model["maker_summary"]["plan_reason_explanations"][-1],
            compiler.THRESHOLD_INELIGIBLE_CN,
        )
        self.assertNotIn("候选名义持仓=750 USDT", proof)
        self.assertEqual(
            len(model["audit"]["rejected_candidate_risk_scenarios"]),
            3,
        )
        self.assertEqual(model["audit"]["risk_scenarios"], [])
        for code in failure_codes:
            with self.subTest(code=code):
                self.assertIn(compiler.CONSTRUCTIBILITY_REASON_CN[code], combined)
        for risk_value in ("13.58%", "12.99%", "13.29%"):
            with self.subTest(risk_value=risk_value):
                self.assertIn(risk_value, combined)
        self.assertIn(compiler.THRESHOLD_INELIGIBLE_CN, combined)
        self.assertEqual(
            model["audit"]["rejected_candidate_risk_recalculation"],
            {
                "status": "recalculated",
                "reason_code": "deterministic_recalculation_succeeded",
            },
        )
        self.assertEqual(
            combined.count("被拒候选风险情景（不可执行，不得用于下单）"),
            3,
        )
        maker_section = combined.split("## ② Maker 计划", 1)[1].split(
            "## ③ 后附", 1
        )[0]
        for forbidden in ("750", "66280", "66200", "64480", "70800", "72500"):
            with self.subTest(frontstage_forbidden=forbidden):
                self.assertNotIn(forbidden, maker_section)
        self.assertIn("被拒候选审计输入（不可执行，不得用于下单）", combined)
        self.assertIn("入场类型=左侧", combined)
        self.assertNotRegex(
            combined,
            r"入场类型=(?:left|right|not_applicable)\b",
        )
        self.assertNotIn("计划持仓=750 USDT", proof)
        self.assertIn("候选名义持仓=750 USDT", combined)
        self.assertNotIn("计划持仓=750 USDT", combined)
        poisoned = copy.deepcopy(model)
        poisoned["frontstage"]["maker_authorization"] += "；影子方向观察状态"
        depth = compiler.evaluate_human_reasoning_depth(
            poisoned,
            contract=compiler.load_presentation_contract(self.fixture.root),
        )
        self.assertFalse(depth["passed"])
        self.assertIn(
            "report_projection.shadow_semantic_state_conflict",
            {item["code"] for item in depth["defects"]},
        )

    def test_rejected_right_entry_type_is_translated_without_certifying_it(
        self,
    ) -> None:
        def reject_right_entry(decision: dict) -> None:
            maker = decision["maker"]
            maker["entry_type"] = "right"
            maker["plan_state"] = "observe"
            maker["threshold_eligible"] = False
            maker["plan_constructible"] = False
            maker["plan_constructibility"].update(
                {
                    "status": "not_constructible",
                    "primary_reason_code": "entry_semantics_invalid",
                    "failure_codes": ["entry_semantics_invalid"],
                }
            )
            maker["execution_action"] = "not_attempted"
            maker["order_transition_action"] = "not_attempted"

        model = self.build_model(decision_mutator=reject_right_entry)
        rendered = compiler.render_combined_markdown(model)

        self.assertEqual(model["maker_summary"]["plan_state"], "observe")
        self.assertIn("入场类型=右侧", rendered)
        self.assertNotRegex(
            rendered,
            r"入场类型=(?:left|right|not_applicable)\b",
        )

    def test_rejected_unrecalculable_risk_is_disclosed_without_report_failure(
        self,
    ) -> None:
        def reject_unrecalculable_risk(decision: dict) -> None:
            maker = decision["maker"]
            maker["plan_state"] = "observe"
            maker["plan_constructible"] = False
            maker["plan_constructibility"].update(
                {
                    "status": "not_constructible",
                    "primary_reason_code": "risk_math_invalid",
                    "failure_codes": ["risk_math_invalid"],
                }
            )
            maker["execution_action"] = "not_attempted"
            maker["order_transition_action"] = "not_attempted"
            maker["risk_plan"]["tp1"] = maker["risk_plan"]["entries"][0]

        model = self.build_model(decision_mutator=reject_unrecalculable_risk)
        combined = compiler.render_combined_markdown(model)

        self.assertEqual(
            model["audit"]["rejected_candidate_risk_recalculation"],
            {
                "status": "not_recalculable",
                "reason_code": "candidate_risk_input_failed_recalculation",
            },
        )
        self.assertEqual(
            model["audit"]["rejected_candidate_risk_scenarios"],
            [],
        )
        self.assertIn("被拒候选审计输入（不可执行，不得用于下单）", combined)
        self.assertIn("候选风险输入未满足确定性复算前提", combined)
        self.assertNotIn("被拒候选风险情景（不可执行，不得用于下单）", combined)
        depth = compiler.evaluate_human_reasoning_depth(
            model,
            contract=compiler.load_presentation_contract(self.fixture.root),
        )
        self.assertTrue(depth["passed"], depth)

    def test_rejected_risk_recalculation_handles_invalid_allocation_shapes(
        self,
    ) -> None:
        for case, allocations in (
            ("allocation_count_mismatch", [100]),
            ("allocation_count_extra", [40, 30, 30]),
            ("zero_weight_scenario", [0, 100]),
            ("negative_weight", [110, -10]),
            ("allocation_sum_mismatch", [40, 40]),
        ):
            with self.subTest(case=case):
                def reject_invalid_allocations(decision: dict) -> None:
                    maker = decision["maker"]
                    maker["plan_state"] = "observe"
                    maker["plan_constructible"] = False
                    maker["plan_constructibility"].update(
                        {
                            "status": "not_constructible",
                            "primary_reason_code": "risk_math_invalid",
                            "failure_codes": ["risk_math_invalid"],
                        }
                    )
                    maker["execution_action"] = "not_attempted"
                    maker["order_transition_action"] = "not_attempted"
                    maker["risk_plan"]["entry_allocations_pct"] = allocations

                model = self.build_model(
                    decision_mutator=reject_invalid_allocations
                )
                combined = compiler.render_combined_markdown(model)
                self.assertEqual(
                    model["audit"]["rejected_candidate_risk_recalculation"][
                        "status"
                    ],
                    "not_recalculable",
                )
                self.assertEqual(
                    model["audit"]["rejected_candidate_risk_scenarios"],
                    [],
                )
                self.assertIn(
                    "候选风险输入未满足确定性复算前提",
                    combined,
                )

    def test_rejected_risk_bounded_preflight_is_closed(self) -> None:
        maker = {
            "direction": "short",
            "risk_plan": {
                "entries": [99.8, 100.0],
                "entry_allocations_pct": [50, 50],
                "stop": 100.35,
                "tp1": 98.0,
                "tp2": 97.0,
                "leverage": 5,
            },
        }
        self.assertTrue(compiler._rejected_risk_input_is_bounded(maker))
        for case, field, value in (
            ("direction", "direction", "sideways"),
            ("nonpositive_entry", "entries", [0, 100.0]),
            ("nonpositive_leverage", "leverage", 0),
            ("nonfinite_stop", "stop", float("nan")),
        ):
            with self.subTest(case=case):
                mutated = copy.deepcopy(maker)
                if field == "direction":
                    mutated[field] = value
                else:
                    mutated["risk_plan"][field] = value
                self.assertFalse(
                    compiler._rejected_risk_input_is_bounded(mutated)
                )

    def test_rejected_risk_preflight_bounds_fill_enumeration(self) -> None:
        def reject_six_level_candidate(decision: dict) -> None:
            maker = decision["maker"]
            maker["plan_state"] = "observe"
            maker["plan_constructible"] = False
            maker["plan_constructibility"].update(
                {
                    "status": "not_constructible",
                    "primary_reason_code": "risk_math_invalid",
                    "failure_codes": ["risk_math_invalid"],
                }
            )
            maker["execution_action"] = "not_attempted"
            maker["order_transition_action"] = "not_attempted"
            maker["risk_plan"]["entries"] = [
                99.75,
                99.8,
                99.85,
                99.9,
                99.95,
                100.0,
            ]
            maker["risk_plan"]["entry_allocations_pct"] = [
                10,
                10,
                20,
                20,
                20,
                20,
            ]

        with patch.object(
            compiler,
            "_risk_scenarios",
            side_effect=AssertionError("unbounded rejected input was enumerated"),
        ):
            model = self.build_model(
                decision_mutator=reject_six_level_candidate
            )
        self.assertEqual(
            model["audit"]["rejected_candidate_risk_recalculation"]["status"],
            "not_recalculable",
        )
        self.assertEqual(
            model["audit"]["rejected_candidate_risk_scenarios"],
            [],
        )

    def test_signal_dispositions_and_copy_normalization_are_visible(self) -> None:
        model = self.build_model()
        combined = compiler.render_combined_markdown(model)

        self.assertIn("二级信号处置｜ETF 资金流确认", combined)
        self.assertIn("二级信号处置｜基本面价格归因观察", combined)
        self.assertEqual(
            combined.count("闭合理由=已复核，本轮未形成独立增量影响"),
            1,
        )
        self.assertEqual(
            combined.count(
                "闭合理由=逐事件价格窗口与方向归因尚未建立，当前只作观察记录"
            ),
            1,
        )
        for defect in (
            "基本面价格归因观察基本面价格归因观察",
            "CVD CVD",
            "。；",
            "；；",
        ):
            with self.subTest(defect=defect):
                self.assertNotIn(defect, combined)

        def unknown_reason(decision: dict) -> None:
            decision["maker"]["winrate_rubric"]["signal_dispositions"][0][
                "no_adjustment_reason_code"
            ] = "unknown_reason"

        with self.assertRaisesRegex(ValueError, "no-adjustment reason is invalid"):
            self.build_model(decision_mutator=unknown_reason)

    def test_fundamental_event_v1_load_bearing_legacy_shapes_fail_closed(
        self,
    ) -> None:
        def restore_legacy_current_basis(reasoning: dict) -> None:
            claim = next(
                item
                for item in reasoning["claims"]
                if item["id"] == "claim_invalidation_main"
            )
            claim["current_basis"]["clauses"].append(
                {
                    "owner_type": "claim",
                    "owner_id": "claim_realization",
                    "field": "realization_state",
                    "operator": "equals",
                    "value": "partially_realized",
                }
            )

        with self.assertRaisesRegex(
            ValueError,
            "fundamental-event-assessment-v1 cannot own invalidation_path.current_basis",
        ):
            self.build_model(reasoning_mutator=restore_legacy_current_basis)

        def restore_legacy_winrate_adjustment(decision: dict) -> None:
            maker = decision["maker"]
            rubric = maker["winrate_rubric"]
            rubric["adjustments"].append(
                {
                    "reason_code": "fundamental_weaken",
                    "label": "legacy fundamental adjustment",
                    "delta": -1,
                    "claim_ids": ["claim_realization"],
                    "rationale": "legacy event-v1 load-bearing path",
                }
            )
            fundamental = next(
                item
                for item in rubric["signal_dispositions"]
                if item["signal_type"] == "fundamental_price_realization"
            )
            fundamental.update(
                {
                    "disposition": "adjusted",
                    "adjustment_reason_code": "fundamental_weaken",
                    "no_adjustment_reason_code": None,
                }
            )
            rubric["final"] -= 1
            maker["win_rate"] -= 1

        with self.assertRaisesRegex(
            ValueError,
            "observation-only secondary signal cannot be adjusted",
        ):
            self.build_model(
                decision_mutator=restore_legacy_winrate_adjustment
            )


if __name__ == "__main__":
    unittest.main()
