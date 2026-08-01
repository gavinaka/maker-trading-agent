"""Read-only adapter from the current immutable capture manifest to vNext.

The adapter never recaptures, edits, moves, or copies evidence.  It verifies
the existing snapshot and emits a new hash-bound evidence contract for shadow
runs.
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .artifacts import _exclusive_json
from .gates import SOURCE_ROLES, evaluate_evidence
from .methodology import load_scoring_policy, sha256_file
from .rate_expectation import validate_rate_provenance


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_IDENTITY_PATTERN = re.compile(r"[0-9a-f-]{16,64}", re.I)


def _source_for_filename(filename: str) -> str:
    name = filename.lower()
    if name.startswith("blockbeats"):
        return "BlockBeats"
    if name.startswith("coinglass") or name.startswith("liqheatmap"):
        return "Coinglass"
    if name.startswith("exocharts"):
        return "Exocharts"
    if name.startswith("fedwatch") or name in {
        "cme_fedwatch_result.json",
        "kalshi_feddecision_raw.json",
        "rate_expectation_provenance.json",
    }:
        return "FedWatch"
    if name.startswith("farside"):
        return "Farside"
    if name.startswith("tradingview"):
        return "TradingView"
    raise ValueError(f"unmapped capture evidence file: {filename}")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _collector_exit_codes(payload: dict[str, Any]) -> list[Any]:
    result_groups = payload.get("results")
    if isinstance(result_groups, dict):
        result_groups = [result_groups]
    if not isinstance(result_groups, list) or not result_groups:
        raise ValueError("legacy capture result map is missing")
    exit_codes = [
        value
        for group in result_groups
        if isinstance(group, dict)
        for value in group.values()
    ]
    if not exit_codes:
        raise ValueError("legacy capture result map is empty")
    return exit_codes


def _rate_expectation_meta(
    *,
    snapshot_root: Path,
    grouped_records: list[dict[str, Any]],
    capture_run_id: str,
    root: Path,
) -> tuple[str, dict[str, Any]]:
    """Return evidence schema and contract-derived compatibility metadata.

    Legacy snapshots containing only ``fedwatch.png`` remain v1-compatible.
    Once a provenance artifact is present, the snapshot is v2 and all provider
    identity is derived from the hash-bound provider contract rather than
    trusted from capture output.
    """

    names = {Path(record["path"]).name for record in grouped_records}
    new_names = {
        "cme_fedwatch_result.json",
        "kalshi_feddecision_raw.json",
        "rate_expectation_provenance.json",
    }
    if names.isdisjoint(new_names):
        return "evidence-snapshot-v1", {}
    provenance_path = snapshot_root / "rate_expectation_provenance.json"
    if not provenance_path.is_file():
        raise ValueError("rate-expectation provider provenance is missing")
    provenance = _load_json(provenance_path)
    contract = _load_json(root / "data_sources" / "rate_expectation_provider_contract.json")
    meta = validate_rate_provenance(
        provenance,
        contract,
        capture_run_id=capture_run_id,
        artifact_names=names,
    )
    return "evidence-snapshot-v2", meta


def _validated_profile_binding(
    manifest: dict[str, Any],
    *,
    capture_run_id: str,
    root: Path,
) -> dict[str, Any]:
    profile_policy = load_scoring_policy(root=root)["tradingview_profile_policy"]
    binding = manifest.get("tradingview_profile_binding")
    expected_keys = {
        "schema_version",
        "capture_run_id",
        "capture_nonce",
        "sidecar_filename",
        "sidecar_schema_version",
    }
    if not isinstance(binding, dict) or set(binding) != expected_keys:
        raise ValueError("legacy capture TradingView profile binding is missing or malformed")
    nonce = str(binding.get("capture_nonce", ""))
    if (
        binding.get("schema_version")
        != profile_policy["state_sidecar_binding_schema_version"]
        or str(binding.get("capture_run_id", "")) != capture_run_id
        or not CAPTURE_IDENTITY_PATTERN.fullmatch(nonce)
        or binding.get("sidecar_filename") != profile_policy["state_sidecar_filename"]
        or binding.get("sidecar_schema_version")
        != profile_policy["state_sidecar_schema_version"]
    ):
        raise ValueError("legacy capture TradingView profile binding differs from current evidence run")
    return binding


def _validate_fallback_lineage(
    manifest: dict[str, Any],
    *,
    root: Path,
    trading_date: str,
    slot: str,
    evidence_capture_run_id: str,
    snapshot: dict[str, Any],
    profile_binding: dict[str, Any],
) -> None:
    if manifest.get("fallback_code") != 0:
        raise ValueError("legacy full-capture fallback is not successful")
    record = manifest.get("fallback_manifest")
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise ValueError("legacy fallback manifest record is missing or malformed")
    relative = str(record.get("path", ""))
    state_root = (root / "runtime_state" / trading_date).resolve()
    target = (state_root / relative).resolve()
    expected_root = (state_root / "captures" / slot).resolve()
    try:
        target.relative_to(expected_root)
    except ValueError as exc:
        raise ValueError("legacy fallback manifest escapes the current slot") from exc
    expected_name = f"full_recollection_{evidence_capture_run_id}.json"
    if target.name != expected_name or not target.is_file():
        raise ValueError("legacy fallback manifest identity differs from evidence_capture_run_id")
    if sha256_file(target) != str(record.get("sha256", "")):
        raise ValueError("legacy fallback manifest hash changed")
    fallback = _load_json(target)
    if (
        fallback.get("success") is not True
        or fallback.get("mode") != "full_recollection"
        or str(fallback.get("run_id", "")) != evidence_capture_run_id
        or str(fallback.get("evidence_capture_run_id", ""))
        != evidence_capture_run_id
        or fallback.get("evidence_snapshot") != snapshot
        or fallback.get("tradingview_profile_binding") != profile_binding
        or any(value != 0 for value in _collector_exit_codes(fallback))
    ):
        raise ValueError("legacy fallback manifest does not bind the selected evidence snapshot")


def adapt_legacy_capture(
    manifest_path: Path,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest_path.relative_to(root / "runtime_state")
    manifest = _load_json(manifest_path)
    trading_date = str(manifest.get("date", ""))
    slot = str(manifest.get("slot", ""))
    expected_manifest_root = (root / "runtime_state" / trading_date / "captures" / slot).resolve()
    manifest_path.relative_to(expected_manifest_root)
    if manifest.get("success") is not True:
        raise ValueError("legacy capture manifest is not successful")
    manifest_run_id = str(manifest.get("run_id", ""))
    evidence_capture_run_id = str(manifest.get("evidence_capture_run_id", ""))
    if (
        not CAPTURE_IDENTITY_PATTERN.fullmatch(manifest_run_id)
        or not CAPTURE_IDENTITY_PATTERN.fullmatch(evidence_capture_run_id)
    ):
        raise ValueError("legacy capture run identity is missing or invalid")
    profile_binding = _validated_profile_binding(
        manifest,
        capture_run_id=evidence_capture_run_id,
        root=root,
    )
    snapshot = manifest.get("evidence_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("legacy capture evidence_snapshot is missing")
    snapshot_relative = str(snapshot.get("root", ""))
    expected_snapshot_relative = (
        Path("evidence") / slot / evidence_capture_run_id
    ).as_posix()
    if Path(snapshot_relative).as_posix() != expected_snapshot_relative:
        raise ValueError("legacy evidence snapshot root differs from evidence_capture_run_id")
    snapshot_root = (root / "runtime_state" / trading_date / snapshot_relative).resolve()
    expected_snapshot_root = (
        root
        / "runtime_state"
        / trading_date
        / "evidence"
        / slot
        / evidence_capture_run_id
    ).resolve()
    if snapshot_root != expected_snapshot_root:
        raise ValueError("legacy evidence snapshot resolved outside its current-run identity")
    if not snapshot_root.is_dir():
        raise ValueError("legacy evidence snapshot root is missing")
    fallback_used = manifest.get("full_fallback_used") is True
    if fallback_used:
        _validate_fallback_lineage(
            manifest,
            root=root,
            trading_date=trading_date,
            slot=slot,
            evidence_capture_run_id=evidence_capture_run_id,
            snapshot=snapshot,
            profile_binding=profile_binding,
        )
    elif (
        manifest_run_id != evidence_capture_run_id
        or any(value != 0 for value in _collector_exit_codes(manifest))
    ):
        raise ValueError("legacy capture contains a failed collector or cross-run evidence")
    files = snapshot.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("legacy evidence snapshot file list is empty")

    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in SOURCE_ROLES}
    frame_map = {
        "tradingview_btc_1d.png": "1D",
        "tradingview_btc_4h.png": "4H",
        "tradingview_btc_1h.png": "1H",
        "tradingview_btc_15m.png": "15m",
    }
    for index, record in enumerate(files):
        if not isinstance(record, dict):
            raise ValueError(f"legacy evidence file record {index} is invalid")
        relative = str(record.get("path", ""))
        target = (snapshot_root / relative).resolve()
        target.relative_to(snapshot_root)
        if not target.is_file():
            raise ValueError(f"legacy evidence file is missing: {relative}")
        expected_hash = str(record.get("sha256", ""))
        expected_size = record.get("size")
        if sha256_file(target) != expected_hash or target.stat().st_size != expected_size:
            raise ValueError(f"legacy evidence file changed: {relative}")
        source = _source_for_filename(relative)
        artifact = {
            "path": target.relative_to(root).as_posix(),
            "sha256": expected_hash,
            "bytes": expected_size,
        }
        lower_name = Path(relative).name.lower()
        if lower_name.startswith("liqheatmap"):
            artifact["kind"] = "liquidation_map"
        if lower_name in frame_map:
            artifact["timeframe"] = frame_map[lower_name]
        grouped[source].append(artifact)

    blockbeats = _load_json(snapshot_root / "blockbeats.json")
    farside = _load_json(snapshot_root / "farside_btc_etf.json")
    observed_at = str(manifest.get("completed_at") or snapshot.get("created_at") or "")
    sources: dict[str, dict[str, Any]] = {}
    for source, records in grouped.items():
        sources[source] = {
            "status": "valid",
            "role": SOURCE_ROLES[source],
            "observed_at": observed_at,
            "artifacts": records,
            "meta": {},
        }
    sources["BlockBeats"]["meta"] = {
        "important_only": blockbeats.get("important_only"),
        "capture_window_hours": blockbeats.get("capture_window_hours"),
        "window_covered": blockbeats.get("window_covered"),
        "selected_count_required": blockbeats.get("selected_count_required"),
        "selected_row_count": len(blockbeats.get("selected_rows") or []),
    }
    latest_farside = farside.get("latest") or {}
    total_usd_m = latest_farside.get("total_usd_m")
    try:
        total_value = Decimal(str(total_usd_m))
    except (InvalidOperation, ValueError):
        total_value = None
    sources["Farside"]["meta"] = {
        "latest_total_usd_m": total_usd_m,
        "latest_complete_date": latest_farside.get("date_iso") or latest_farside.get("date"),
        "flow_direction": (
            "inflow"
            if total_value is not None and total_value > 0
            else "outflow"
            if total_value is not None and total_value < 0
            else "flat"
        ),
    }
    present_names = {Path(record["path"]).name.lower() for record in grouped["TradingView"]}
    sources["TradingView"]["timeframes"] = [
        frame for filename, frame in frame_map.items() if filename in present_names
    ]
    evidence_schema, rate_meta = _rate_expectation_meta(
        snapshot_root=snapshot_root,
        grouped_records=grouped["FedWatch"],
        capture_run_id=evidence_capture_run_id,
        root=root,
    )
    sources["FedWatch"]["meta"] = rate_meta
    manifest_record = {
        "path": manifest_path.relative_to(root).as_posix(),
        "sha256": sha256_file(manifest_path),
        "bytes": manifest_path.stat().st_size,
    }
    payload: dict[str, Any] = {
        "schema_version": evidence_schema,
        "trading_date": trading_date,
        "slot": slot,
        "captured_at": observed_at,
        "capture_mode": manifest.get("mode"),
        "capture_run_id": evidence_capture_run_id,
        "tradingview_profile_binding": profile_binding,
        "capture_workflow_lease_id": manifest.get("workflow_lease_id"),
        "legacy_capture_manifest": manifest_record,
        "sources": sources,
    }
    gate = evaluate_evidence(payload, root=root)
    if not gate.passed:
        messages = "; ".join(f"{item.code}:{item.message}" for item in gate.defects)
        raise ValueError("adapted legacy evidence failed vNext gate: " + messages)
    payload["snapshot_sha256"] = gate.facts["snapshot_sha256"]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    payload = adapt_legacy_capture(args.manifest, root=args.root)
    _exclusive_json(args.output.resolve(), payload)
    print(json.dumps({"status": "adapted", "output": str(args.output), "snapshot_sha256": payload["snapshot_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
