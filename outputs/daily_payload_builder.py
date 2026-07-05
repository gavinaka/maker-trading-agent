# -*- coding: utf-8 -*-
"""Build and verify daily Notion payloads from the locked combined report.

The daily report has exactly one textual source of truth: the combined Markdown
report.  This module mechanically derives the Notion payload from that source so
the publish layer cannot become a second free-form writing surface.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from .daily_publish_contract import (
        DAILY_PAYLOAD_TYPES_BY_SLOT,
        FINAL_TEXT_PREFIXES,
        REQUIRED_SOURCE_LABELS,
        SLOT_TITLE_META,
        SOURCE_SPEC_FILENAMES,
        SOURCE_SPEC_POLICY,
    )
    from .report_structure_gate import (
        assert_combined_structure,
        display_date,
        strict_contract_active,
    )
except ImportError:  # pragma: no cover - script execution from outputs/
    from daily_publish_contract import (
        DAILY_PAYLOAD_TYPES_BY_SLOT,
        FINAL_TEXT_PREFIXES,
        REQUIRED_SOURCE_LABELS,
        SLOT_TITLE_META,
        SOURCE_SPEC_FILENAMES,
        SOURCE_SPEC_POLICY,
    )
    from report_structure_gate import (
        assert_combined_structure,
        display_date,
        strict_contract_active,
    )


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_NAME = "daily_payload_builder"
GENERATOR_VERSION = "1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _rt(text: str) -> dict:
    return {"type": "text", "text": {"content": text}}


def _block(block_type: str, text: str | None = None) -> dict:
    if block_type == "divider":
        return {"object": "block", "type": "divider", "divider": {}}
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": [_rt(str(text or ""))]},
    }


def block_plain_text(block: dict) -> str:
    block_type = block.get("type")
    if block_type == "divider":
        return "<divider>"
    body = block.get(block_type)
    if not isinstance(body, dict):
        return ""
    parts = []
    for item in body.get("rich_text", []):
        if not isinstance(item, dict):
            continue
        if item.get("plain_text") is not None:
            parts.append(str(item.get("plain_text", "")))
            continue
        text = item.get("text")
        if isinstance(text, dict):
            parts.append(str(text.get("content", "")))
    return "".join(parts).strip()


def children_signature(children: list[dict]) -> list[dict]:
    return [
        {
            "index": index,
            "type": block.get("type") if isinstance(block, dict) else None,
            "text": block_plain_text(block) if isinstance(block, dict) else "",
        }
        for index, block in enumerate(children, 1)
    ]


def _nonempty(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def _find_heading(lines: list[str], level: int, exact: str) -> int:
    prefix = "#" * level + " "
    for index, line in enumerate(lines):
        if line.startswith(prefix) and line[len(prefix) :].strip() == exact:
            return index
    raise ValueError(f"combined report missing heading: {'#' * level} {exact}")


def _find_h3(lines: list[str], exact: str) -> int:
    return _find_heading(lines, 3, exact)


def _section_after(lines: list[str], start: int, stop_levels: tuple[int, ...]) -> list[str]:
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].lstrip()
        for level in stop_levels:
            if stripped.startswith("#" * level + " "):
                end = index
                return lines[start + 1 : end]
    return lines[start + 1 : end]


def _first_blockquote(lines: list[str]) -> str:
    quotes = [line[1:].strip() for line in lines if line.startswith(">")]
    if not quotes:
        raise ValueError("combined report missing opening quote block")
    return " ".join(part for part in quotes if part).strip()


def _one_line_section(lines: list[str], heading: str, *, level: int = 3) -> str:
    start = _find_heading(lines, level, heading)
    values = _nonempty(_section_after(lines, start, (2, 3)))
    if len(values) != 1:
        raise ValueError(f"section {heading!r} must contain exactly one text line")
    return values[0]


def _strategy_line(lines: list[str]) -> str:
    start = _find_h3(lines, "策略")
    values = _nonempty(_section_after(lines, start, (2, 3)))
    if values and values[0] in {"策略：", "策略:"}:
        values = values[1:]
    if len(values) != 1:
        raise ValueError("section '策略' must contain exactly one executable text line")
    return values[0]


def _cannot_do_line(lines: list[str]) -> str:
    start = _find_heading(lines, 2, "不能做")
    values = _nonempty(_section_after(lines, start, (2, 3)))
    if len(values) != 1:
        raise ValueError("section '不能做' must contain exactly one text line")
    if not values[0].startswith("不能做：") or values[0] == "不能做：":
        raise ValueError("section '不能做' text must start with complete '不能做：'")
    return values[0]


def _technical_lines(lines: list[str]) -> tuple[str, str]:
    start = _find_h3(lines, "技术面")
    values = _nonempty(_section_after(lines, start, (2, 3)))
    if len(values) != 2:
        raise ValueError("section '技术面' must contain exactly 2 text lines")
    if not values[0].startswith("盘口"):
        raise ValueError("section '技术面' first line must be 盘口 label")
    return values[0], values[1]


def _interpretation_lines(lines: list[str]) -> tuple[str, str, str, str]:
    start = _find_h3(lines, "解读")
    values = _nonempty(_section_after(lines, start, (2, 3)))
    if len(values) != 4:
        raise ValueError("section '解读' must contain 解读/盘面/日线/小时 four lines")
    if not values[0].startswith("解读"):
        raise ValueError("section '解读' first line must start with 解读")
    if not values[1].startswith("盘面"):
        raise ValueError("section '解读' second line must be 盘面 label")
    if not values[2].startswith("日线级别"):
        raise ValueError("section '解读' third line must start with 日线级别")
    if not values[3].startswith("小时级别"):
        raise ValueError("section '解读' fourth line must start with 小时级别")
    return values[0], values[1], values[2], values[3]


def _maker_lines(lines: list[str], slot: str) -> tuple[list[str], list[str]]:
    maker_start = _find_heading(lines, 2, "② Maker 计划")
    maker_section = _section_after(lines, maker_start, (2,))
    defense_index = None
    for index, line in enumerate(maker_section):
        if line.startswith("### ") and line[4:].strip() == "防守计划":
            defense_index = index
            break
    if defense_index is None:
        raise ValueError("Maker section missing heading: ### 防守计划")

    before_defense = _nonempty(maker_section[:defense_index])
    after_defense = _nonempty(maker_section[defense_index + 1 :])
    if len(before_defense) != 4:
        raise ValueError("Maker section before 防守计划 must contain BTC/strategy/TP/SL")
    expected_tail = 6 if slot == "evening" else 5
    if len(after_defense) != expected_tail:
        raise ValueError(
            f"防守计划 must contain exactly {expected_tail} lines for {slot}, "
            f"got {len(after_defense)}"
        )
    required_prefixes = ("第一层：", "第二层：", "注意事项：")
    for value, prefix in zip(after_defense[:3], required_prefixes):
        if not value.startswith(prefix):
            raise ValueError(f"防守计划 line must start with {prefix}")
    if slot == "evening" and not after_defense[-2].startswith("核心："):
        raise ValueError("evening 防守计划 penultimate line must start with 核心：")
    if not after_defense[-1].startswith(FINAL_TEXT_PREFIXES):
        raise ValueError("防守计划 final line must start with 独立边界 or 持仓校准")
    return before_defense, after_defense


def daily_text_values_from_combined(lines: list[str], trading_date: str, slot: str) -> list[str]:
    assert_combined_structure(lines, trading_date, slot)
    orderflow_label, orderflow_text = _technical_lines(lines)
    interpretation, chart_label, daily_line, hourly_line = _interpretation_lines(lines)
    maker_main, defense = _maker_lines(lines, slot)
    values = [
        _first_blockquote(lines),
        _cannot_do_line(lines),
        _one_line_section(lines, "基本面"),
        "技术面",
        orderflow_label,
        orderflow_text,
        interpretation,
        chart_label,
        daily_line,
        hourly_line,
        _one_line_section(lines, "趋势确认"),
        _one_line_section(lines, "日内支撑/压力"),
        "策略",
        _strategy_line(lines),
        "<divider>",
        maker_main[0],
        maker_main[1],
        maker_main[2],
        maker_main[3],
        "防守计划",
        *defense,
    ]
    expected = len(DAILY_PAYLOAD_TYPES_BY_SLOT[slot])
    if len(values) != expected:
        raise ValueError(
            f"derived daily payload text count mismatch for {slot}: "
            f"expected={expected}, actual={len(values)}"
        )
    return values


def daily_children_from_combined(lines: list[str], trading_date: str, slot: str) -> list[dict]:
    values = daily_text_values_from_combined(lines, trading_date, slot)
    return [
        _block(block_type, None if block_type == "divider" else values[index])
        for index, block_type in enumerate(DAILY_PAYLOAD_TYPES_BY_SLOT[slot])
    ]


def _load_transition(trading_date: str, slot: str, root: Path) -> dict:
    path = root / "runtime_state" / trading_date / f"transition_{slot}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def source_specs_from_transition(trading_date: str, slot: str, *, root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    state_dir = root / "runtime_state" / trading_date
    transition = _load_transition(trading_date, slot, root)
    capture = transition.get("capture_manifest")
    if not isinstance(capture, dict):
        raise ValueError("transition is missing capture_manifest")
    snapshot = capture.get("evidence_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("transition capture manifest is missing evidence_snapshot")
    snapshot_root_value = snapshot.get("root")
    if not isinstance(snapshot_root_value, str) or not snapshot_root_value:
        raise ValueError("evidence snapshot root is missing")
    snapshot_root = (state_dir / snapshot_root_value).resolve()
    files = {entry.get("path") for entry in snapshot.get("files", []) if isinstance(entry, dict)}

    source_specs = {}
    for label in sorted(REQUIRED_SOURCE_LABELS):
        filename = SOURCE_SPEC_FILENAMES[label]
        if filename not in files:
            raise ValueError(f"evidence snapshot missing required source file: {filename}")
        spec = {"path": _relative(snapshot_root / filename, root)}
        spec.update(SOURCE_SPEC_POLICY[label])
        source_specs[label] = spec
    return source_specs


def blockbeat_card_paths(trading_date: str, slot: str, *, root: Path = ROOT) -> list[str]:
    card_dir = Path(root) / "outputs" / "blockbeats"
    paths = sorted(card_dir.glob(f"{trading_date}_{slot}_*.png"))
    if len(paths) != 3:
        raise ValueError(
            f"daily publish requires exactly 3 BlockBeats cards for {trading_date} {slot}; "
            f"found {len(paths)}"
        )
    return [_relative(path, Path(root)) for path in paths]


def build_daily_payload(report_path: Path, *, root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    report_path = Path(report_path)
    report = report_path if report_path.is_absolute() else root / report_path
    match = re.match(
        r"^(20\d{2}-\d{2}-\d{2})_(morning|midday|evening)_",
        report.name,
    )
    if not match:
        raise ValueError("combined report filename must start with YYYY-MM-DD_slot_")
    trading_date, slot = match.groups()
    lines = report.read_text(encoding="utf-8").splitlines()
    children = daily_children_from_combined(lines, trading_date, slot)
    source_specs = source_specs_from_transition(trading_date, slot, root=root)
    image_paths = blockbeat_card_paths(trading_date, slot, root=root)
    meta = SLOT_TITLE_META[slot]
    report_sha = sha256_file(report)
    signature = children_signature(children)
    payload = {
        "schema_version": "daily-publish-payload-v2",
        "date": trading_date,
        "title": (
            f"{meta['emoji']} {display_date(trading_date)} {meta['label']}"
            f"（{meta['score_time']} 评分点）"
        ),
        "title_prefix": meta["emoji"],
        "verifier_mode": slot,
        "report_path": _relative(report, root),
        "source_specs": source_specs,
        "children": children,
        "image_after_heading": "基本面",
        "image_paths": image_paths,
        "payload_source": {
            "schema_version": "daily-payload-source-v1",
            "kind": "combined_md_to_notion_payload",
            "generator": GENERATOR_NAME,
            "generator_version": GENERATOR_VERSION,
            "report_path": _relative(report, root),
            "report_sha256": report_sha,
            "children_signature_sha256": _json_hash(signature),
            "source_specs_sha256": _json_hash(_normalized_source_specs(source_specs, root)),
            "image_paths_sha256": _json_hash(_normalized_paths(image_paths, root)),
        },
    }
    return payload


def _resolve_path(value: str, root: Path) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _normalized_paths(paths: list[str], root: Path) -> list[str]:
    return [_relative(_resolve_path(str(path), root), root) for path in paths]


def _normalized_source_specs(source_specs: dict, root: Path) -> dict:
    normalized = {}
    for label, raw in source_specs.items():
        spec = {"path": raw} if isinstance(raw, str) else dict(raw)
        spec["path"] = _relative(_resolve_path(str(spec["path"]), root), root)
        normalized[label] = spec
    return normalized


def validate_payload_derivation(
    payload: dict,
    report_path: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict:
    if payload.get("verifier_mode") not in {"morning", "midday", "evening"}:
        return {"status": "skipped", "reason": "non-daily verifier mode"}
    if not strict_contract_active(trading_date):
        return {"status": "skipped", "reason": "historical report before derivation gate"}

    root = Path(root).resolve()
    report = report_path if Path(report_path).is_absolute() else root / report_path
    expected = build_daily_payload(report, root=root)
    expected_source = expected["payload_source"]
    actual_source = payload.get("payload_source")
    if not isinstance(actual_source, dict):
        raise ValueError("daily payload is missing payload_source derivation evidence")
    source_keys = (
        "kind",
        "generator",
        "generator_version",
        "report_path",
        "report_sha256",
        "children_signature_sha256",
        "source_specs_sha256",
        "image_paths_sha256",
    )
    for key in source_keys:
        if actual_source.get(key) != expected_source.get(key):
            raise ValueError(
                f"daily payload source evidence mismatch for {key}: "
                f"expected={expected_source.get(key)!r}, actual={actual_source.get(key)!r}"
            )

    scalar_keys = ("date", "title", "title_prefix", "verifier_mode", "image_after_heading")
    for key in scalar_keys:
        if payload.get(key) != expected.get(key):
            raise ValueError(
                f"daily payload scalar drift for {key}: "
                f"expected={expected.get(key)!r}, actual={payload.get(key)!r}"
            )

    actual_signature = children_signature(payload.get("children", []))
    expected_signature = children_signature(expected["children"])
    if actual_signature != expected_signature:
        for expected_item, actual_item in zip(expected_signature, actual_signature):
            if expected_item != actual_item:
                raise ValueError(
                    "daily payload children are not derived from combined report: "
                    f"block {expected_item['index']} expected={expected_item!r}, "
                    f"actual={actual_item!r}"
                )
        raise ValueError("daily payload children count drift from combined report")

    expected_images = _normalized_paths(expected["image_paths"], root)
    actual_images = _normalized_paths([str(path) for path in payload.get("image_paths", [])], root)
    if actual_images != expected_images:
        raise ValueError(
            f"daily payload image_paths drift: expected={expected_images}, actual={actual_images}"
        )

    expected_specs = _normalized_source_specs(expected["source_specs"], root)
    actual_specs = _normalized_source_specs(payload.get("source_specs", {}), root)
    if actual_specs != expected_specs:
        raise ValueError("daily payload source_specs drift from locked evidence snapshot")

    report_sha = sha256_file(report)
    result = copy.deepcopy(expected_source)
    result.update(
        {
            "status": "passed",
            "report_sha256": report_sha,
            "children_signature_sha256": _json_hash(actual_signature),
        }
    )
    return result


def write_daily_payload(report_path: Path, output_path: Path | None = None, *, root: Path = ROOT) -> Path:
    payload = build_daily_payload(report_path, root=root)
    target = output_path
    if target is None:
        report = Path(report_path)
        if not report.is_absolute():
            report = Path(root) / report
        match = re.match(r"^(20\d{2}-\d{2}-\d{2})_(morning|midday|evening)_", report.name)
        if not match:
            raise ValueError("combined report filename must start with YYYY-MM-DD_slot_")
        trading_date, slot = match.groups()
        target = Path(root) / "outputs" / f"{trading_date}_{slot}_publish_payload.json"
    else:
        target = Path(output_path)
        if not target.is_absolute():
            target = Path(root) / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a daily Notion publish payload from combined Markdown"
    )
    parser.add_argument("combined", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = write_daily_payload(args.combined.resolve(), args.output, root=ROOT)
    print(str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
