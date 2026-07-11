"""Materialize one hash-bound authority phase to reduce repeated tool reads."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_pack import authority_manifest, authority_read_plan, authority_sha256


MAX_PHASE_SOURCE_BYTES = 58 * 1024
MAX_PHASE_BUNDLE_BYTES = 60 * 1024
BEGIN_BUNDLE_MARKER = "---BEGIN_AUTHORITY_BUNDLE---"
END_BUNDLE_MARKER = "---END_AUTHORITY_BUNDLE---"


def render_phase_contract(
    trading_date: str,
    slot: str,
    phase: str,
    *,
    root: Path = ROOT,
) -> tuple[dict, str]:
    """Render one complete phase without writing it.

    The source and rendered bundle limits are deliberately below the desktop
    host's single-output ceiling.  A phase that grows beyond the limit must be
    split by responsibility; silently truncating authority is forbidden.
    """
    root = Path(root).resolve()
    plan = authority_read_plan()
    if phase not in plan:
        raise ValueError(f"unknown authority phase: {phase}")
    manifest = authority_manifest(root)
    manifest_by_path = {item["path"]: item for item in manifest}
    selected = plan[phase]
    total = sum((root / relative).stat().st_size for relative in selected)
    if total > MAX_PHASE_SOURCE_BYTES:
        raise ValueError(
            f"authority phase exceeds {MAX_PHASE_SOURCE_BYTES} source bytes: "
            f"{phase}={total}; split the phase without removing authority"
        )
    lines = [
        f"# Authority phase: {phase}",
        "",
        f"- trading_date: {trading_date}",
        f"- slot: {slot}",
        f"- authority_sha256: {authority_sha256(manifest)}",
        f"- source_bytes: {total}",
        "- rule: this bundle is method authority, never prior-session judgment",
        "- completeness: every listed source is included in full; truncation is forbidden",
        "",
    ]
    for relative in selected:
        record = manifest_by_path[relative]
        lines.extend([
            f"## {relative}",
            f"sha256: `{record['sha256']}`",
            "",
            (root / relative).read_text(encoding="utf-8"),
            "",
        ])
    rendered = "\n".join(lines)
    bundle_bytes = len(rendered.encode("utf-8"))
    if bundle_bytes > MAX_PHASE_BUNDLE_BYTES:
        raise ValueError(
            f"authority phase exceeds {MAX_PHASE_BUNDLE_BYTES} rendered bytes: "
            f"{phase}={bundle_bytes}; split the phase without removing authority"
        )
    payload = {
        "schema_version": "authority-phase-contract-v2",
        "trading_date": trading_date,
        "slot": slot,
        "phase": phase,
        "source_bytes": total,
        "bundle_bytes": bundle_bytes,
        "source_files": selected,
        "authority_sha256": authority_sha256(manifest),
        "complete": True,
    }
    return payload, rendered


def build_phase_contract(trading_date: str, slot: str, phase: str, *, root: Path = ROOT) -> tuple[dict, Path]:
    root = Path(root).resolve()
    payload, rendered = render_phase_contract(
        trading_date,
        slot,
        phase,
        root=root,
    )
    target = root / "runtime_state" / trading_date / f"authority_phase_{slot}_{phase}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".md.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, target)
    payload["path"] = str(target)
    return payload, target


def format_phase_output(payload: dict, rendered: str, *, emit_bundle: bool) -> str:
    """Return one complete machine header and, when requested, the full bundle.

    The explicit end marker lets the host prove that a large tool result was not
    truncated.  Emitting the bundle changes only transport: source selection,
    hashes, byte limits, and content remain identical to the persisted file.
    """
    header = json.dumps(payload, ensure_ascii=False)
    if not emit_bundle:
        return header
    return "\n".join((header, BEGIN_BUNDLE_MARKER, rendered, END_BUNDLE_MARKER))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--emit-bundle",
        action="store_true",
        help=(
            "emit the complete authority bundle in this invocation; callers must "
            "verify the END marker and must not reread the persisted file"
        ),
    )
    args = parser.parse_args()
    payload, target = build_phase_contract(args.date, args.slot, args.phase)
    rendered = target.read_text(encoding="utf-8") if args.emit_bundle else ""
    print(format_phase_output(payload, rendered, emit_bundle=args.emit_bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
