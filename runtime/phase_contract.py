"""Materialize one hash-bound authority phase to reduce repeated tool reads."""

from __future__ import annotations

import argparse
import hashlib
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
MAX_TRANSPORT_PART_BYTES = 28 * 1024
MAX_TRANSPORT_OUTPUT_BYTES = 32 * 1024
BEGIN_BUNDLE_MARKER = "---BEGIN_AUTHORITY_BUNDLE---"
END_BUNDLE_MARKER = "---END_AUTHORITY_BUNDLE---"
BEGIN_PART_MARKER = "---BEGIN_AUTHORITY_BUNDLE_PART {index}/{count}---"
END_PART_MARKER = "---END_AUTHORITY_BUNDLE_PART {index}/{count}---"


def render_phase_contract(
    trading_date: str,
    slot: str,
    phase: str,
    *,
    root: Path = ROOT,
) -> tuple[dict, str]:
    """Render one complete phase without writing it.

    The source and rendered bundle limits bound one logical authority phase.
    Transport to the desktop host is separately split into hash-bound parts;
    silently truncating either the logical bundle or a transport part is
    forbidden.
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
    """Return a header and, only when host-safe, one legacy full bundle.

    Large bundles must use ``format_phase_part_output``.  Keeping this bounded
    legacy path prevents an older automation from silently reproducing the
    host truncation failure.
    """
    header = json.dumps(payload, ensure_ascii=False)
    if not emit_bundle:
        return header
    output = "\n".join((header, BEGIN_BUNDLE_MARKER, rendered, END_BUNDLE_MARKER))
    output_bytes = len(output.encode("utf-8"))
    if output_bytes > MAX_TRANSPORT_OUTPUT_BYTES:
        raise ValueError(
            "full authority output exceeds the host-safe transport envelope: "
            f"{output_bytes}>{MAX_TRANSPORT_OUTPUT_BYTES}; use --emit-part"
        )
    return output


def split_phase_transport(
    rendered: str,
    *,
    max_part_bytes: int = MAX_TRANSPORT_PART_BYTES,
) -> list[str]:
    """Split UTF-8 text losslessly without breaking a code point."""
    if max_part_bytes <= 0:
        raise ValueError("max_part_bytes must be positive")
    remaining = rendered.encode("utf-8")
    if not remaining:
        return [""]
    parts: list[str] = []
    while remaining:
        cut = min(max_part_bytes, len(remaining))
        if cut < len(remaining):
            newline = remaining.rfind(b"\n", 0, cut)
            if newline >= 0:
                cut = newline + 1
        while True:
            try:
                part = remaining[:cut].decode("utf-8")
                break
            except UnicodeDecodeError as error:
                cut = error.start
                if cut <= 0:
                    raise ValueError("transport limit cannot hold one UTF-8 code point") from error
        parts.append(part)
        remaining = remaining[cut:]
    return parts


def format_phase_part_output(
    payload: dict,
    rendered: str,
    *,
    part_index: int,
) -> str:
    """Return one bounded, hash-bound, one-based transport part."""
    parts = split_phase_transport(rendered)
    part_count = len(parts)
    if part_index < 1 or part_index > part_count:
        raise ValueError(f"part_index must be between 1 and {part_count}: {part_index}")
    part = parts[part_index - 1]
    bundle_sha256 = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    part_sha256 = hashlib.sha256(part.encode("utf-8")).hexdigest()
    transport_payload = {
        **payload,
        "transport_schema_version": "authority-phase-transport-v1",
        "bundle_sha256": bundle_sha256,
        "part_index": part_index,
        "part_count": part_count,
        "part_bytes": len(part.encode("utf-8")),
        "part_sha256": part_sha256,
        "max_part_bytes": MAX_TRANSPORT_PART_BYTES,
        "max_output_bytes": MAX_TRANSPORT_OUTPUT_BYTES,
    }
    header = json.dumps(transport_payload, ensure_ascii=False)
    begin = BEGIN_PART_MARKER.format(index=part_index, count=part_count)
    end = END_PART_MARKER.format(index=part_index, count=part_count)
    separator = "" if part.endswith("\n") else "\n"
    output = f"{header}\n{begin}\n{part}{separator}{end}"
    output_bytes = len(output.encode("utf-8"))
    if output_bytes > MAX_TRANSPORT_OUTPUT_BYTES:
        raise ValueError(
            "authority part exceeds the host-safe transport envelope: "
            f"{output_bytes}>{MAX_TRANSPORT_OUTPUT_BYTES}"
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--phase", required=True)
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--emit-bundle",
        action="store_true",
        help=(
            "emit the complete authority bundle only when it fits the bounded "
            "transport envelope; otherwise use --emit-part"
        ),
    )
    output_group.add_argument(
        "--emit-part",
        type=int,
        metavar="INDEX",
        help=(
            "emit one one-based hash-bound transport part; read part 1 first, "
            "then each remaining index exactly once"
        ),
    )
    args = parser.parse_args()
    payload, target = build_phase_contract(args.date, args.slot, args.phase)
    rendered = (
        target.read_text(encoding="utf-8")
        if args.emit_bundle or args.emit_part is not None
        else ""
    )
    if args.emit_part is not None:
        print(format_phase_part_output(payload, rendered, part_index=args.emit_part))
    else:
        print(format_phase_output(payload, rendered, emit_bundle=args.emit_bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
