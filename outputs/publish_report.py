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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    assert_source_freshness(source_specs)
    run_report_lint(report_path)

    summary = {
        "date": payload["date"],
        "title": payload["title"],
        "title_prefix": payload["title_prefix"],
        "verifier_mode": payload["verifier_mode"],
        "report_path": report_path,
        "image_paths": image_paths,
        "block_count": len(payload["children"]),
        "dry_run": dry_run,
    }
    if dry_run:
        return summary

    try:
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
            "page_id": page_id,
            "frozen_verifier_pass": True,
            "unique_page_pass": True,
            "archived_pages": archived_pages,
        }
        atomic_json_write(manifest_path, evidence)
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
            "failure_reason": str(exc),
        }
        atomic_json_write(manifest_path, failure)
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
