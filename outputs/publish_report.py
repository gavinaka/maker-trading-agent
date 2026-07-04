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
from runtime.state_store import atomic_json_write
from runtime.usage_logger import append_usage


REQUIRED = {
    "date",
    "title",
    "title_prefix",
    "verifier_mode",
    "report_path",
    "source_specs",
    "children",
    "image_after_heading",
    "image_paths",
}
REQUIRED_SOURCE_LABELS = {
    "blockbeats",
    "coinglass",
    "exocharts",
    "fedwatch",
    "tradingview_1d",
    "tradingview_4h",
    "tradingview_1h",
    "tradingview_15m",
}
SOURCE_LABEL_FILES = {
    "blockbeats": {"blockbeats.png", "blockbeats.json"},
    "coinglass": {"coinglass.png"},
    "exocharts": {"exocharts.png"},
    "fedwatch": {"fedwatch.png", "fedwatch.json"},
    "tradingview_1d": {"tradingview_btc_1d.png"},
    "tradingview_4h": {"tradingview_btc_4h.png"},
    "tradingview_1h": {"tradingview_btc_1h.png"},
    "tradingview_15m": {"tradingview_btc_15m.png"},
}


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
) -> dict:
    started = time.perf_counter()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED - set(payload))
    if missing:
        raise ValueError(f"publish payload missing fields: {missing}")
    if payload["verifier_mode"] not in {"morning", "midday", "evening", "review"}:
        raise ValueError("unsupported verifier_mode")
    if not isinstance(payload["children"], list):
        raise ValueError("children must be an array of Notion blocks")
    if not isinstance(payload["source_specs"], dict):
        raise ValueError("source_specs must be an object")
    if not isinstance(payload["image_paths"], list):
        raise ValueError("image_paths must be an array")
    missing_sources = sorted(REQUIRED_SOURCE_LABELS - set(payload["source_specs"]))
    if missing_sources:
        raise ValueError(
            "publish payload missing required source specs: " + ", ".join(missing_sources)
        )

    def resolve(path: str) -> str:
        candidate = Path(path)
        return str(candidate if candidate.is_absolute() else (ROOT / candidate).resolve())

    source_specs = {}
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
    mode = payload["verifier_mode"]
    if mode != "review" and mode != report_slot:
        raise ValueError("verifier_mode does not match report filename slot")
    telemetry_slot = report_slot
    payload_hash = sha256_file(payload_path)
    report_hash = sha256_file(report)
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
        "source_binding": source_binding,
    }

    try:
        assert_source_freshness(source_specs)
        run_report_lint(report_path)
        if dry_run:
            return summary

        parent_id = ensure_date_page(payload["date"])
        page_id, archived_pages = replace_page_transactional(
            parent_id=parent_id,
            title=payload["title"],
            title_prefix=payload["title_prefix"],
            children=payload["children"],
            image_after_heading=payload["image_after_heading"],
            image_paths=image_paths,
            verifier_mode=payload["verifier_mode"],
        )
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
            "page_id": page_id,
            "frozen_verifier_pass": True,
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
            },
            root=ROOT,
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a parameterized report payload")
    parser.add_argument("payload", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-republish", action="store_true")
    args = parser.parse_args()
    result = publish(
        args.payload.resolve(),
        dry_run=args.dry_run,
        force_republish=args.force_republish,
    )
    # Windows PowerShell may expose a GBK stdout that cannot encode title emoji.
    # ASCII-safe JSON preserves the exact Unicode content without console crashes.
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
