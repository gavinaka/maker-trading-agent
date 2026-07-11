"""Parameter-driven Notion report publisher.

The payload contains block data and metadata, while the existing transactional
library remains the sole authority for freshness, publication, verification,
rollback, and live-page uniqueness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUTS_DIR = Path(__file__).resolve().parent
if str(OUTPUTS_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUTS_DIR))

from notion_push_lib import (
    assert_source_freshness,
    ensure_date_page,
    replace_page_transactional,
    run_report_lint,
)
from daily_color_template import style_daily_payload_children
from daily_payload_builder import validate_payload_derivation
from daily_publish_contract import (
    CRITICAL_REPORT_TEXT_PREFIXES,
    DAILY_PAYLOAD_TEXT_PREFIXES,
    DAILY_PAYLOAD_TYPES_BY_SLOT,
    FINAL_TEXT_PREFIXES,
    REQUIRED_SOURCE_LABELS,
    SOURCE_LABEL_FILES,
)
from report_structure_gate import (
    assert_combined_structure,
    display_date,
    strict_contract_active,
)
from review_contract import (
    CONTRACT_VERSION as REVIEW_CONTRACT_VERSION,
    REVIEW_FONT_TEMPLATE,
    SOURCE_KIND as REVIEW_SOURCE_KIND,
    validate_review_payload_colors,
    validate_review_payload_shape,
    validate_review_payload_source,
)
from runtime.reasoning_readiness import (
    report_preflight_required,
    validate_locked_report_for_output,
)
from runtime.state_store import atomic_json_write
from runtime.usage_logger import append_usage


REQUIRED = {
    "date",
    "title",
    "title_prefix",
    "verifier_mode",
    "report_path",
    "children",
    "image_after_heading",
    "image_paths",
}
DAILY_REQUIRED = REQUIRED | {"source_specs"}
LOCKED_TIMEPOINT_POLICY = "user_authorized_locked_evidence_delivery_v1"


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def validate_payload_preflight_binding(
    payload: dict,
    analysis_lock: dict | None,
    trading_date: str,
) -> dict:
    if not report_preflight_required(trading_date):
        return {"status": "not_required", "required_from": "2026-07-11"}
    if not isinstance(analysis_lock, dict):
        raise ValueError("daily payload blocked: missing analysis lock")
    validation = analysis_lock.get("analysis_validation")
    if not isinstance(validation, dict):
        raise ValueError("daily payload blocked: analysis lock has no validation record")
    expected = validation.get("payload_preview_sha256")
    actual = canonical_json_sha256(payload)
    if not isinstance(expected, str) or expected != actual:
        raise ValueError(
            "daily payload blocked: final payload differs from pre-lock derivation"
        )
    return {
        "status": "passed",
        "payload_preview_sha256": actual,
        "report_preflight_manifest": validation.get("report_preflight_manifest"),
        "report_preflight_manifest_sha256": validation.get(
            "report_preflight_manifest_sha256"
        ),
    }
LOCKED_TIMEPOINT_REASON_MIN_CHARS = 20


def _source_age_evidence(source_specs: dict, *, now_ts: float) -> dict:
    """Return an audit-only age snapshot without changing freshness limits."""
    evidence = {}
    for label, raw_spec in source_specs.items():
        spec = {"path": raw_spec} if isinstance(raw_spec, str) else dict(raw_spec)
        path = Path(spec["path"]).resolve()
        if not path.is_file():
            raise ValueError(f"locked-timepoint source is missing: {label}")
        modified = path.stat().st_mtime
        evidence[label] = {
            "age_minutes": round(max(0.0, (now_ts - modified) / 60.0), 2),
            "max_age_minutes": float(spec.get("max_age_minutes", 240)),
            "same_local_day_required": bool(spec.get("same_local_day")),
            "same_local_day": (
                time.localtime(modified)[:3] == time.localtime(now_ts)[:3]
            ),
        }
    return evidence


def enforce_source_freshness(
    source_specs: dict,
    *,
    allow_locked_timepoint_publish: bool = False,
    locked_timepoint_reason: str | None = None,
    analysis_lock: dict | None = None,
    source_binding: dict | None = None,
    report_sha256: str | None = None,
) -> dict:
    """Enforce the normal freshness gate or record a narrow time-lock override.

    The override does not make stale evidence fresh. It only permits delivery of
    an explicitly requested historical time-slice when the formal report is
    already bound to an analysis lock and the immutable evidence snapshot.
    """
    reason = (locked_timepoint_reason or "").strip()
    if reason and not allow_locked_timepoint_publish:
        raise ValueError(
            "locked-timepoint reason requires --allow-locked-timepoint-publish"
        )
    if allow_locked_timepoint_publish:
        if len(reason) < LOCKED_TIMEPOINT_REASON_MIN_CHARS:
            raise ValueError(
                "locked-timepoint publish requires an explicit audit reason of at "
                f"least {LOCKED_TIMEPOINT_REASON_MIN_CHARS} characters"
            )
        if not isinstance(analysis_lock, dict):
            raise ValueError(
                "locked-timepoint publish requires a hash-bound analysis lock"
            )
        if analysis_lock.get("report_sha256") != report_sha256:
            raise ValueError(
                "locked-timepoint publish report hash does not match analysis lock"
            )
        if not isinstance(source_binding, dict):
            raise ValueError(
                "locked-timepoint publish requires immutable source binding"
            )
        if not source_binding.get("capture_manifest_sha256"):
            raise ValueError(
                "locked-timepoint publish requires capture manifest hash binding"
            )
        if not source_binding.get("evidence_snapshot_root"):
            raise ValueError(
                "locked-timepoint publish requires evidence snapshot binding"
            )

    now_ts = time.time()
    ages = _source_age_evidence(source_specs, now_ts=now_ts)
    try:
        assert_source_freshness(source_specs, now_ts=now_ts)
    except SystemExit as exc:
        if not allow_locked_timepoint_publish:
            raise
        result = {
            "policy": LOCKED_TIMEPOINT_POLICY,
            "status": "authorized_locked_timepoint",
            "freshness_passed": False,
            "override_used": True,
            "reason": reason,
            "original_failure": str(exc),
            "source_ages": ages,
            "analysis_lock_commit_id": analysis_lock.get("commit_id"),
            "report_sha256": report_sha256,
            "capture_manifest_sha256": source_binding.get(
                "capture_manifest_sha256"
            ),
            "evidence_snapshot_root": source_binding.get(
                "evidence_snapshot_root"
            ),
        }
        print(
            "SOURCE FRESHNESS OVERRIDDEN: user-authorized locked-timepoint "
            "delivery; immutable report and evidence bindings verified"
        )
        return result
    return {
        "policy": "normal_current_freshness_v1",
        "status": "passed",
        "freshness_passed": True,
        "override_used": False,
        "override_requested": allow_locked_timepoint_publish,
        "source_ages": ages,
    }


def _rich_text_plain(block: dict) -> str:
    block_type = block.get("type")
    body = block.get(block_type)
    if not isinstance(body, dict):
        return ""
    parts = []
    for item in body.get("rich_text", []):
        if not isinstance(item, dict):
            continue
        if item.get("plain_text") is not None:
            parts.append(str(item["plain_text"]))
            continue
        text = item.get("text")
        if isinstance(text, dict):
            parts.append(str(text.get("content", "")))
    return "".join(parts).strip()


def _report_plain(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _must_exist_in_report(payload_text: str, report_text: str) -> bool:
    return _report_plain(payload_text) in _report_plain(report_text)


def validate_daily_payload_shape(
    payload: dict,
    trading_date: str,
    report_slot: str,
    report_text: str | None = None,
) -> dict:
    """Hard-stop new daily payloads before Notion writes if they drift from gold shape."""
    if payload.get("verifier_mode") not in {"morning", "midday", "evening"}:
        return {"status": "skipped", "reason": "non-daily verifier mode"}
    if not strict_contract_active(trading_date):
        return {"status": "skipped", "reason": "historical report before strict shape gate"}
    children = payload.get("children")
    if not isinstance(children, list):
        raise ValueError("daily payload shape gate requires children array")
    expected_types = DAILY_PAYLOAD_TYPES_BY_SLOT[report_slot]
    actual_types = tuple(
        block.get("type") if isinstance(block, dict) else None
        for block in children
    )
    if actual_types != expected_types:
        raise ValueError(
            "daily Notion payload block type sequence does not match frozen gold shape: "
            f"expected={list(expected_types)}, actual={list(actual_types)}"
        )
    text_values = []
    for index, block in enumerate(children):
        block_type = block.get("type") if isinstance(block, dict) else None
        if block_type == "divider":
            continue
        text = _rich_text_plain(block)
        text_values.append((index, text))
        if not text:
            raise ValueError(f"daily Notion payload text block {index + 1} is empty")
        if "??" in text:
            raise ValueError(
                f"daily Notion payload text block {index + 1} looks encoding-corrupted: {text!r}"
            )
    if len(payload.get("image_paths", [])) != 3:
        raise ValueError("daily Notion payload must publish exactly 3 fundamental images")
    if payload.get("image_after_heading") != "基本面":
        raise ValueError("daily Notion payload must insert images after 基本面")
    expected_display_date = display_date(trading_date)
    if expected_display_date not in str(payload.get("title", "")):
        raise ValueError("daily Notion payload title must use display date YYYY.M.D")
    if trading_date in str(payload.get("title", "")):
        raise ValueError("daily Notion payload title must not use ISO date")
    expected_slot = {
        "morning": "早间日报",
        "midday": "午间日报",
        "evening": "晚间日报",
    }[report_slot]
    if expected_slot not in str(payload.get("title", "")):
        raise ValueError(f"daily Notion payload title must contain {expected_slot}")
    for index, expected_prefix in DAILY_PAYLOAD_TEXT_PREFIXES.items():
        text = _rich_text_plain(children[index])
        if not text.startswith(expected_prefix):
            raise ValueError(
                "daily Notion payload text slot drift: "
                f"block {index + 1} expected prefix {expected_prefix!r}, got {text!r}"
            )
    final_text = _rich_text_plain(children[-1])
    if not final_text.startswith(FINAL_TEXT_PREFIXES):
        raise ValueError(
            "daily Notion payload final boundary block drift: "
            f"expected one of {FINAL_TEXT_PREFIXES!r}, got {final_text!r}"
        )
    if report_text is not None:
        for index, text in text_values:
            if text.startswith(CRITICAL_REPORT_TEXT_PREFIXES) and not _must_exist_in_report(
                text, report_text
            ):
                raise ValueError(
                    "daily Notion payload critical text is not present in combined report: "
                    f"block {index + 1} text={text!r}"
                )
    return {
        "status": "passed",
        "gold_shape": (
            "2026-06-02 daily frozen shape excluding inserted images "
            f"({len(expected_types)} text blocks for {report_slot})"
        ),
        "block_count_before_images": len(children),
        "image_count": len(payload["image_paths"]),
    }


def _publish_manifest_has_quality_evidence(manifest: dict, trading_date: str) -> bool:
    if not strict_contract_active(trading_date):
        return True
    shape = manifest.get("notion_payload_shape")
    colors = manifest.get("notion_payload_colors")
    source = manifest.get("notion_payload_source")
    verifier = manifest.get("frozen_verifier")
    if manifest.get("verifier_mode") == "review":
        return bool(
            isinstance(shape, dict)
            and shape.get("status") == "passed"
            and shape.get("template") == REVIEW_CONTRACT_VERSION
            and shape.get("block_count_before_images") == 15
            and shape.get("image_count") == 0
            and isinstance(colors, dict)
            and colors.get("status") == "passed"
            and colors.get("template") == REVIEW_FONT_TEMPLATE
            and isinstance(source, dict)
            and source.get("status") == "passed"
            and source.get("kind") == REVIEW_SOURCE_KIND
            and source.get("template") == REVIEW_CONTRACT_VERSION
            and isinstance(verifier, dict)
            and verifier.get("returncode") == 0
            and "[PASS]" in str(verifier.get("stdout", ""))
        )
    expected_count = {
        "morning": 25,
        "midday": 25,
        "evening": 26,
    }.get(str(manifest.get("slot", "")))
    return bool(
        isinstance(shape, dict)
        and shape.get("status") == "passed"
        and expected_count is not None
        and shape.get("block_count_before_images") == expected_count
        and shape.get("image_count") == 3
        and isinstance(colors, dict)
        and colors.get("status") == "passed"
        and colors.get("template") == "daily-gold-run-colors-v1"
        and isinstance(source, dict)
        and source.get("status") == "passed"
        and source.get("kind") == "combined_md_to_notion_payload"
        and isinstance(verifier, dict)
        and verifier.get("returncode") == 0
        and "[PASS]" in str(verifier.get("stdout", ""))
    )


def _attempt_manifest_path(
    trading_date: str,
    mode: str,
    status: str,
    payload_hash: str,
) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
    return (
        ROOT
        / "runtime_state"
        / trading_date
        / "publish_attempts"
        / mode
        / f"{stamp}_{status}_{payload_hash[:12]}.json"
    )


def _validate_publish_inputs(
    report: Path,
    image_paths: list[str],
    image_after_heading: object,
) -> None:
    if not report.is_file():
        raise ValueError(f"report_path is missing: {report}")
    if not isinstance(image_paths, list):
        raise ValueError("image_paths must be an array")
    if image_paths and not (
        isinstance(image_after_heading, str) and image_after_heading.strip()
    ):
        raise ValueError("image_after_heading is required when image_paths is not empty")
    missing_images = [path for path in image_paths if not Path(path).is_file()]
    if missing_images:
        raise ValueError(
            "publish image files are missing: "
            + ", ".join(str(path) for path in missing_images)
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def validate_publish_source_binding(
    trading_date: str,
    slot: str,
    source_specs: dict,
    *,
    root: Path = ROOT,
) -> dict:
    """Require publish freshness inputs to come from the locked evidence snapshot."""
    root = Path(root).resolve()
    state_dir = root / "runtime_state" / trading_date
    transition_path = state_dir / f"transition_{slot}.json"
    transition = _load_object(transition_path)
    if transition.get("trading_date") != trading_date or transition.get("slot") != slot:
        raise ValueError("publish source binding transition mismatch")

    capture = transition.get("capture_manifest")
    if not isinstance(capture, dict):
        raise ValueError("transition is missing capture_manifest")
    capture_rel = capture.get("path")
    if not isinstance(capture_rel, str) or not capture_rel:
        raise ValueError("transition capture manifest path is missing")
    capture_path = (state_dir / capture_rel).resolve()
    if capture.get("sha256") != sha256_file(capture_path):
        raise ValueError("capture manifest hash mismatch before publish")

    snapshot = capture.get("evidence_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("transition capture manifest is missing evidence_snapshot")
    snapshot_root_value = snapshot.get("root")
    if not isinstance(snapshot_root_value, str) or not snapshot_root_value:
        raise ValueError("evidence snapshot root is missing")
    snapshot_root = (state_dir / snapshot_root_value).resolve()
    allowed_root = (state_dir / "evidence" / slot).resolve()
    try:
        snapshot_root.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("publish evidence snapshot escapes slot evidence directory") from exc
    if not snapshot_root.is_dir():
        raise ValueError(f"publish evidence snapshot directory is missing: {snapshot_root}")

    entries = snapshot.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("evidence snapshot has no files")
    files_by_path: dict[Path, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("evidence snapshot file entry must be an object")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError(f"invalid evidence snapshot path: {relative!r}")
        file_path = (snapshot_root / relative).resolve()
        try:
            file_path.relative_to(snapshot_root)
        except ValueError as exc:
            raise ValueError(f"evidence file escapes snapshot: {relative}") from exc
        if not file_path.is_file():
            raise ValueError(f"evidence file is missing before publish: {relative}")
        if expected_hash != sha256_file(file_path):
            raise ValueError(f"evidence file hash mismatch before publish: {relative}")
        files_by_path[file_path] = entry

    bindings = {}
    for label in sorted(REQUIRED_SOURCE_LABELS):
        raw_spec = source_specs[label]
        spec = {"path": raw_spec} if isinstance(raw_spec, str) else dict(raw_spec)
        source_path = Path(spec["path"])
        source_path = (
            source_path.resolve()
            if source_path.is_absolute()
            else (root / source_path).resolve()
        )
        if source_path.name not in SOURCE_LABEL_FILES[label]:
            raise ValueError(
                f"{label} publish source points to wrong artifact: {source_path.name}"
            )
        try:
            source_path.relative_to(snapshot_root)
        except ValueError as exc:
            raise ValueError(
                f"{label} publish source is not from locked evidence snapshot"
            ) from exc
        entry = files_by_path.get(source_path)
        if not entry:
            raise ValueError(f"{label} publish source is absent from evidence snapshot")
        bindings[label] = {
            "path": _relative(source_path, root),
            "sha256": entry["sha256"],
            "snapshot_file": entry["path"],
        }

    return {
        "transition_path": _relative(transition_path, root),
        "transition_sha256": sha256_file(transition_path),
        "capture_manifest_path": _relative(capture_path, root),
        "capture_manifest_sha256": capture["sha256"],
        "evidence_snapshot_root": _relative(snapshot_root, root),
        "sources": bindings,
    }


def publish(
    payload_path: Path,
    *,
    dry_run: bool = False,
    force_republish: bool = False,
    allow_locked_timepoint_publish: bool = False,
    locked_timepoint_reason: str | None = None,
) -> dict:
    started = time.perf_counter()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    mode = payload.get("verifier_mode")
    required_fields = DAILY_REQUIRED if mode in {"morning", "midday", "evening"} else REQUIRED
    missing = sorted(required_fields - set(payload))
    if missing:
        raise ValueError(f"publish payload missing fields: {missing}")
    if mode not in {"morning", "midday", "evening", "review"}:
        raise ValueError("unsupported verifier_mode")
    if mode == "review" and (
        allow_locked_timepoint_publish or locked_timepoint_reason
    ):
        raise ValueError("locked-timepoint publish is available only for daily reports")
    if not isinstance(payload["children"], list):
        raise ValueError("children must be an array of Notion blocks")
    if not isinstance(payload["image_paths"], list):
        raise ValueError("image_paths must be an array")
    if mode != "review":
        if not isinstance(payload["source_specs"], dict):
            raise ValueError("source_specs must be an object")
        missing_sources = sorted(REQUIRED_SOURCE_LABELS - set(payload["source_specs"]))
        if missing_sources:
            raise ValueError(
                "publish payload missing required source specs: "
                + ", ".join(missing_sources)
            )

    def resolve(path: str) -> str:
        candidate = Path(path)
        return str(candidate if candidate.is_absolute() else (ROOT / candidate).resolve())

    source_specs = {}
    if mode != "review":
        for label, raw in payload["source_specs"].items():
            spec = {"path": raw} if isinstance(raw, str) else dict(raw)
            spec["path"] = resolve(spec["path"])
            source_specs[label] = spec

    report_path = resolve(payload["report_path"])
    image_paths = [resolve(path) for path in payload["image_paths"]]
    report = Path(report_path)
    _validate_publish_inputs(report, image_paths, payload["image_after_heading"])
    report_match = re.match(
        r"^(20\d{2}-\d{2}-\d{2})_(morning|midday|evening)_",
        report.name,
    )
    if not report_match:
        raise ValueError("report_path must use canonical date/slot naming")
    trading_date, report_slot = report_match.groups()
    if mode == "review" and trading_date >= "2026-07-09":
        raise RuntimeError(
            "evening independent review publishing retired on 2026-07-09; "
            "use the external Trading accuracy evaluator"
        )
    if mode != "review" and mode != report_slot:
        raise ValueError("verifier_mode does not match report filename slot")
    if mode == "review" and report_slot != "evening":
        raise ValueError("review verifier_mode must reference the evening report")
    telemetry_slot = report_slot
    analysis_lock = None
    if mode != "review":
        report_lines = report.read_text(encoding="utf-8").splitlines()
        assert_combined_structure(report_lines, trading_date, report_slot)
        analysis_lock = validate_locked_report_for_output(
            trading_date,
            report_slot,
            report,
            root=ROOT,
        )
    expected_display_date = display_date(trading_date)
    if expected_display_date not in payload["title"] or trading_date in payload["title"]:
        raise ValueError(
            "publish title must use human display date "
            f"{expected_display_date}, not ISO date {trading_date}"
        )
    if mode == "review":
        payload_source = validate_review_payload_source(
            payload,
            report,
            trading_date,
            report_slot,
            root=ROOT,
        )
        payload_shape = validate_review_payload_shape(payload, trading_date)
        payload_colors = validate_review_payload_colors(payload)
        payload_preflight = {"status": "not_applicable"}
    else:
        report_text = report.read_text(encoding="utf-8")
        payload_source = validate_payload_derivation(
            payload,
            report,
            trading_date,
            report_slot,
            root=ROOT,
        )
        payload_preflight = validate_payload_preflight_binding(
            payload,
            analysis_lock,
            trading_date,
        )
        payload_shape = validate_daily_payload_shape(
            payload,
            trading_date,
            report_slot,
            report_text=report_text,
        )
        payload_colors = (
            style_daily_payload_children(payload["children"])
            if payload_shape.get("status") == "passed"
            else {"status": "skipped", "reason": payload_shape.get("reason")}
        )
    payload_hash = sha256_file(payload_path)
    report_hash = sha256_file(report)
    if mode == "review":
        source_binding = {
            "status": "not_applicable",
            "reason": "independent_review_uses_review_manifest_binding",
            "review_manifest": payload_source.get("review_manifest"),
            "review_manifest_sha256": payload_source.get("review_manifest_sha256"),
        }
    else:
        source_binding = validate_publish_source_binding(
            trading_date,
            report_slot,
            source_specs,
            root=ROOT,
        )
    manifest_path = (
        ROOT / "runtime_state" / trading_date / f"publish_{mode}.json"
    )
    existing = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else None
    )
    if (
        not dry_run
        and not force_republish
        and isinstance(existing, dict)
        and existing.get("status") == "success"
        and existing.get("payload_sha256") == payload_hash
        and existing.get("report_sha256") == report_hash
        and existing.get("source_binding") == source_binding
        and _publish_manifest_has_quality_evidence(existing, trading_date)
    ):
        append_usage(
            trading_date=trading_date,
            slot=telemetry_slot,
            phase="publish",
            status="success",
            event_id=f"{report_hash}:publish:{mode}:cache",
            details={
                "cache_hit": True,
                "attempt": 1,
                "backend": "notion_rest",
                "input_sha256": payload_hash,
                "report_sha256": report_hash,
                "page_id": existing["page_id"],
            },
            root=ROOT,
        )
        result = dict(existing)
        result["cache_hit"] = True
        return result
    summary = {
        "date": payload["date"],
        "title": payload["title"],
        "title_prefix": payload["title_prefix"],
        "verifier_mode": payload["verifier_mode"],
        "report_path": report_path,
        "image_paths": image_paths,
        "block_count": len(payload["children"]),
        "dry_run": dry_run,
        "notion_payload_source": payload_source,
        "notion_payload_shape": payload_shape,
        "notion_payload_colors": payload_colors,
        "payload_preflight": payload_preflight,
        "source_binding": source_binding,
    }
    source_freshness = {
        "policy": LOCKED_TIMEPOINT_POLICY,
        "status": "not_evaluated",
        "override_requested": allow_locked_timepoint_publish,
    }

    try:
        if mode != "review":
            source_freshness = enforce_source_freshness(
                source_specs,
                allow_locked_timepoint_publish=allow_locked_timepoint_publish,
                locked_timepoint_reason=locked_timepoint_reason,
                analysis_lock=analysis_lock,
                source_binding=source_binding,
                report_sha256=report_hash,
            )
            summary["source_freshness"] = source_freshness
            run_report_lint(report_path)
        if dry_run:
            return summary

        parent_id = ensure_date_page(payload["date"])
        publish_result = replace_page_transactional(
            parent_id=parent_id,
            title=payload["title"],
            title_prefix=payload["title_prefix"],
            children=payload["children"],
            image_after_heading=payload["image_after_heading"],
            image_paths=image_paths,
            verifier_mode=payload["verifier_mode"],
            daily_payload_source=payload_source,
        )
        if not isinstance(publish_result, tuple) or len(publish_result) not in (2, 3):
            raise ValueError("replace_page_transactional returned an invalid result")
        if len(publish_result) == 3:
            page_id, archived_pages, frozen_verifier_evidence = publish_result
        else:
            page_id, archived_pages = publish_result
            frozen_verifier_evidence = None
        published_at = datetime.now().astimezone().isoformat(timespec="seconds")
        evidence = {
            "schema_version": "1.0",
            "status": "success",
            "completed_at": published_at,
            "published_at": published_at,
            "trading_date": trading_date,
            "slot": telemetry_slot,
            "verifier_mode": mode,
            "payload_path": str(payload_path),
            "payload_sha256": payload_hash,
            "report_path": report_path,
            "report_sha256": report_hash,
            "source_binding": source_binding,
            "source_freshness": source_freshness,
            "page_id": page_id,
            "frozen_verifier_pass": True,
            "frozen_verifier": frozen_verifier_evidence,
            "notion_payload_source": payload_source,
            "notion_payload_shape": payload_shape,
            "notion_payload_colors": payload_colors,
            "payload_preflight": payload_preflight,
            "unique_page_pass": True,
            "archived_pages": archived_pages,
        }
        attempt_path = _attempt_manifest_path(
            trading_date, mode, "success", payload_hash
        )
        evidence["attempt_manifest_path"] = str(attempt_path)
        atomic_json_write(manifest_path, evidence)
        atomic_json_write(attempt_path, evidence)
        append_usage(
            trading_date=trading_date,
            slot=telemetry_slot,
            phase="publish",
            status="success",
            event_id=f"{report_hash}:publish:{mode}:{page_id}",
            duration_ms=round((time.perf_counter() - started) * 1000),
            details={
                "cache_hit": False,
                "attempt": 1,
                "backend": "notion_rest",
                "input_sha256": payload_hash,
                "report_sha256": report_hash,
                "page_id": page_id,
                "frozen_verifier_pass": True,
                "unique_page_pass": True,
                "locked_timepoint_override_used": source_freshness.get(
                    "override_used", False
                ),
            },
            root=ROOT,
        )
        summary.update(evidence)
        return summary
    except BaseException as exc:
        if dry_run:
            raise
        failure = {
            "schema_version": "1.0",
            "status": "failed",
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": trading_date,
            "slot": telemetry_slot,
            "verifier_mode": mode,
            "payload_path": str(payload_path),
            "payload_sha256": payload_hash,
            "report_path": report_path,
            "report_sha256": report_hash,
            "source_binding": source_binding,
            "source_freshness": source_freshness,
            "notion_payload_source": payload_source,
            "failure_class": type(exc).__name__,
            "failure_reason": str(exc),
        }
        attempt_path = _attempt_manifest_path(
            trading_date, mode, "failed", payload_hash
        )
        failure["attempt_manifest_path"] = str(attempt_path)
        atomic_json_write(manifest_path, failure)
        atomic_json_write(attempt_path, failure)
        append_usage(
            trading_date=trading_date,
            slot=telemetry_slot,
            phase="publish",
            status="failed",
            event_id=f"{report_hash}:publish:{mode}:failed",
            duration_ms=round((time.perf_counter() - started) * 1000),
            details={
                "cache_hit": False,
                "attempt": 1,
                "backend": "notion_rest",
                "input_sha256": payload_hash,
                "report_sha256": report_hash,
                "failure_reason": str(exc),
                "locked_timepoint_override_requested": (
                    allow_locked_timepoint_publish
                ),
            },
            root=ROOT,
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a parameterized report payload")
    parser.add_argument("payload", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-republish", action="store_true")
    parser.add_argument(
        "--allow-locked-timepoint-publish",
        action="store_true",
        help=(
            "permit an explicitly requested locked historical time-slice only "
            "after analysis-lock and immutable-source validation"
        ),
    )
    parser.add_argument(
        "--locked-timepoint-reason",
        help="audited user-authorization reason for locked-timepoint delivery",
    )
    args = parser.parse_args()
    result = publish(
        args.payload.resolve(),
        dry_run=args.dry_run,
        force_republish=args.force_republish,
        allow_locked_timepoint_publish=args.allow_locked_timepoint_publish,
        locked_timepoint_reason=args.locked_timepoint_reason,
    )
    # Windows PowerShell may expose a GBK stdout that cannot encode title emoji.
    # ASCII-safe JSON preserves the exact Unicode content without console crashes.
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
