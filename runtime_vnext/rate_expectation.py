"""Deterministic Kalshi Plan-C normalizer for FOMC rate expectations.

This module contains no network client.  It accepts only sealed capture
artifacts, validates their provider and current-run lineage, and deterministically
replays the public market payload into the compatibility ``FedWatch`` metrics.
Kalshi remains an explicitly non-equivalent observation source; this module
does not relabel it as CME FedWatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


TOTAL_UNITS = 100_000
UNIT_PERCENTAGE_POINTS = Decimal("0.001")
NORMALIZED_HASH_FIELD = "normalized_sha256"
EXPECTED_CME_ATTEMPT_CONTRACT = {
    "exact_fields": [
        "schema_version",
        "capture_run_id",
        "provider_id",
        "status",
        "defect_code",
        "started_at",
        "completed_at",
        "output",
        "attempt_sha256",
    ],
    "status_values": ["passed", "failed"],
    "passed_output_exact_fields": ["path", "sha256", "bytes"],
    "passed_output_path": "fedwatch.png",
    "failed_output_must_be_null": True,
    "hash_field": "attempt_sha256",
    "hash_method_code": "sha256_canonical_json_without_self_v1",
}
EXPECTED_PROVENANCE_FIELDS = {
    "schema_version",
    "logical_source",
    "capture_run_id",
    "selection_mode",
    "provider_id",
    "series_ticker",
    "fallback_reason_code",
    "primary_attempt_artifact_path",
    "raw_artifact_paths",
    "normalized_artifact_path",
    "selected_artifact_paths",
    "provenance_sha256",
}


class RateExpectationError(ValueError):
    """A sealed Plan-C artifact cannot be certified."""


def canonical_json_sha256(value: Any, *, exclude: str | None = None) -> str:
    if exclude is not None:
        if not isinstance(value, dict):
            raise RateExpectationError("hash-bearing payload must be an object")
        value = {key: item for key, item in value.items() if key != exclude}
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RateExpectationError(f"{label} must be an object")
    return value


def _exact_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        missing = sorted(keys - set(value))
        extra = sorted(set(value) - keys)
        raise RateExpectationError(
            f"{label} fields differ from contract (missing={missing}, extra={extra})"
        )


def _aware_datetime(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RateExpectationError(f"{label} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise RateExpectationError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise RateExpectationError(f"{label} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RateExpectationError(f"{label} must be numeric") from exc
    if not result.is_finite():
        raise RateExpectationError(f"{label} must be finite")
    return result


def _dollar_units(value: Any, label: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"(?:0\.[0-9]{4}|1\.0000)", value) is None:
        raise RateExpectationError(f"{label} must be a four-decimal dollar string")
    amount = _decimal(value, label)
    scaled = amount * TOTAL_UNITS
    integral = scaled.to_integral_value()
    if amount < 0 or amount > 1 or scaled != integral:
        raise RateExpectationError(
            f"{label} must be a 0..1 quote exactly representable at 0.001 percentage points"
        )
    return int(integral)


def _format_units(units: int) -> str:
    if not 0 <= units <= TOTAL_UNITS:
        raise RateExpectationError("normalized probability is outside 0..100")
    return f"{Decimal(units) * UNIT_PERCENTAGE_POINTS:.3f}"


def _format_delta(units: int) -> str:
    return f"{Decimal(units) * UNIT_PERCENTAGE_POINTS:.3f}"


def _bounded_simplex(
    quotes: dict[str, tuple[int, int]],
    *,
    order: tuple[str, ...],
    reject_all_zero: bool,
) -> tuple[dict[str, int], int]:
    """Project bid/ask midpoints onto sum(listed)<=1 with a residual bucket.

    The integer grid is 0.001 percentage points.  When listed midpoints exceed
    one, equal downward water-filling is applied without crossing any bid.  A
    deterministic outcome order resolves indivisible one-unit remainders.
    """

    midpoint: dict[str, int] = {}
    lower: dict[str, int] = {}
    for key in order:
        if key not in quotes:
            raise RateExpectationError(f"quote set is missing {key}")
        bid, ask = quotes[key]
        if bid > ask:
            raise RateExpectationError(f"{key} bid exceeds ask")
        midpoint[key] = (bid + ask) // 2
        # A half-grid cannot occur because Kalshi's four-decimal dollar quotes
        # map to ten units before division; keep the guard for schema drift.
        if (bid + ask) % 2:
            raise RateExpectationError(f"{key} midpoint is off the output grid")
        lower[key] = bid

    if reject_all_zero and all(value == 0 for value in midpoint.values()):
        raise RateExpectationError("all listed Kalshi bid/ask midpoints are zero")
    if sum(lower.values()) > TOTAL_UNITS:
        raise RateExpectationError("listed Kalshi bids exceed the probability simplex")

    values = dict(midpoint)
    excess = max(0, sum(values.values()) - TOTAL_UNITS)
    while excess:
        active = [key for key in order if values[key] > lower[key]]
        if not active:
            raise RateExpectationError("midpoints cannot be projected without crossing bids")
        share, remainder = divmod(excess, len(active))
        progress = 0
        for index, key in enumerate(active):
            requested = share + (1 if index < remainder else 0)
            if requested == 0:
                continue
            reduction = min(requested, values[key] - lower[key])
            values[key] -= reduction
            excess -= reduction
            progress += reduction
        if progress == 0:
            # This is reachable only when excess < len(active) and the chosen
            # deterministic prefix unexpectedly has no capacity.
            for key in active:
                if excess == 0:
                    break
                if values[key] > lower[key]:
                    values[key] -= 1
                    excess -= 1
                    progress += 1
        if progress == 0:
            raise RateExpectationError("bounded-simplex projection made no progress")
    return values, TOTAL_UNITS - sum(values.values())


def _request_envelope(value: Any, label: str) -> dict[str, Any]:
    request = _object(value, label)
    _exact_keys(
        request,
        {
            "url",
            "status_code",
            "retrieved_at",
            "wire_sha256",
            "body_sha256",
            "payload",
        },
        label,
    )
    if request.get("status_code") != 200:
        raise RateExpectationError(f"{label} did not return HTTP 200")
    _aware_datetime(request.get("retrieved_at"), f"{label}.retrieved_at")
    payload = request.get("payload")
    if re.fullmatch(r"[0-9a-f]{64}", str(request.get("wire_sha256") or "")) is None:
        raise RateExpectationError(f"{label} wire hash is invalid")
    if request.get("body_sha256") != canonical_json_sha256(payload):
        raise RateExpectationError(f"{label} payload hash mismatch")
    return request


def _endpoint(
    request: dict[str, Any],
    *,
    base_url: str,
    expected_path: str,
    label: str,
) -> dict[str, list[str]]:
    parsed = urlparse(str(request.get("url") or ""))
    base = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or parsed.scheme != base.scheme
        or parsed.netloc != base.netloc
        or parsed.path.rstrip("/") != expected_path.rstrip("/")
    ):
        raise RateExpectationError(f"{label} URL is outside the contracted endpoint")
    return parse_qs(parsed.query, keep_blank_values=True)


def _validate_cme_result(
    result: dict[str, Any], contract: dict[str, Any], *, require_failed: bool
) -> None:
    attempt_contract = contract["cme"]["attempt_artifact"]
    if attempt_contract != EXPECTED_CME_ATTEMPT_CONTRACT:
        raise RateExpectationError("CME attempt artifact contract differs from frozen v1")
    _exact_keys(
        result,
        set(attempt_contract["exact_fields"]),
        "cme_result",
    )
    primary = contract["selection_modes"]["cme_primary"]
    cme_policy = contract["cme"]
    if (
        result.get("schema_version") != contract["cme_attempt_schema_version"]
        or result.get("provider_id") != primary["provider_id"]
        or result.get("status") not in attempt_contract["status_values"]
        or result.get("attempt_sha256")
        != canonical_json_sha256(result, exclude=attempt_contract["hash_field"])
    ):
        raise RateExpectationError("CME attempt identity or hash is invalid")
    attempted = _aware_datetime(result.get("started_at"), "cme_result.started_at")
    completed = _aware_datetime(result.get("completed_at"), "cme_result.completed_at")
    if completed < attempted:
        raise RateExpectationError("CME attempt completion precedes its start")
    capture_run_id = str(result.get("capture_run_id") or "")
    if re.fullmatch(r"[0-9a-f-]{16,64}", capture_run_id, re.I) is None:
        raise RateExpectationError("CME attempt capture_run_id is invalid")

    if require_failed:
        code = result.get("defect_code")
        if (
            result.get("status") != "failed"
            or code not in cme_policy["eligible_fallback_codes"]
            or code in cme_policy["non_fallback_codes"]
            or result.get("output") is not None
        ):
            raise RateExpectationError("CME failure is not eligible for Plan C")
    else:
        output = result.get("output")
        if (
            result.get("status") != "passed"
            or result.get("defect_code") is not None
            or not isinstance(output, dict)
            or set(output) != set(attempt_contract["passed_output_exact_fields"])
            or output.get("path") != attempt_contract["passed_output_path"]
            or re.fullmatch(r"[0-9a-f]{64}", str(output.get("sha256") or ""))
            is None
            or not isinstance(output.get("bytes"), int)
            or isinstance(output.get("bytes"), bool)
            or output["bytes"] <= 0
        ):
            raise RateExpectationError("CME primary attempt did not seal a valid success")


def validate_cme_result(
    result: dict[str, Any], contract: dict[str, Any], *, require_failed: bool
) -> None:
    """Public validator used by the evidence gate for both provider modes."""

    _validate_cme_result(result, contract, require_failed=require_failed)


def validate_rate_provenance(
    provenance: dict[str, Any],
    contract: dict[str, Any],
    *,
    capture_run_id: str,
    artifact_names: set[str],
) -> dict[str, Any]:
    """Validate the closed provider state machine and return exact source meta."""

    _exact_keys(provenance, EXPECTED_PROVENANCE_FIELDS, "provider provenance")
    if (
        provenance.get("schema_version") != contract["provenance_schema_version"]
        or provenance.get("logical_source") != contract["logical_source"]
        or provenance.get("capture_run_id") != capture_run_id
        or provenance.get("provenance_sha256")
        != canonical_json_sha256(provenance, exclude="provenance_sha256")
    ):
        raise RateExpectationError("provider provenance identity or hash is invalid")
    mode = str(provenance.get("selection_mode") or "")
    selection = (contract.get("selection_modes") or {}).get(mode)
    if not isinstance(selection, dict):
        raise RateExpectationError("provider selection_mode is unsupported")
    if (
        provenance.get("provider_id") != selection.get("provider_id")
        or provenance.get("series_ticker") != selection.get("series_ticker")
        or provenance.get("primary_attempt_artifact_path")
        != "cme_fedwatch_result.json"
    ):
        raise RateExpectationError("provider provenance differs from selected contract mode")

    if mode == "cme_primary":
        expected_artifacts = {
            "fedwatch.png",
            "cme_fedwatch_result.json",
            "rate_expectation_provenance.json",
        }
        if (
            artifact_names != expected_artifacts
            or provenance.get("fallback_reason_code") != "none"
            or provenance.get("raw_artifact_paths") != []
            or provenance.get("normalized_artifact_path") is not None
            or provenance.get("selected_artifact_paths")
            != ["cme_fedwatch_result.json", "fedwatch.png"]
        ):
            raise RateExpectationError("CME primary provenance/artifacts are not closed")
    elif mode == "kalshi_plan_c_fallback":
        expected_artifacts = {
            "cme_fedwatch_result.json",
            "kalshi_feddecision_raw.json",
            "fedwatch.json",
            "rate_expectation_provenance.json",
        }
        if (
            artifact_names != expected_artifacts
            or provenance.get("fallback_reason_code")
            not in contract["cme"]["eligible_fallback_codes"]
            or provenance.get("raw_artifact_paths")
            != ["kalshi_feddecision_raw.json"]
            or provenance.get("normalized_artifact_path") != "fedwatch.json"
            or provenance.get("selected_artifact_paths")
            != [
                "cme_fedwatch_result.json",
                "fedwatch.json",
                "kalshi_feddecision_raw.json",
            ]
        ):
            raise RateExpectationError("Plan C provenance/artifacts are not closed")
    else:
        raise RateExpectationError("provider selection_mode is unsupported")

    return {
        "provider_id": selection.get("provider_id"),
        "selection_mode": mode,
        "series_ticker": selection.get("series_ticker"),
        "acquisition_channel": selection.get("acquisition_channel"),
        "method_class": selection.get("method_class"),
        "method_equivalence": selection.get("method_equivalence"),
        "sample_source_class": selection.get("sample_source_class"),
        "quote_basis_code": selection.get("quote_basis_code"),
        "normalization_method_code": selection.get("normalization_method_code"),
        "fallback_reason_code": provenance.get("fallback_reason_code"),
        "provenance_sha256": provenance.get("provenance_sha256"),
    }


def _outcome_order(contract: dict[str, Any]) -> tuple[str, ...]:
    mappings = contract["kalshi"]["outcome_mappings"]
    order = tuple(str(item["outcome_key"]) for item in mappings)
    if len(order) != len(set(order)) or set(order) | {
        contract["kalshi"]["normalization"]["other_outcome_key"]
    } != set(contract["kalshi"]["required_outcomes"]):
        raise RateExpectationError("provider contract outcome mapping is inconsistent")
    return order


def _market_mapping(contract: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    result: dict[tuple[str, str, str], str] = {}
    for item in contract["kalshi"]["outcome_mappings"]:
        key = (
            str(item["custom_strike_key"]),
            str(item["custom_strike_value"]),
            str(item["subtitle"]),
        )
        if key in result:
            raise RateExpectationError("provider contract contains a duplicate outcome mapping")
        result[key] = str(item["outcome_key"])
    return result


def _map_event_markets(
    event: dict[str, Any], contract: dict[str, Any], *, retrieved_at: datetime
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    mapping = _market_mapping(contract)
    markets = event.get("markets")
    if not isinstance(markets, list):
        raise RateExpectationError("selected Kalshi event has no market list")
    by_outcome: dict[str, dict[str, Any]] = {}
    ticker_to_outcome: dict[str, str] = {}
    for market in markets:
        market = _object(market, "Kalshi market")
        strike = _object(market.get("custom_strike"), "Kalshi market custom_strike")
        if len(strike) != 1:
            raise RateExpectationError("Kalshi market custom_strike must have one field")
        strike_key, strike_value = next(iter(strike.items()))
        map_key = (str(strike_key), str(strike_value), str(market.get("subtitle") or ""))
        outcome = mapping.get(map_key)
        if outcome is None:
            raise RateExpectationError(f"unmapped Kalshi market bucket: {map_key!r}")
        ticker = str(market.get("ticker") or "")
        close_time = _aware_datetime(market.get("close_time"), f"{ticker}.close_time")
        if (
            not ticker
            or outcome in by_outcome
            or ticker in ticker_to_outcome
            or market.get("status") != "active"
            or market.get("event_ticker") != event.get("event_ticker")
            or close_time <= retrieved_at
            or ("is_provisional" in market and market.get("is_provisional") is not False)
        ):
            raise RateExpectationError("Kalshi market identity/status is invalid or duplicated")
        by_outcome[outcome] = market
        ticker_to_outcome[ticker] = outcome
    if set(by_outcome) != set(_outcome_order(contract)):
        raise RateExpectationError("Kalshi event does not contain exactly the five contracted buckets")
    return by_outcome, ticker_to_outcome


def _select_event(
    events_payload: Any,
    *,
    retrieved_at: datetime,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, str]]:
    envelope = _object(events_payload, "events response")
    events = envelope.get("events")
    if not isinstance(events, list):
        raise RateExpectationError("events response has no events list")
    candidates: list[tuple[datetime, str, dict[str, Any]]] = []
    for value in events:
        event = _object(value, "Kalshi event")
        if event.get("series_ticker") != contract["kalshi"]["series_ticker"]:
            continue
        strike = _aware_datetime(event.get("strike_date"), "event.strike_date")
        if strike > retrieved_at:
            candidates.append((strike, str(event.get("event_ticker") or ""), event))
    if not candidates:
        raise RateExpectationError("no future KXFEDDECISION event is available")
    earliest_strike = min(item[0] for item in candidates)
    earliest = [item for item in candidates if item[0] == earliest_strike]
    if len(earliest) != 1:
        raise RateExpectationError("earliest KXFEDDECISION event is ambiguous")
    _, ticker, event = earliest[0]
    if not ticker or event.get("mutually_exclusive") is not True:
        raise RateExpectationError("selected Kalshi event ticker is missing")
    by_outcome, ticker_to_outcome = _map_event_markets(
        event, contract, retrieved_at=retrieved_at
    )
    return event, by_outcome, ticker_to_outcome


def _quotes_from_markets(
    by_outcome: dict[str, dict[str, Any]], order: tuple[str, ...]
) -> tuple[dict[str, tuple[int, int]], dict[str, dict[str, Any]]]:
    quotes: dict[str, tuple[int, int]] = {}
    audit: dict[str, dict[str, Any]] = {}
    for outcome in order:
        market = by_outcome[outcome]
        bid_text = market.get("yes_bid_dollars")
        ask_text = market.get("yes_ask_dollars")
        bid = _dollar_units(bid_text, f"{outcome}.yes_bid_dollars")
        ask = _dollar_units(ask_text, f"{outcome}.yes_ask_dollars")
        quotes[outcome] = (bid, ask)
        audit[outcome] = {
            "market_ticker": market["ticker"],
            "yes_bid_dollars": str(bid_text),
            "yes_ask_dollars": str(ask_text),
            "last_price_dollars": str(market.get("last_price_dollars") or ""),
        }
    return quotes, audit


def _historical_quotes(
    candles_payload: Any,
    *,
    ticker_to_outcome: dict[str, str],
    target_ts: int,
    max_age: int,
    max_skew: int,
    order: tuple[str, ...],
) -> tuple[dict[str, tuple[int, int]], dict[str, Any]]:
    payload = _object(candles_payload, "candlesticks response")
    tickers = payload.get("market_tickers")
    series = payload.get("market_candlesticks")
    if (
        not isinstance(tickers, list)
        or not isinstance(series, list)
        or len(tickers) != len(series)
        or len(tickers) != len(set(map(str, tickers)))
        or set(map(str, tickers)) != set(ticker_to_outcome)
    ):
        raise RateExpectationError("candlestick market arrays do not match the selected event")

    quotes: dict[str, tuple[int, int]] = {}
    selected_times: dict[str, int] = {}
    audit: dict[str, Any] = {}
    for ticker_value, candles in zip(tickers, series):
        ticker = str(ticker_value)
        outcome = ticker_to_outcome[ticker]
        if not isinstance(candles, list):
            raise RateExpectationError(f"candlesticks for {ticker} must be an array")
        eligible: list[tuple[int, dict[str, Any]]] = []
        for candle_value in candles:
            candle = _object(candle_value, f"candlestick {ticker}")
            if "is_provisional" in candle and candle.get("is_provisional") is not False:
                raise RateExpectationError(f"provisional candlestick is forbidden for {ticker}")
            timestamp = candle.get("end_period_ts")
            if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp > target_ts:
                continue
            bid_close = (candle.get("yes_bid") or {}).get("close_dollars") if isinstance(candle.get("yes_bid"), dict) else None
            ask_close = (candle.get("yes_ask") or {}).get("close_dollars") if isinstance(candle.get("yes_ask"), dict) else None
            if bid_close is None or ask_close is None:
                continue
            eligible.append((timestamp, candle))
        if not eligible:
            raise RateExpectationError(f"historical anchor is missing for {ticker}")
        timestamp, candle = max(eligible, key=lambda item: item[0])
        age = target_ts - timestamp
        if age < 0 or age > max_age:
            raise RateExpectationError(f"historical anchor is stale for {ticker}")
        bid_text = candle["yes_bid"]["close_dollars"]
        ask_text = candle["yes_ask"]["close_dollars"]
        bid = _dollar_units(bid_text, f"{ticker}.historical_yes_bid")
        ask = _dollar_units(ask_text, f"{ticker}.historical_yes_ask")
        quotes[outcome] = (bid, ask)
        selected_times[outcome] = timestamp
        audit[outcome] = {
            "market_ticker": ticker,
            "end_period_ts": timestamp,
            "yes_bid_dollars": str(bid_text),
            "yes_ask_dollars": str(ask_text),
        }
    if set(quotes) != set(order):
        raise RateExpectationError("historical anchor does not cover all five outcomes")
    if max(selected_times.values()) - min(selected_times.values()) > max_skew:
        raise RateExpectationError("historical anchor timestamps exceed cross-bucket skew")
    return quotes, {
        "target_ts": target_ts,
        "selected_min_ts": min(selected_times.values()),
        "selected_max_ts": max(selected_times.values()),
        "quotes": audit,
    }


def _distribution(
    quotes: dict[str, tuple[int, int]], contract: dict[str, Any]
) -> tuple[dict[str, int], dict[str, str]]:
    order = _outcome_order(contract)
    other_key = contract["kalshi"]["normalization"]["other_outcome_key"]
    reject_all_zero = contract["kalshi"]["normalization"].get(
        "reject_all_listed_midpoints_zero"
    ) is True
    listed, other = _bounded_simplex(
        quotes,
        order=order,
        reject_all_zero=reject_all_zero,
    )
    units = {**listed, other_key: other}
    return units, {key: _format_units(value) for key, value in units.items()}


def _validate_series(payload: Any, contract: dict[str, Any]) -> None:
    series = _object(_object(payload, "series response").get("series"), "series")
    sources = series.get("settlement_sources")
    names = {
        str(item.get("name") or "")
        for item in sources
        if isinstance(item, dict)
    } if isinstance(sources, list) else set()
    if (
        series.get("ticker") != contract["kalshi"]["series_ticker"]
        or series.get("contract_terms_url") != contract["kalshi"]["contract_terms_url"]
        or contract["kalshi"]["settlement_source_name"] not in names
    ):
        raise RateExpectationError("Kalshi series identity/settlement source is invalid")


def normalize_kalshi_payload(
    contract: dict[str, Any],
    cme_result: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Validate and deterministically normalize one sealed Plan-C raw payload."""

    if contract.get("schema_version") != "fomc-rate-provider-contract-v1":
        raise RateExpectationError("unsupported rate-provider contract")
    _validate_cme_result(cme_result, contract, require_failed=True)
    _exact_keys(
        raw,
        {
            "schema_version",
            "provider_id",
            "series_ticker",
            "capture_run_id",
            "retrieved_at",
            "api_base_url",
            "cme_attempt_sha256",
            "selected_event",
            "responses",
            "contract_terms",
            "raw_sha256",
        },
        "kalshi_raw",
    )
    fallback = contract["selection_modes"]["kalshi_plan_c_fallback"]
    kalshi = contract["kalshi"]
    if (
        raw.get("schema_version") != contract["kalshi_raw_schema_version"]
        or raw.get("provider_id") != fallback["provider_id"]
        or raw.get("series_ticker") != fallback["series_ticker"]
        or raw.get("api_base_url") != kalshi["api_base_url"]
        or raw.get("capture_run_id") != cme_result.get("capture_run_id")
        or raw.get("cme_attempt_sha256") != cme_result.get("attempt_sha256")
        or raw.get("raw_sha256") != canonical_json_sha256(raw, exclude="raw_sha256")
    ):
        raise RateExpectationError("Kalshi raw identity, current-run binding, or hash is invalid")
    retrieved_at = _aware_datetime(raw.get("retrieved_at"), "kalshi_raw.retrieved_at")
    cme_completed_at = _aware_datetime(
        cme_result.get("completed_at"), "cme_result.completed_at"
    )
    if retrieved_at < cme_completed_at:
        raise RateExpectationError("Kalshi retrieval precedes the sealed CME failure")

    terms = _object(raw.get("contract_terms"), "contract_terms")
    _exact_keys(
        terms,
        {
            "url",
            "status_code",
            "retrieved_at",
            "bytes",
            "sha256",
            "expected_sha256",
            "matches_expected",
        },
        "contract_terms",
    )
    if (
        terms.get("url") != kalshi["contract_terms_url"]
        or terms.get("status_code") != 200
        or not isinstance(terms.get("bytes"), int)
        or isinstance(terms.get("bytes"), bool)
        or terms.get("bytes") <= 0
        or terms.get("sha256") != kalshi["contract_terms_sha256"]
        or terms.get("expected_sha256") != kalshi["contract_terms_sha256"]
        or terms.get("matches_expected") is not True
    ):
        raise RateExpectationError("Kalshi contract-terms binding is invalid")
    _aware_datetime(terms.get("retrieved_at"), "contract_terms.retrieved_at")

    responses = _object(raw.get("responses"), "responses")
    _exact_keys(responses, {"series", "events", "candlesticks"}, "responses")
    series_request = _request_envelope(responses["series"], "responses.series")
    events_request = _request_envelope(responses["events"], "responses.events")
    candles_request = _request_envelope(
        responses["candlesticks"], "responses.candlesticks"
    )
    for request, label in (
        (series_request, "responses.series"),
        (events_request, "responses.events"),
        (candles_request, "responses.candlesticks"),
    ):
        if _aware_datetime(request["retrieved_at"], f"{label}.retrieved_at") > retrieved_at:
            raise RateExpectationError(f"{label} retrieval is later than sealed raw retrieval")

    series_path = f"/trade-api/v2/series/{kalshi['series_ticker']}"
    _endpoint(
        series_request,
        base_url=kalshi["api_base_url"],
        expected_path=series_path,
        label="series",
    )
    event_query = _endpoint(
        events_request,
        base_url=kalshi["api_base_url"],
        expected_path="/trade-api/v2/events",
        label="events",
    )
    if (
        event_query.get("series_ticker") != [kalshi["series_ticker"]]
        or event_query.get("status") != ["open"]
        or event_query.get("with_nested_markets") != ["true"]
    ):
        raise RateExpectationError("events request is missing the contracted filters")
    _validate_series(series_request["payload"], contract)
    event, by_outcome, ticker_to_outcome = _select_event(
        events_request["payload"], retrieved_at=retrieved_at, contract=contract
    )
    selected = _object(raw.get("selected_event"), "selected_event")
    _exact_keys(
        selected,
        {
            "event_ticker",
            "strike_date",
            "mutually_exclusive",
            "market_tickers",
            "outcome_market_map",
        },
        "selected_event",
    )
    expected_selected = {
        "event_ticker": event.get("event_ticker"),
        "strike_date": event.get("strike_date"),
        "mutually_exclusive": True,
        "market_tickers": sorted(ticker_to_outcome),
        "outcome_market_map": {
            outcome: ticker
            for ticker, outcome in sorted(ticker_to_outcome.items())
        },
    }
    actual_selected = dict(selected)
    if isinstance(actual_selected.get("market_tickers"), list):
        actual_selected["market_tickers"] = sorted(map(str, actual_selected["market_tickers"]))
    if actual_selected != expected_selected:
        raise RateExpectationError("selected_event differs from deterministic event selection")

    candle_path = (
        f"/trade-api/v2/series/{kalshi['series_ticker']}/events/"
        f"{event['event_ticker']}/candlesticks"
    )
    candle_query = _endpoint(
        candles_request,
        base_url=kalshi["api_base_url"],
        expected_path=candle_path,
        label="candlesticks",
    )
    history = kalshi["history"]
    if candle_query.get("period_interval") != [str(history["period_interval_minutes"])]:
        raise RateExpectationError("candlestick interval differs from provider contract")
    try:
        start_ts = int(candle_query.get("start_ts", [""])[0])
        end_ts = int(candle_query.get("end_ts", [""])[0])
    except (TypeError, ValueError) as exc:
        raise RateExpectationError("candlestick request range is invalid") from exc
    retrieved_ts = int(retrieved_at.timestamp())
    largest_offset = max(history["anchor_offsets_seconds"].values())
    if (
        start_ts > retrieved_ts - largest_offset - history["max_anchor_age_seconds"]
        or end_ts < retrieved_ts
    ):
        raise RateExpectationError("candlestick request does not cover every required anchor")
    candle_payload = _object(candles_request["payload"], "candlesticks response")
    adjusted_end_ts = candle_payload.get("adjusted_end_ts")
    period_seconds = int(history["period_interval_minutes"]) * 60
    if (
        not isinstance(adjusted_end_ts, int)
        or isinstance(adjusted_end_ts, bool)
        or adjusted_end_ts < retrieved_ts - period_seconds
        or adjusted_end_ts > end_ts
    ):
        raise RateExpectationError("candlestick adjusted_end_ts does not cover retrieval time")

    order = _outcome_order(contract)
    current_quotes, current_quote_audit = _quotes_from_markets(by_outcome, order)
    current_units, current_distribution = _distribution(current_quotes, contract)
    anchor_units: dict[str, dict[str, int]] = {}
    anchor_distributions: dict[str, dict[str, str]] = {}
    anchor_audit: dict[str, Any] = {}
    for window, offset in history["anchor_offsets_seconds"].items():
        quotes, audit = _historical_quotes(
            candles_request["payload"],
            ticker_to_outcome=ticker_to_outcome,
            target_ts=retrieved_ts - int(offset),
            max_age=int(history["max_anchor_age_seconds"]),
            max_skew=int(history["max_cross_bucket_skew_seconds"]),
            order=order,
        )
        units, distribution = _distribution(quotes, contract)
        anchor_units[window] = units
        anchor_distributions[window] = distribution
        anchor_audit[window] = audit

    metric_windows: dict[str, dict[str, str]] = {}
    for window in ("change_1d", "change_1w", "change_1m"):
        metric_windows[window] = {
            key: _format_delta(current_units[key] - anchor_units[window][key])
            for key in current_units
        }
    metrics = {
        "data_as_of": str(raw["retrieved_at"]),
        "next_fomc_date": _aware_datetime(
            event["strike_date"], "selected event strike_date"
        ).date().isoformat(),
        "current_probabilities": current_distribution,
        **metric_windows,
    }
    payload: dict[str, Any] = {
        "schema_version": contract["kalshi_normalized_schema_version"],
        "logical_source": contract["logical_source"],
        "compatibility_source_id": contract["compatibility_source_id"],
        "selection_mode": "kalshi_plan_c_fallback",
        "provider_id": fallback["provider_id"],
        "series_ticker": fallback["series_ticker"],
        "acquisition_channel": fallback["acquisition_channel"],
        "method_class": fallback["method_class"],
        "method_equivalence": fallback["method_equivalence"],
        "sample_source_class": fallback["sample_source_class"],
        "quote_basis_code": fallback["quote_basis_code"],
        "normalization_method_code": fallback["normalization_method_code"],
        "fallback_reason_code": cme_result["defect_code"],
        "capture_run_id": raw["capture_run_id"],
        "event_ticker": event["event_ticker"],
        "retrieved_at": raw["retrieved_at"],
        "metrics": metrics,
        "distributions": {
            "current": current_distribution,
            "anchor_1d": anchor_distributions["change_1d"],
            "anchor_1w": anchor_distributions["change_1w"],
            "anchor_1m": anchor_distributions["change_1m"],
        },
        "quote_audit": {
            "current": current_quote_audit,
            "anchors": anchor_audit,
        },
        "bindings": {
            "provider_contract_sha256": canonical_json_sha256(contract),
            "cme_attempt_sha256": cme_result["attempt_sha256"],
            "kalshi_raw_sha256": raw["raw_sha256"],
        },
    }
    payload[NORMALIZED_HASH_FIELD] = canonical_json_sha256(
        payload, exclude=NORMALIZED_HASH_FIELD
    )
    return payload


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RateExpectationError(f"cannot read {label}: {path}") from exc
    return _object(payload, label)


def _exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    normalize = subparsers.add_parser(
        "normalize-kalshi", description="Replay one sealed Kalshi Plan-C capture"
    )
    normalize.add_argument("--contract", required=True, type=Path)
    normalize.add_argument("--cme-result", required=True, type=Path)
    normalize.add_argument("--raw", required=True, type=Path)
    normalize.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command != "normalize-kalshi":
        raise RateExpectationError("unsupported command")
    payload = normalize_kalshi_payload(
        _load(args.contract, "provider contract"),
        _load(args.cme_result, "CME result"),
        _load(args.raw, "Kalshi raw"),
    )
    _exclusive_json(args.output.resolve(), payload)
    print(
        json.dumps(
            {
                "status": "normalized",
                "output": str(args.output.resolve()),
                "normalized_sha256": payload[NORMALIZED_HASH_FIELD],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
