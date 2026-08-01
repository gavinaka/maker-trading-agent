from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime_vnext.rate_expectation import (
    RateExpectationError,
    canonical_json_sha256,
    normalize_kalshi_payload,
    validate_rate_provenance,
)


ROOT = Path(__file__).resolve().parents[1]


def _contract() -> dict:
    return json.loads(
        (ROOT / "data_sources" / "rate_expectation_provider_contract.json").read_text(
            encoding="utf-8"
        )
    )


def _request(url: str, payload: dict, retrieved_at: str) -> dict:
    return {
        "url": url,
        "status_code": 200,
        "retrieved_at": retrieved_at,
        "wire_sha256": "a" * 64,
        "body_sha256": canonical_json_sha256(payload),
        "payload": payload,
    }


def _fixture(
    retrieved_at: str = "2026-07-19T00:00:00Z",
) -> tuple[dict, dict, dict]:
    contract = _contract()
    run_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    retrieved_dt = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
    retrieved_ts = int(retrieved_dt.timestamp())

    def before(seconds: int) -> str:
        return datetime.fromtimestamp(
            retrieved_ts - seconds, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z")
    event_ticker = "KXFEDDECISION-26JUL"
    buckets = [
        ("cut_gt_25bp", "C26", {"Cut": ">25"}, "Cut >25bps", "0.0000", "0.0200"),
        ("cut_25bp", "C25", {"Cut": "25"}, "Cut 25bps", "0.0500", "0.0700"),
        ("hold", "H0", {"Hike": "0"}, "Hike 0bps", "0.8000", "0.8200"),
        ("hike_25bp", "H25", {"Hike": "25"}, "Hike 25bps", "0.1000", "0.1200"),
        ("hike_gt_25bp", "H26", {"Hike": ">25"}, "Hike >25bps", "0.0100", "0.0300"),
    ]
    markets = []
    tickers = []
    for _, suffix, strike, subtitle, bid, ask in buckets:
        ticker = f"{event_ticker}-{suffix}"
        tickers.append(ticker)
        markets.append(
            {
                "ticker": ticker,
                "event_ticker": event_ticker,
                "status": "active",
                "close_time": "2026-07-29T17:59:00Z",
                "custom_strike": strike,
                "subtitle": subtitle,
                "yes_bid_dollars": bid,
                "yes_ask_dollars": ask,
                "last_price_dollars": bid,
            }
        )
    event = {
        "event_ticker": event_ticker,
        "series_ticker": "KXFEDDECISION",
        "strike_date": "2026-07-29T18:00:00Z",
        "mutually_exclusive": True,
        "markets": markets,
    }
    series_payload = {
        "series": {
            "ticker": "KXFEDDECISION",
            "contract_terms_url": contract["kalshi"]["contract_terms_url"],
            "settlement_sources": [
                {"name": "Federal Reserve", "url": "https://www.federalreserve.gov"}
            ],
        }
    }
    events_payload = {"events": [event]}
    candle_series = []
    offsets = (86400, 604800, 2592000)
    for index, (_, _, _, _, bid, ask) in enumerate(buckets):
        rows = []
        for offset in offsets:
            # Earlier distributions differ while remaining on the same five
            # independently observed quote baselines.
            historical_bid = max(0, int(float(bid) * 100) - index) / 100
            historical_ask = max(
                historical_bid,
                int(float(ask) * 100) - index,
            ) / 100
            rows.append(
                {
                    "end_period_ts": retrieved_ts - offset - 3600,
                    "yes_bid": {"close_dollars": f"{historical_bid:.4f}"},
                    "yes_ask": {"close_dollars": f"{historical_ask:.4f}"},
                    "volume_fp": "1.00",
                }
            )
        candle_series.append(rows)
    candles_payload = {
        "adjusted_end_ts": retrieved_ts,
        "market_tickers": tickers,
        "market_candlesticks": candle_series,
    }

    cme_result = {
        "schema_version": contract["cme_attempt_schema_version"],
        "provider_id": "cme_fedwatch_ui",
        "capture_run_id": run_id,
        "started_at": before(60),
        "completed_at": before(30),
        "status": "failed",
        "defect_code": "cme_tool_content_load_error",
        "output": None,
    }
    cme_result["attempt_sha256"] = canonical_json_sha256(
        cme_result, exclude="attempt_sha256"
    )
    base = contract["kalshi"]["api_base_url"]
    responses = {
        "series": _request(
            f"{base}/series/KXFEDDECISION", series_payload, before(20)
        ),
        "events": _request(
            f"{base}/events?series_ticker=KXFEDDECISION&status=open&limit=200&with_nested_markets=true",
            events_payload,
            before(15),
        ),
        "candlesticks": _request(
            f"{base}/series/KXFEDDECISION/events/{event_ticker}/candlesticks"
            f"?start_ts={retrieved_ts - 2592000 - 86400}&end_ts={retrieved_ts}&period_interval=60",
            candles_payload,
            before(10),
        ),
    }
    terms_hash = contract["kalshi"]["contract_terms_sha256"]
    raw = {
        "schema_version": contract["kalshi_raw_schema_version"],
        "provider_id": "kalshi_public_market_data_api",
        "series_ticker": "KXFEDDECISION",
        "capture_run_id": run_id,
        "retrieved_at": retrieved_at,
        "api_base_url": base,
        "cme_attempt_sha256": cme_result["attempt_sha256"],
        "selected_event": {
            "event_ticker": event_ticker,
            "strike_date": event["strike_date"],
            "mutually_exclusive": True,
            "market_tickers": sorted(tickers),
            "outcome_market_map": {
                outcome: ticker
                for (outcome, *_), ticker in zip(buckets, tickers)
            },
        },
        "responses": responses,
        "contract_terms": {
            "url": contract["kalshi"]["contract_terms_url"],
            "status_code": 200,
            "retrieved_at": before(5),
            "bytes": 25054,
            "sha256": terms_hash,
            "expected_sha256": terms_hash,
            "matches_expected": True,
        },
    }
    raw["raw_sha256"] = canonical_json_sha256(raw, exclude="raw_sha256")
    return contract, cme_result, raw


def _rehash_raw(raw: dict) -> None:
    raw["raw_sha256"] = canonical_json_sha256(raw, exclude="raw_sha256")


def _provenance(contract: dict, cme_result: dict) -> dict:
    payload = {
        "schema_version": contract["provenance_schema_version"],
        "logical_source": contract["logical_source"],
        "capture_run_id": cme_result["capture_run_id"],
        "selection_mode": "kalshi_plan_c_fallback",
        "provider_id": "kalshi_public_market_data_api",
        "series_ticker": "KXFEDDECISION",
        "fallback_reason_code": cme_result["defect_code"],
        "primary_attempt_artifact_path": "cme_fedwatch_result.json",
        "raw_artifact_paths": ["kalshi_feddecision_raw.json"],
        "normalized_artifact_path": "fedwatch.json",
        "selected_artifact_paths": [
            "cme_fedwatch_result.json",
            "fedwatch.json",
            "kalshi_feddecision_raw.json",
        ],
    }
    payload["provenance_sha256"] = canonical_json_sha256(
        payload, exclude="provenance_sha256"
    )
    return payload


PLAN_C_ARTIFACT_NAMES = {
    "cme_fedwatch_result.json",
    "kalshi_feddecision_raw.json",
    "fedwatch.json",
    "rate_expectation_provenance.json",
}


class RateExpectationTests(unittest.TestCase):
    def test_plan_c_normalization_is_deterministic_and_sum_closed(self):
        contract, cme_result, raw = _fixture()
        first = normalize_kalshi_payload(contract, cme_result, raw)
        second = normalize_kalshi_payload(contract, cme_result, raw)
        self.assertEqual(first, second)
        self.assertEqual(first["method_equivalence"], "non_equivalent")
        self.assertEqual(first["selection_mode"], "kalshi_plan_c_fallback")
        self.assertEqual(first["metrics"]["next_fomc_date"], "2026-07-29")
        current = first["metrics"]["current_probabilities"]
        self.assertEqual(set(current), set(contract["kalshi"]["required_outcomes"]))
        self.assertEqual(sum(map(float, current.values())), 100.0)
        for window in ("change_1d", "change_1w", "change_1m"):
            self.assertAlmostEqual(
                sum(map(float, first["metrics"][window].values())), 0.0, places=6
            )
        self.assertEqual(
            first["normalized_sha256"],
            canonical_json_sha256(first, exclude="normalized_sha256"),
        )

    def test_all_zero_listed_midpoints_hard_stop(self):
        contract, cme_result, raw = _fixture()
        event = raw["responses"]["events"]["payload"]["events"][0]
        for market in event["markets"]:
            market["yes_bid_dollars"] = "0.0000"
            market["yes_ask_dollars"] = "0.0000"
        request = raw["responses"]["events"]
        request["body_sha256"] = canonical_json_sha256(request["payload"])
        _rehash_raw(raw)
        with self.assertRaisesRegex(RateExpectationError, "all listed"):
            normalize_kalshi_payload(contract, cme_result, raw)

    def test_missing_one_historical_anchor_hard_stops(self):
        contract, cme_result, raw = _fixture()
        candles = raw["responses"]["candlesticks"]["payload"]
        candles["market_candlesticks"][0] = []
        request = raw["responses"]["candlesticks"]
        request["body_sha256"] = canonical_json_sha256(request["payload"])
        _rehash_raw(raw)
        with self.assertRaisesRegex(RateExpectationError, "anchor is missing"):
            normalize_kalshi_payload(contract, cme_result, raw)

    def test_noneligible_cme_failure_never_enables_plan_c(self):
        contract, cme_result, raw = _fixture()
        cme_result["defect_code"] = "cme_page_schema_unclassified"
        cme_result["attempt_sha256"] = canonical_json_sha256(
            cme_result, exclude="attempt_sha256"
        )
        raw["cme_attempt_sha256"] = cme_result["attempt_sha256"]
        _rehash_raw(raw)
        with self.assertRaisesRegex(RateExpectationError, "not eligible"):
            normalize_kalshi_payload(contract, cme_result, raw)

    def test_cme_contract_cannot_be_weakened_with_its_payload(self):
        contract, cme_result, raw = _fixture()
        contract["cme"]["attempt_artifact"]["exact_fields"].remove("output")
        del cme_result["output"]
        cme_result["attempt_sha256"] = canonical_json_sha256(
            cme_result, exclude="attempt_sha256"
        )
        raw["cme_attempt_sha256"] = cme_result["attempt_sha256"]
        _rehash_raw(raw)
        with self.assertRaisesRegex(RateExpectationError, "frozen v1"):
            normalize_kalshi_payload(contract, cme_result, raw)

    def test_raw_payload_mutation_is_rejected_before_normalization(self):
        contract, cme_result, raw = _fixture()
        mutated = copy.deepcopy(raw)
        mutated["responses"]["events"]["payload"]["events"][0]["strike_date"] = (
            "2026-09-01T18:00:00Z"
        )
        with self.assertRaisesRegex(RateExpectationError, "raw identity"):
            normalize_kalshi_payload(contract, cme_result, mutated)

    def test_provenance_mutation_path_mix_and_unknown_reason_are_closed(self):
        contract, cme_result, _ = _fixture()
        provenance = _provenance(contract, cme_result)
        meta = validate_rate_provenance(
            provenance,
            contract,
            capture_run_id=cme_result["capture_run_id"],
            artifact_names=PLAN_C_ARTIFACT_NAMES,
        )
        self.assertEqual(meta["selection_mode"], "kalshi_plan_c_fallback")

        mutated = copy.deepcopy(provenance)
        mutated["provider_id"] = "cme_fedwatch_ui"
        with self.assertRaisesRegex(RateExpectationError, "identity or hash"):
            validate_rate_provenance(
                mutated,
                contract,
                capture_run_id=cme_result["capture_run_id"],
                artifact_names=PLAN_C_ARTIFACT_NAMES,
            )

        with self.assertRaisesRegex(RateExpectationError, "not closed"):
            validate_rate_provenance(
                provenance,
                contract,
                capture_run_id=cme_result["capture_run_id"],
                artifact_names=PLAN_C_ARTIFACT_NAMES | {"fedwatch.png"},
            )

        unknown = copy.deepcopy(provenance)
        unknown["fallback_reason_code"] = "cme_unknown_failure"
        unknown["provenance_sha256"] = canonical_json_sha256(
            unknown, exclude="provenance_sha256"
        )
        with self.assertRaisesRegex(RateExpectationError, "not closed"):
            validate_rate_provenance(
                unknown,
                contract,
                capture_run_id=cme_result["capture_run_id"],
                artifact_names=PLAN_C_ARTIFACT_NAMES,
            )

    def test_cme_primary_provenance_uses_explicit_none_reason(self):
        contract, cme_result, _ = _fixture()
        provenance = {
            "schema_version": contract["provenance_schema_version"],
            "logical_source": contract["logical_source"],
            "capture_run_id": cme_result["capture_run_id"],
            "selection_mode": "cme_primary",
            "provider_id": "cme_fedwatch_ui",
            "series_ticker": None,
            "fallback_reason_code": "none",
            "primary_attempt_artifact_path": "cme_fedwatch_result.json",
            "raw_artifact_paths": [],
            "normalized_artifact_path": None,
            "selected_artifact_paths": [
                "cme_fedwatch_result.json",
                "fedwatch.png",
            ],
        }
        provenance["provenance_sha256"] = canonical_json_sha256(
            provenance, exclude="provenance_sha256"
        )
        meta = validate_rate_provenance(
            provenance,
            contract,
            capture_run_id=cme_result["capture_run_id"],
            artifact_names={
                "cme_fedwatch_result.json",
                "fedwatch.png",
                "rate_expectation_provenance.json",
            },
        )
        self.assertEqual(meta["fallback_reason_code"], "none")

    def test_ambiguous_earliest_event_hard_stops(self):
        contract, cme_result, raw = _fixture()
        request = raw["responses"]["events"]
        duplicate = copy.deepcopy(request["payload"]["events"][0])
        duplicate["event_ticker"] = "KXFEDDECISION-26JUL-DUP"
        for market in duplicate["markets"]:
            market["event_ticker"] = duplicate["event_ticker"]
            market["ticker"] = market["ticker"] + "-DUP"
        request["payload"]["events"].append(duplicate)
        request["body_sha256"] = canonical_json_sha256(request["payload"])
        _rehash_raw(raw)
        with self.assertRaisesRegex(RateExpectationError, "ambiguous"):
            normalize_kalshi_payload(contract, cme_result, raw)

    def test_closed_or_provisional_market_hard_stops(self):
        contract, cme_result, raw = _fixture()
        request = raw["responses"]["events"]
        market = request["payload"]["events"][0]["markets"][0]
        market["close_time"] = "2026-07-18T23:00:00Z"
        request["body_sha256"] = canonical_json_sha256(request["payload"])
        _rehash_raw(raw)
        with self.assertRaises(RateExpectationError):
            normalize_kalshi_payload(contract, cme_result, raw)

        contract, cme_result, raw = _fixture()
        request = raw["responses"]["events"]
        request["payload"]["events"][0]["markets"][0]["is_provisional"] = True
        request["body_sha256"] = canonical_json_sha256(request["payload"])
        _rehash_raw(raw)
        with self.assertRaises(RateExpectationError):
            normalize_kalshi_payload(contract, cme_result, raw)

    def test_noncanonical_dollar_quote_hard_stops(self):
        contract, cme_result, raw = _fixture()
        request = raw["responses"]["events"]
        request["payload"]["events"][0]["markets"][0]["yes_bid_dollars"] = "0.01"
        request["body_sha256"] = canonical_json_sha256(request["payload"])
        _rehash_raw(raw)
        with self.assertRaisesRegex(RateExpectationError, "four-decimal"):
            normalize_kalshi_payload(contract, cme_result, raw)

    def test_event_at_retrieval_instant_is_not_future(self):
        contract, cme_result, raw = _fixture()
        request = raw["responses"]["events"]
        event = request["payload"]["events"][0]
        event["strike_date"] = raw["retrieved_at"]
        raw["selected_event"]["strike_date"] = raw["retrieved_at"]
        request["body_sha256"] = canonical_json_sha256(request["payload"])
        _rehash_raw(raw)
        with self.assertRaisesRegex(RateExpectationError, "no future"):
            normalize_kalshi_payload(contract, cme_result, raw)


if __name__ == "__main__":
    unittest.main()
