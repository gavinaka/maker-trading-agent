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
            except (OSError, UnicodeError, json.JSONDecodeError):
                valid = False
                invalid_reasons.append("blockbeats.json is not valid UTF-8 JSON")
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
