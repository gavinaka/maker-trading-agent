"""Mechanical, non-business outcome emitted for each terminal vNext run.

The outcome is an audit/export surface.  It is deliberately excluded from the
production reasoning context and contains no market facts, positions, scores,
PnL, or free-text defect messages.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .effort_policy import REQUESTED_EFFORT, REQUESTED_MODEL
from .methodology import (
    MethodologyIdentity,
    canonical_sha256,
    sha256_file,
    validate_run_authority_binding,
    validate_run_authority_profile,
)


SCHEMA_VERSION = "vnext-sample-outcome-v6"
V5_SCHEMA_VERSION = "vnext-sample-outcome-v5"
V4_SCHEMA_VERSION = "vnext-sample-outcome-v4"
V3_SCHEMA_VERSION = "vnext-sample-outcome-v3"
V2_SCHEMA_VERSION = "vnext-sample-outcome-v2"
V1_SCHEMA_VERSION = "vnext-sample-outcome-v1"
SUPPORTED_SCHEMA_VERSIONS = {
    V1_SCHEMA_VERSION,
    V2_SCHEMA_VERSION,
    V3_SCHEMA_VERSION,
    V4_SCHEMA_VERSION,
    V5_SCHEMA_VERSION,
    SCHEMA_VERSION,
}
EVIDENCE_PROVENANCE_SCHEMA_VERSIONS = {
    V3_SCHEMA_VERSION,
    V4_SCHEMA_VERSION,
    V5_SCHEMA_VERSION,
    SCHEMA_VERSION,
}
FULL_PROVENANCE_SCHEMA_VERSIONS = {
    V4_SCHEMA_VERSION,
    V5_SCHEMA_VERSION,
    SCHEMA_VERSION,
}
AUTHORITY_EPOCH_SCHEMA_VERSIONS = {
    V2_SCHEMA_VERSION,
    V3_SCHEMA_VERSION,
    V4_SCHEMA_VERSION,
    V5_SCHEMA_VERSION,
}
TRIPLE_AUTHORITY_SCHEMA_VERSIONS = {SCHEMA_VERSION}
TERMINAL_STATUSES = {"complete", "shadow_complete", "retired"}
STAGES = ("evidence", "reasoning", "decision", "report", "delivery")
EVIDENCE_PROVENANCE_MODES = {
    "fresh_full_recollection",
    "immutable_replay",
    "unknown",
}
RATE_EXPECTATION_PROVENANCE = {
    (
        "cme_fedwatch_ui",
        "cme_target_rate_probability",
        "cme_canonical",
    ),
    (
        "kalshi_public_market_data_api",
        "independent_event_contract_market",
        "kalshi_plan_c_observation",
    ),
    ("unknown", "unknown", "unknown"),
}
SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _payload_sha256(payload: dict[str, Any], hash_field: str) -> str:
    clean = dict(payload)
    clean.pop(hash_field, None)
    encoded = json.dumps(
        clean,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _requested_effort_matches_schema(schema_version: object, effort: object) -> bool:
    if schema_version in {V5_SCHEMA_VERSION, SCHEMA_VERSION}:
        return effort == REQUESTED_EFFORT
    if schema_version in {V3_SCHEMA_VERSION, V4_SCHEMA_VERSION}:
        return effort == "high"
    return effort in {"high", "max"}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path.name}")
    return payload


def _parse_iso(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("sample outcome timestamp must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("sample outcome timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("sample outcome timestamp must include a timezone")
    return parsed


def _load_run(repo_root: Path, run_root: Path) -> dict[str, Any]:
    payload = _load_json(run_root / "run.json")
    recorded_hash = payload.get("run_sha256")
    clean = dict(payload)
    clean.pop("run_sha256", None)
    schema_version = payload.get("schema_version")
    if (
        schema_version not in {"daily-run-vnext-v1", "daily-run-vnext-v2"}
        or recorded_hash != canonical_sha256(clean)
    ):
        raise ValueError("invalid vNext run metadata")
    if schema_version == "daily-run-vnext-v2":
        run_mode = payload.get("run_mode")
        expected_kind = (
            "explicit_shadow_test_approval"
            if run_mode == "shadow"
            else "explicit_production_cutover_approval"
            if run_mode == "production"
            else None
        )
        if (
            expected_kind is None
            or payload.get("authorization_kind") != expected_kind
            or not SHA256_RE.fullmatch(
                str(payload.get("authorization_ref_sha256", ""))
            )
        ):
            raise ValueError("invalid vNext run mode authorization binding")
        try:
            validate_run_authority_profile(payload)
        except ValueError as exc:
            raise ValueError("invalid vNext run authority binding") from exc
    expected = (
        repo_root
        / "runtime_state_vnext"
        / str(payload.get("trading_date", ""))
        / str(payload.get("slot", ""))
        / str(payload.get("run_id", ""))
    ).resolve()
    if expected != run_root:
        raise ValueError("sample outcome run path does not match run metadata")
    return payload


def _load_checkpoint(run_root: Path) -> dict[str, Any]:
    payload = _load_json(run_root / "checkpoint.json")
    recorded_hash = payload.get("checkpoint_sha256")
    clean = dict(payload)
    clean.pop("checkpoint_sha256", None)
    if (
        payload.get("schema_version") != "daily-checkpoint-vnext-v1"
        or recorded_hash != canonical_sha256(clean)
    ):
        raise ValueError("invalid vNext checkpoint")
    if payload.get("status") not in TERMINAL_STATUSES:
        raise ValueError("sample outcome is only emitted for a terminal run")
    return payload


def _load_authority_identity(
    run_root: Path,
    run: dict[str, Any],
) -> MethodologyIdentity:
    payload = _load_json(run_root / "methodology_manifest.json")
    try:
        return validate_run_authority_binding(run, payload)
    except ValueError as exc:
        raise ValueError("sample outcome authority binding is invalid") from exc


def _load_completed_manifest(
    repo_root: Path,
    run_root: Path,
    checkpoint: dict[str, Any],
    stage: str,
) -> dict[str, Any] | None:
    completed = checkpoint.get("completed", {}).get(stage)
    if not isinstance(completed, dict):
        return None
    path = (repo_root / str(completed.get("manifest_path", ""))).resolve()
    try:
        path.relative_to(run_root)
    except ValueError as exc:
        raise ValueError(f"completed {stage} manifest escapes the run") from exc
    if not path.is_file() or sha256_file(path) != completed.get("manifest_sha256"):
        raise ValueError(f"completed {stage} manifest binding is invalid")
    payload = _load_json(path)
    if (
        payload.get("schema_version") != "stage-manifest-vnext-v1"
        or payload.get("stage") != stage
        or payload.get("status") != "passed"
        or payload.get("manifest_sha256") != canonical_sha256(payload)
        or payload.get("outputs") != completed.get("outputs")
    ):
        raise ValueError(f"completed {stage} manifest is invalid")
    return payload


def _load_evidence_provenance(
    repo_root: Path,
    run_root: Path,
    checkpoint: dict[str, Any],
) -> dict[str, str]:
    manifest = _load_completed_manifest(
        repo_root,
        run_root,
        checkpoint,
        "evidence",
    )
    if manifest is None:
        return {
            "mode": "unknown",
            "provider_id": "unknown",
            "method_class": "unknown",
            "sample_source_class": "unknown",
        }
    record = manifest.get("outputs", {}).get("evidence")
    if not isinstance(record, dict):
        raise ValueError("completed evidence output binding is missing")
    path = (repo_root / str(record.get("path", ""))).resolve()
    try:
        path.relative_to(run_root)
    except ValueError as exc:
        raise ValueError("completed evidence output escapes the run") from exc
    if (
        not path.is_file()
        or sha256_file(path) != record.get("sha256")
        or path.stat().st_size != record.get("bytes")
    ):
        raise ValueError("completed evidence output binding is invalid")
    evidence = _load_json(path)
    capture_mode = evidence.get("capture_mode")
    mode = {
        "full_base": "fresh_full_recollection",
        "full_recollection": "fresh_full_recollection",
        "immutable_evidence_replay": "immutable_replay",
    }.get(capture_mode, "unknown")
    fedwatch = (evidence.get("sources") or {}).get("FedWatch")
    meta = fedwatch.get("meta") if isinstance(fedwatch, dict) else None
    evidence_schema = evidence.get("schema_version")
    if evidence_schema == "evidence-snapshot-v1":
        if isinstance(meta, dict) and any(
            meta.get(field)
            for field in ("provider_id", "method_class", "sample_source_class")
        ):
            raise ValueError("legacy evidence cannot assert rate-expectation provenance")
        provider_tuple = ("unknown", "unknown", "unknown")
    elif evidence_schema == "evidence-snapshot-v2":
        provider_tuple = (
            str(meta.get("provider_id") or "unknown"),
            str(meta.get("method_class") or "unknown"),
            str(meta.get("sample_source_class") or "unknown"),
        ) if isinstance(meta, dict) else ("unknown", "unknown", "unknown")
        if provider_tuple not in RATE_EXPECTATION_PROVENANCE - {
            ("unknown", "unknown", "unknown")
        }:
            raise ValueError("current evidence rate-expectation provenance is invalid")
    else:
        raise ValueError("sample outcome evidence schema is unsupported")
    return {
        "mode": mode,
        "provider_id": provider_tuple[0],
        "method_class": provider_tuple[1],
        "sample_source_class": provider_tuple[2],
    }


def _failure_inventory(run_root: Path) -> tuple[dict[str, int], list[dict[str, Any]]]:
    stage_failure_counts = {stage: 0 for stage in STAGES}
    cluster_counts: dict[tuple[str, str, str], int] = {}
    for stage in STAGES:
        for path in sorted((run_root / stage).glob("attempt-*/failure.json")):
            payload = _load_json(path)
            recorded_hash = payload.get("failure_sha256")
            clean = dict(payload)
            clean.pop("failure_sha256", None)
            if (
                payload.get("schema_version") != "stage-failure-vnext-v1"
                or payload.get("stage") != stage
                or payload.get("status") != "failed"
                or recorded_hash != canonical_sha256(clean)
            ):
                raise ValueError(f"invalid vNext failure record in {stage}")
            stage_failure_counts[stage] += 1
            failure_class = str(payload.get("failure_class", "unclassified"))
            defects = payload.get("defects")
            codes = sorted(
                {
                    str(defect.get("code"))
                    for defect in defects
                    if isinstance(defect, dict) and str(defect.get("code", "")).strip()
                }
            ) if isinstance(defects, list) else []
            for code in codes or ["unclassified"]:
                key = (stage, failure_class, code)
                cluster_counts[key] = cluster_counts.get(key, 0) + 1
    clusters = []
    for (stage, failure_class, defect_code), count in sorted(cluster_counts.items()):
        fingerprint_source = {
            "stage": stage,
            "failure_class": failure_class,
            "defect_code": defect_code,
        }
        clusters.append(
            {
                **fingerprint_source,
                "fingerprint": _payload_sha256(fingerprint_source, "unused"),
                "count": count,
            }
        )
    return stage_failure_counts, clusters


def _orphan_inventory(run_root: Path) -> dict[str, int]:
    counts = {stage: 0 for stage in STAGES}
    for stage in STAGES:
        for path in sorted((run_root / stage).glob("attempt-*/orphaned.json")):
            payload = _load_json(path)
            recorded_hash = payload.get("orphan_sha256")
            clean = dict(payload)
            clean.pop("orphan_sha256", None)
            if (
                payload.get("schema_version") != "stage-orphan-vnext-v1"
                or payload.get("stage") != stage
                or recorded_hash != canonical_sha256(clean)
            ):
                raise ValueError(f"invalid vNext orphan record in {stage}")
            counts[stage] += 1
    return counts


def build_sample_outcome(*, repo_root: Path, run_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    run_root = run_root.resolve()
    run_root.relative_to(repo_root / "runtime_state_vnext")
    run = _load_run(repo_root, run_root)
    checkpoint = _load_checkpoint(run_root)
    authority_identity = _load_authority_identity(run_root, run)
    schema_version = (
        V5_SCHEMA_VERSION
        if authority_identity.legacy_combined_identity
        else SCHEMA_VERSION
    )
    if any(checkpoint.get(key) != run.get(key) for key in ("run_id", "trading_date", "slot")):
        raise ValueError("sample outcome run/checkpoint identity mismatch")

    stage_attempt_counts = {
        stage: len([path for path in (run_root / stage).glob("attempt-*") if path.is_dir()])
        for stage in STAGES
    }
    stage_failure_counts, failure_clusters = _failure_inventory(run_root)
    stage_orphan_counts = _orphan_inventory(run_root)
    manual_review_count = len(list((run_root / "manual_reviews").glob("review-*.json")))

    report_manifest = _load_completed_manifest(repo_root, run_root, checkpoint, "report")
    delivery_manifest = _load_completed_manifest(repo_root, run_root, checkpoint, "delivery")
    evidence_provenance = _load_evidence_provenance(
        repo_root,
        run_root,
        checkpoint,
    )
    report_facts = (
        report_manifest.get("gate", {}).get("facts", {})
        if isinstance(report_manifest, dict)
        else {}
    )
    depth = report_facts.get("human_reasoning_depth")
    template = report_facts.get("gold_template_fidelity")
    quality_contracts = {
        "report_compilation_passed": (
            report_manifest.get("gate", {}).get("passed") is True
            if report_manifest is not None
            else None
        ),
        "human_reasoning_depth_passed": (
            depth.get("passed") is True if isinstance(depth, dict) else None
        ),
        "gold_template_fidelity_passed": (
            template.get("passed") is True if isinstance(template, dict) else None
        ),
        "delivery_integrity_passed": (
            delivery_manifest.get("gate", {}).get("passed") is True
            if delivery_manifest is not None
            else None
        ),
    }

    created_at = _parse_iso(run.get("created_at"))
    updated_at = _parse_iso(checkpoint.get("updated_at"))
    elapsed_seconds = max(0, int((updated_at - created_at).total_seconds()))
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "run": {
            "run_id": run["run_id"],
            "trading_date": run["trading_date"],
            "slot": run["slot"],
            "terminal_status": checkpoint["status"],
            "created_at": run["created_at"],
            "updated_at": checkpoint["updated_at"],
            "requested_model": run["requested_model"],
            "requested_effort": run["requested_effort"],
        },
        "bindings": {
            "run_sha256": run["run_sha256"],
            "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        },
        "process": {
            "stage_attempt_counts": stage_attempt_counts,
            "stage_failure_counts": stage_failure_counts,
            "stage_orphan_counts": stage_orphan_counts,
            "total_attempts": sum(stage_attempt_counts.values()),
            "local_retry_count": sum(max(0, count - 1) for count in stage_attempt_counts.values()),
            "manual_review_count": manual_review_count,
            "elapsed_seconds": elapsed_seconds,
        },
        "quality_contracts": quality_contracts,
        "evidence_provenance": evidence_provenance,
        "failure_clusters": failure_clusters,
        "observer_boundary": {
            "blocking": False,
            "production_context_input": False,
            "contains_business_conclusions": False,
        },
    }
    if authority_identity.legacy_combined_identity:
        payload["bindings"]["authority_epoch_sha256"] = (
            authority_identity.manifest_sha256
        )
    else:
        payload["bindings"].update(
            {
                "semantic_contract_sha256": (
                    authority_identity.semantic_contract_sha256
                ),
                "release_sha256": authority_identity.release_sha256,
                "methodology_manifest_sha256": (
                    authority_identity.manifest_sha256
                ),
            }
        )
    payload["sample_outcome_sha256"] = _payload_sha256(payload, "sample_outcome_sha256")
    validate_sample_outcome(payload)
    return payload


def validate_sample_outcome(payload: dict[str, Any]) -> None:
    expected_top = {
        "schema_version",
        "run",
        "bindings",
        "process",
        "quality_contracts",
        "failure_clusters",
        "observer_boundary",
        "sample_outcome_sha256",
    }
    schema_version = payload.get("schema_version")
    if schema_version in EVIDENCE_PROVENANCE_SCHEMA_VERSIONS:
        expected_top.add("evidence_provenance")
    if set(payload) != expected_top or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("sample outcome has an unsupported shape or schema")
    if payload.get("sample_outcome_sha256") != _payload_sha256(payload, "sample_outcome_sha256"):
        raise ValueError("sample outcome hash mismatch")
    run = payload.get("run")
    if not isinstance(run, dict) or set(run) != {
        "run_id", "trading_date", "slot", "terminal_status", "created_at", "updated_at",
        "requested_model", "requested_effort",
    }:
        raise ValueError("sample outcome run identity is invalid")
    if run.get("terminal_status") not in TERMINAL_STATUSES:
        raise ValueError("sample outcome must describe a terminal run")
    if (
        not re.fullmatch(r"run-[A-Za-z0-9_.-]{4,80}", str(run.get("run_id", "")))
        or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(run.get("trading_date", "")))
        or run.get("slot") not in {"morning", "midday", "evening"}
        or run.get("requested_model") != REQUESTED_MODEL
        or not _requested_effort_matches_schema(
            schema_version, run.get("requested_effort")
        )
    ):
        raise ValueError("sample outcome run values are invalid")
    _parse_iso(run.get("created_at"))
    _parse_iso(run.get("updated_at"))
    bindings = payload.get("bindings")
    expected_bindings = {"run_sha256", "checkpoint_sha256"}
    if schema_version in AUTHORITY_EPOCH_SCHEMA_VERSIONS:
        expected_bindings.add("authority_epoch_sha256")
    if schema_version in TRIPLE_AUTHORITY_SCHEMA_VERSIONS:
        expected_bindings.update(
            {
                "semantic_contract_sha256",
                "release_sha256",
                "methodology_manifest_sha256",
            }
        )
    if not isinstance(bindings, dict) or set(bindings) != expected_bindings:
        raise ValueError("sample outcome bindings are invalid")
    if any(not isinstance(value, str) or not SHA256_RE.fullmatch(value) for value in bindings.values()):
        raise ValueError("sample outcome bindings must be SHA-256 values")
    if schema_version == V3_SCHEMA_VERSION:
        provenance = payload.get("evidence_provenance")
        if (
            not isinstance(provenance, dict)
            or set(provenance) != {"mode"}
            or provenance.get("mode") not in EVIDENCE_PROVENANCE_MODES
        ):
            raise ValueError("sample outcome evidence provenance is invalid")
    if schema_version in FULL_PROVENANCE_SCHEMA_VERSIONS:
        provenance = payload.get("evidence_provenance")
        if (
            not isinstance(provenance, dict)
            or set(provenance) != {
                "mode",
                "provider_id",
                "method_class",
                "sample_source_class",
            }
            or provenance.get("mode") not in EVIDENCE_PROVENANCE_MODES
            or (
                provenance.get("provider_id"),
                provenance.get("method_class"),
                provenance.get("sample_source_class"),
            ) not in RATE_EXPECTATION_PROVENANCE
        ):
            raise ValueError("sample outcome evidence provenance is invalid")
    process = payload.get("process")
    if not isinstance(process, dict) or set(process) != {
        "stage_attempt_counts", "stage_failure_counts", "stage_orphan_counts",
        "total_attempts", "local_retry_count", "manual_review_count", "elapsed_seconds",
    }:
        raise ValueError("sample outcome process metrics are invalid")
    for field in ("stage_attempt_counts", "stage_failure_counts", "stage_orphan_counts"):
        values = process.get(field)
        if not isinstance(values, dict) or set(values) != set(STAGES):
            raise ValueError(f"sample outcome {field} is invalid")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values.values()):
            raise ValueError(f"sample outcome {field} must contain non-negative integers")
    for field in ("total_attempts", "local_retry_count", "manual_review_count", "elapsed_seconds"):
        value = process.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"sample outcome {field} must be a non-negative integer")
    if process["total_attempts"] != sum(process["stage_attempt_counts"].values()):
        raise ValueError("sample outcome total_attempts does not match stage counts")
    if process["local_retry_count"] != sum(
        max(0, count - 1) for count in process["stage_attempt_counts"].values()
    ):
        raise ValueError("sample outcome local_retry_count does not match stage counts")
    if any(
        process["stage_failure_counts"][stage] > process["stage_attempt_counts"][stage]
        for stage in STAGES
    ):
        raise ValueError("sample outcome failure count exceeds attempt count")
    quality = payload.get("quality_contracts")
    if not isinstance(quality, dict) or set(quality) != {
        "report_compilation_passed", "human_reasoning_depth_passed",
        "gold_template_fidelity_passed", "delivery_integrity_passed",
    } or any(value not in {True, False, None} for value in quality.values()):
        raise ValueError("sample outcome quality contract flags are invalid")
    clusters = payload.get("failure_clusters")
    if not isinstance(clusters, list):
        raise ValueError("sample outcome failure clusters must be a list")
    for cluster in clusters:
        if not isinstance(cluster, dict) or set(cluster) != {
            "stage", "failure_class", "defect_code", "fingerprint", "count",
        }:
            raise ValueError("sample outcome failure cluster is invalid")
        source = {key: cluster[key] for key in ("stage", "failure_class", "defect_code")}
        if (
            cluster.get("stage") not in STAGES
            or not SAFE_CODE_RE.fullmatch(str(cluster.get("failure_class", "")))
            or not SAFE_CODE_RE.fullmatch(str(cluster.get("defect_code", "")))
            or cluster.get("fingerprint") != _payload_sha256(source, "unused")
        ):
            raise ValueError("sample outcome failure fingerprint is invalid")
        if not isinstance(cluster.get("count"), int) or isinstance(cluster.get("count"), bool) or cluster["count"] < 1:
            raise ValueError("sample outcome failure count is invalid")
    if payload.get("observer_boundary") != {
        "blocking": False,
        "production_context_input": False,
        "contains_business_conclusions": False,
    }:
        raise ValueError("sample outcome observer boundary is invalid")


def write_sample_outcome(*, repo_root: Path, run_root: Path) -> dict[str, Any]:
    target = run_root.resolve() / "sample_outcome.json"
    if target.exists():
        existing = _load_json(target)
        validate_sample_outcome(existing)
        run = _load_run(repo_root.resolve(), run_root.resolve())
        checkpoint = _load_checkpoint(run_root.resolve())
        if (
            any(
                existing["run"].get(key) != run.get(key)
                for key in ("run_id", "trading_date", "slot")
            )
            or existing["run"].get("terminal_status") != checkpoint.get("status")
            or existing["bindings"].get("run_sha256") != run.get("run_sha256")
            or existing["bindings"].get("checkpoint_sha256")
            != checkpoint.get("checkpoint_sha256")
        ):
            raise ValueError("immutable sample outcome differs from terminal run state")
        authority_identity = _load_authority_identity(run_root.resolve(), run)
        if existing.get("schema_version") in AUTHORITY_EPOCH_SCHEMA_VERSIONS:
            if (
                not authority_identity.legacy_combined_identity
                or existing["bindings"].get("authority_epoch_sha256")
                != authority_identity.manifest_sha256
            ):
                raise ValueError(
                    "immutable sample outcome authority epoch differs from run"
                )
        if existing.get("schema_version") in TRIPLE_AUTHORITY_SCHEMA_VERSIONS:
            expected = {
                "semantic_contract_sha256": (
                    authority_identity.semantic_contract_sha256
                ),
                "release_sha256": authority_identity.release_sha256,
                "methodology_manifest_sha256": (
                    authority_identity.manifest_sha256
                ),
            }
            if authority_identity.legacy_combined_identity or any(
                existing["bindings"].get(field) != value
                for field, value in expected.items()
            ):
                raise ValueError(
                    "immutable sample outcome authority triple differs from run"
                )
        return existing
    payload = build_sample_outcome(repo_root=repo_root, run_root=run_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return payload
