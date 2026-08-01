"""Artifact fingerprinting and conservative delta calculation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from runtime.dependency_graph import (
    affected_nodes,
    all_recomputable_nodes,
    required_analysis_nodes,
)


SOURCE_PATTERNS: dict[str, tuple[str, ...]] = {
    "blockbeats": ("blockbeats.json", "blockbeats.png"),
    "coinglass": ("coinglass.png",),
    "exocharts": ("exocharts.png",),
    "fedwatch": ("fedwatch.json", "fedwatch.png"),
    "farside_btc_etf": ("farside_btc_etf.json", "farside_btc_etf.png"),
    "tradingview_1d": ("tradingview_btc_1d.png", "tradingview_btc_1d_liq.png"),
    "tradingview_4h": ("tradingview_btc_4h.png", "tradingview_btc_4h_liq.png"),
    "tradingview_1h": ("tradingview_btc_1h.png", "tradingview_btc_1h_liq.png"),
    "tradingview_15m": ("tradingview_btc_15m.png", "tradingview_btc_15m_liq.png"),
}
SOURCE_COMPLETENESS = {
    "blockbeats": "all",
    "coinglass": "all",
    "exocharts": "all",
    "fedwatch": "any",
    "farside_btc_etf": "all",
    "tradingview_1d": "all",
    "tradingview_4h": "all",
    "tradingview_1h": "all",
    "tradingview_15m": "all",
}

REQUIRED_SOURCES = frozenset(SOURCE_PATTERNS)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_fingerprint(entries: Iterable[dict]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["path"]):
        digest.update(entry["path"].encode("utf-8"))
        digest.update(entry["sha256"].encode("ascii"))
    return digest.hexdigest()


def scan_source_snapshot(inbox: Path) -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for source, names in SOURCE_PATTERNS.items():
        entries = []
        for name in names:
            path = inbox / name
            if not path.is_file():
                continue
            stat = path.stat()
            if stat.st_size <= 0:
                continue
            entries.append(
                {
                    "path": name,
                    "sha256": file_sha256(path),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
        present = {entry["path"] for entry in entries}
        required = set(names)
        completeness = SOURCE_COMPLETENESS[source]
        mechanically_complete = (
            bool(present & required)
            if completeness == "any"
            else required.issubset(present)
        )
        valid = mechanically_complete
        invalid_reasons: list[str] = []
        if source == "blockbeats" and mechanically_complete:
            try:
                payload = json.loads((inbox / "blockbeats.json").read_text(encoding="utf-8"))
                if payload.get("important_only") is not True:
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json must record important_only=true"
                    )
                if payload.get("capture_window_hours") != 12:
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json must record capture_window_hours=12"
                    )
                if (
                    payload.get("selection_policy")
                    != "last_12h_all_important_then_top3_by_fundamental_priority"
                ):
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json must record 12h top3 selection_policy"
                    )
                if payload.get("window_covered") is not True:
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json must prove the 12h window was fully covered"
                    )
                candidate_rows = payload.get("candidate_rows")
                selected_rows = payload.get("selected_rows")
                rows = payload.get("rows")
                if not isinstance(candidate_rows, list) or len(candidate_rows) < 3:
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json must include at least 3 candidate_rows from the 12h window"
                    )
                if not isinstance(selected_rows, list) or len(selected_rows) != 3:
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json must include exactly 3 selected_rows"
                    )
                if not isinstance(rows, list) or len(rows) != 3:
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json rows must expose exactly the selected top3"
                    )
                elif isinstance(selected_rows, list) and rows != selected_rows:
                    valid = False
                    invalid_reasons.append(
                        "blockbeats.json rows must equal selected_rows exactly"
                    )
            except (OSError, UnicodeError, json.JSONDecodeError):
                valid = False
                invalid_reasons.append("blockbeats.json is not valid UTF-8 JSON")
        if source == "farside_btc_etf" and mechanically_complete:
            try:
                payload = json.loads(
                    (inbox / "farside_btc_etf.json").read_text(encoding="utf-8")
                )
                if payload.get("source") != "farside_btc_etf":
                    valid = False
                    invalid_reasons.append(
                        "farside_btc_etf.json must record source=farside_btc_etf"
                    )
                url = payload.get("url")
                if not isinstance(url, str) or not url.startswith(
                    "https://farside.co.uk/btc"
                ):
                    valid = False
                    invalid_reasons.append(
                        "farside_btc_etf.json must record the Farside BTC URL"
                    )
                if payload.get("unit") != "US$m":
                    valid = False
                    invalid_reasons.append(
                        "farside_btc_etf.json must record unit=US$m"
                    )
                latest = payload.get("latest")
                if not isinstance(latest, dict):
                    valid = False
                    invalid_reasons.append(
                        "farside_btc_etf.json must include latest flow row"
                    )
                else:
                    total = latest.get("total_usd_m")
                    if not isinstance(total, (int, float)) or isinstance(total, bool):
                        valid = False
                        invalid_reasons.append(
                            "farside_btc_etf.json latest.total_usd_m must be numeric"
                        )
                    else:
                        expected_direction = (
                            "inflow" if total > 0 else "outflow" if total < 0 else "flat"
                        )
                        if latest.get("direction") != expected_direction:
                            valid = False
                            invalid_reasons.append(
                                "farside_btc_etf.json latest.direction must match total_usd_m"
                            )
                    if not isinstance(latest.get("date"), str) or not latest["date"].strip():
                        valid = False
                        invalid_reasons.append(
                            "farside_btc_etf.json latest.date must be present"
                        )
                    funds = latest.get("funds")
                    published_fund_values = (
                        [
                            value
                            for value in funds.values()
                            if isinstance(value, (int, float))
                            and not isinstance(value, bool)
                        ]
                        if isinstance(funds, dict)
                        else []
                    )
                    if not published_fund_values:
                        valid = False
                        invalid_reasons.append(
                            "farside_btc_etf.json latest row must contain at least one published fund value"
                        )
                rows = payload.get("rows")
                if not isinstance(rows, list) or not rows:
                    valid = False
                    invalid_reasons.append(
                        "farside_btc_etf.json must include parsed daily rows"
                    )
                validity = payload.get("validity")
                required_flags = [
                    "title_match",
                    "table_found",
                    "has_total_column",
                    "latest_daily_row",
                    "latest_total_is_number",
                    "latest_row_complete",
                ]
                if not isinstance(validity, dict):
                    valid = False
                    invalid_reasons.append(
                        "farside_btc_etf.json must include validity object"
                    )
                else:
                    failed_flags = [
                        flag for flag in required_flags if validity.get(flag) is not True
                    ]
                    if failed_flags:
                        valid = False
                        invalid_reasons.append(
                            "farside_btc_etf.json failed validity flags: "
                            + ", ".join(failed_flags)
                        )
            except (OSError, UnicodeError, json.JSONDecodeError):
                valid = False
                invalid_reasons.append("farside_btc_etf.json is not valid UTF-8 JSON")
        snapshot[source] = {
            "valid": valid,
            "mechanically_complete": mechanically_complete,
            "completeness_rule": completeness,
            "missing_artifacts": sorted(required - present),
            "invalid_reasons": invalid_reasons,
            "files": entries,
            "fingerprint": aggregate_fingerprint(entries) if entries else None,
        }

    heatmaps = sorted(inbox.glob("liqheatmap_*.png"))
    entries = []
    for path in heatmaps:
        stat = path.stat()
        if stat.st_size <= 0:
            continue
        entries.append(
            {
                "path": path.name,
                "sha256": file_sha256(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    snapshot["liqheatmap"] = {
        "valid": bool(entries),
        "files": entries,
        "fingerprint": aggregate_fingerprint(entries) if entries else None,
        "optional": True,
    }
    return snapshot


def compare_snapshots(
    previous: dict[str, dict] | None,
    current: dict[str, dict],
    *,
    slot: str | None = None,
) -> dict:
    previous = previous or {}
    changed = {
        source
        for source, state in current.items()
        if state.get("fingerprint") != previous.get(source, {}).get("fingerprint")
    }
    missing = {
        source
        for source in REQUIRED_SOURCES
        if not current.get(source, {}).get("valid")
    }
    return {
        "changed_sources": sorted(changed),
        "unchanged_sources": sorted(set(current) - changed),
        "missing_required_sources": sorted(missing),
        "source_affected_nodes": sorted(affected_nodes(changed)),
        "invalidated_nodes": sorted(required_analysis_nodes(slot)),
    }


def full_invalidation(reason: str, *, slot: str | None = None) -> dict:
    return {
        "full_recollection_required": True,
        "recollection_reasons": [reason],
        "invalidated_nodes": sorted(required_analysis_nodes(slot)),
    }
