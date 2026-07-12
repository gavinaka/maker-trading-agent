"""Retention cleanup for daily-report generated artifacts.

The CLI default mode is audit-only.  Pass --execute to remove candidates.
The long-lived local report artifact is the canonical Word draft; Notion is
the published draft.  Reproducible/heavy local artifacts are removed after the
configured retention window.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEEP_DAYS = 2
NON_DAILY_RUNTIME_DIRS = ("quality_audit",)
SLOT_PATTERN = r"(morning|midday|evening)"
ISO_DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
TRANSIENT_OUTPUT = re.compile(
    rf"^(20\d{{2}}-\d{{2}}-\d{{2}})_{SLOT_PATTERN}_(?:cards|publish_payload)\.json$"
)
NON_WORD_REPORT_OUTPUT = re.compile(
    rf"^(20\d{{2}}-\d{{2}}-\d{{2}})(?:_{SLOT_PATTERN}_combined\.md|_.+\.html)$"
)


@dataclass(frozen=True)
class RetentionAction:
    kind: str
    path: str
    bytes: int
    reason: str


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value!r}") from exc


def cutoff_date(today: date, keep_days: int) -> date:
    if keep_days < 1:
        raise ValueError("keep_days must be >= 1")
    return today - timedelta(days=keep_days - 1)


def configured_keep_days() -> int:
    return int(os.environ.get("REPORT_RETENTION_KEEP_DAYS", DEFAULT_KEEP_DAYS))


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def latest_modified_date(path: Path) -> date:
    timestamps = [path.stat().st_mtime]
    if path.is_dir():
        timestamps.extend(
            child.stat().st_mtime for child in path.rglob("*") if child.is_file()
        )
    return datetime.fromtimestamp(max(timestamps)).date()


def relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def ensure_under_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"refusing to touch path outside repository: {resolved}") from exc
    return resolved


def older_than_cutoff(date_text: str, cutoff: date) -> bool:
    return ISO_DATE.fullmatch(date_text) is not None and parse_iso_date(date_text) < cutoff


def action(kind: str, path: Path, root: Path, reason: str) -> RetentionAction:
    ensure_under_root(path, root)
    return RetentionAction(
        kind=kind,
        path=relative(path, root),
        bytes=path_size(path),
        reason=reason,
    )


def collect_actions(
    *,
    root: Path = ROOT,
    today: date | None = None,
    keep_days: int = DEFAULT_KEEP_DAYS,
    include_temp_scripts: bool = True,
) -> list[RetentionAction]:
    root = root.resolve()
    today = today or date.today()
    cutoff = cutoff_date(today, keep_days)
    actions: list[RetentionAction] = []

    inbox = root / "data_sources" / "inbox"
    if inbox.is_dir():
        for child in sorted(inbox.iterdir()):
            if child.is_dir() and older_than_cutoff(child.name, cutoff):
                actions.append(
                    action(
                        "inbox_dir",
                        child,
                        root,
                        f"source inbox date is before cutoff {cutoff.isoformat()}",
                    )
                )

    blockbeats = root / "outputs" / "blockbeats"
    if blockbeats.is_dir():
        for child in sorted(blockbeats.iterdir()):
            match = re.match(r"^(20\d{2}-\d{2}-\d{2})_", child.name)
            if child.is_file() and match and older_than_cutoff(match.group(1), cutoff):
                actions.append(
                    action(
                        "blockbeats_card",
                        child,
                        root,
                        f"BlockBeats card date is before cutoff {cutoff.isoformat()}",
                    )
                )

    outputs = root / "outputs"
    if outputs.is_dir():
        for child in sorted(outputs.iterdir()):
            if not child.is_file():
                continue
            match = TRANSIENT_OUTPUT.match(child.name)
            if match and older_than_cutoff(match.group(1), cutoff):
                actions.append(
                    action(
                        "output_transient",
                        child,
                        root,
                        f"daily payload/card JSON date is before cutoff {cutoff.isoformat()}",
                        )
                    )
            else:
                match = NON_WORD_REPORT_OUTPUT.match(child.name)
                if match and older_than_cutoff(match.group(1), cutoff):
                    actions.append(
                        action(
                            "output_non_word_report",
                            child,
                            root,
                            f"non-Word local report artifact date is before cutoff {cutoff.isoformat()}",
                        )
                    )
                    continue
            if include_temp_scripts and child.name.startswith("_") and child.suffix == ".py":
                modified = datetime.fromtimestamp(child.stat().st_mtime).date()
                if modified < cutoff:
                    actions.append(
                        action(
                            "output_temp_script",
                            child,
                            root,
                            f"one-time output script mtime is before cutoff {cutoff.isoformat()}",
                        )
                    )

    runtime_state = root / "runtime_state"
    if runtime_state.is_dir():
        for date_dir in sorted(runtime_state.iterdir()):
            if not date_dir.is_dir() or not older_than_cutoff(date_dir.name, cutoff):
                continue
            for candidate in sorted(path for path in date_dir.iterdir() if path.is_dir()):
                actions.append(
                    action(
                        "runtime_state_heavy",
                        candidate,
                        root,
                        f"runtime subdirectory date is before cutoff {cutoff.isoformat()}",
                    )
                )

        for name in NON_DAILY_RUNTIME_DIRS:
            candidate = runtime_state / name
            if candidate.is_dir() and latest_modified_date(candidate) < cutoff:
                actions.append(
                    action(
                        "runtime_state_nondaily_transient",
                        candidate,
                        root,
                        f"non-daily runtime artifact is older than cutoff {cutoff.isoformat()}",
                    )
                )

    return actions


def remove_path(path: Path, root: Path) -> None:
    target = ensure_under_root(path, root)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def execute_actions(actions: list[RetentionAction], *, root: Path = ROOT) -> None:
    for item in actions:
        remove_path(root / item.path, root)


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def retention_payload(
    *,
    root: Path,
    today: date,
    keep_days: int,
    execute: bool,
    actions: list[RetentionAction],
    reason: str,
) -> dict:
    return {
        "schema_version": "1.0",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "execute" if execute else "dry-run",
        "root": str(root),
        "today": today.isoformat(),
        "keep_days": keep_days,
        "cutoff": cutoff_date(today, keep_days).isoformat(),
        "count": len(actions),
        "bytes": sum(item.bytes for item in actions),
        "reason": reason,
        "actions": [asdict(item) for item in actions],
    }


def run_retention_cleanup(
    *,
    root: Path = ROOT,
    today: date | None = None,
    keep_days: int = DEFAULT_KEEP_DAYS,
    include_temp_scripts: bool = True,
    execute: bool = False,
    manifest_path: Path | None = None,
    reason: str = "manual",
) -> dict:
    root = root.resolve()
    today = today or date.today()
    actions = collect_actions(
        root=root,
        today=today,
        keep_days=keep_days,
        include_temp_scripts=include_temp_scripts,
    )
    payload = retention_payload(
        root=root,
        today=today,
        keep_days=keep_days,
        execute=execute,
        actions=actions,
        reason=reason,
    )
    if execute:
        execute_actions(actions, root=root)
    if manifest_path is not None:
        write_json_atomic(manifest_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean old daily-report artifacts")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--keep-days",
        type=int,
        default=configured_keep_days(),
    )
    parser.add_argument("--today", type=parse_iso_date)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--no-temp-scripts", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    payload = run_retention_cleanup(
        root=root,
        today=args.today or date.today(),
        keep_days=args.keep_days,
        include_temp_scripts=not args.no_temp_scripts,
        execute=args.execute,
        manifest_path=args.manifest,
        reason="manual_cli",
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "[report-retention] "
            f"{payload['mode']} cutoff={payload['cutoff']} "
            f"count={payload['count']} bytes={payload['bytes']}"
        )
        for item in payload["actions"]:
            print(
                f"- {item['kind']}: {item['path']} ({item['bytes']} bytes) "
                f"[{item['reason']}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
