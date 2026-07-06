# -*- coding: utf-8 -*-
"""Mechanical contract for evening independent review publishing.

The review page is trader-facing analysis, not an execution audit. This module
keeps that boundary mechanical: the page must use the independent review shape,
must score every required segment by dimension, and must not leak runner,
payload, or lock terminology into visible Notion content.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from report_structure_gate import display_date, strict_contract_active
except ModuleNotFoundError:  # pragma: no cover - package import path
    from outputs.report_structure_gate import display_date, strict_contract_active


CONTRACT_VERSION = "evening-review-contract-v1"
REVIEW_FONT_TEMPLATE = "review-font-rendering-v1"
SOURCE_KIND = "post_lock_evening_independent_review"
SOURCE_SCHEMA_VERSION = "evening-review-source-v1"
MANIFEST_SCHEMA_VERSION = "evening-independent-review-v2"

REVIEW_PAYLOAD_TYPES = (
    "callout",
    "heading_2",
    "table",
    "heading_2",
    "table",
    "callout",
    "heading_2",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
)
REVIEW_REQUIRED_SEGMENTS = ("前一晚报", "当天早报", "当天午报")
REVIEW_SCORE_DIMENSIONS = (
    "方向判断",
    "入场结构",
    "风险框架",
    "数据精度",
    "内在一致性",
)
REVIEW_SCORE_ROWS = REVIEW_SCORE_DIMENSIONS + ("综合",)
REVIEW_SCORE_HEADER = ("维度",) + REVIEW_REQUIRED_SEGMENTS + ("综合",)
REVIEW_PRICE_TABLE_REQUIRED_HEADERS = ("区域", "当前计划处理", "审查意见")
REVIEW_FINDING_BLOCKS = range(7, 13)
REVIEW_CURRENT_SEGMENT_LABEL = "当前晚报"
REVIEW_SEGMENT_COLORS = {
    REVIEW_REQUIRED_SEGMENTS[0]: "orange",
    REVIEW_REQUIRED_SEGMENTS[1]: "red",
    REVIEW_REQUIRED_SEGMENTS[2]: "green",
}
REVIEW_PRICE_SEGMENT_COLORS = {
    **REVIEW_SEGMENT_COLORS,
    REVIEW_CURRENT_SEGMENT_LABEL: "blue",
}
REVIEW_FINDING_COLORS = ("green", "orange", "red", "green", "red", "yellow")

SYSTEM_NARRATIVE_PATTERNS = (
    (r"\banalysis[_-]?lock\b", "analysis lock"),
    (r"\block-analysis\b", "lock-analysis command"),
    (r"\bcombined\b", "combined artifact"),
    (r"\bcommit(?:_id)?\b", "commit metadata"),
    (r"\bfinalize-post-lock\b", "post-lock command"),
    (r"\bWord-QA\b", "Word QA command"),
    (r"\bpayload\b", "payload metadata"),
    (r"\bpublish(?:_report)?\b", "publish command"),
    (r"\bcontext_log\b", "context log"),
    (r"\bdeliver\b", "delivery command"),
    (r"\bverifier\b", "verifier metadata"),
    (r"\breport_sha", "hash metadata"),
    (r"\bruntime_state\b", "runtime state path"),
    (r"\bpre[-_]?MD\b", "pre-MD process"),
    (r"\bprelock\b", "prelock process"),
    (r"分析锁", "分析锁"),
    (r"锁后", "锁后流程"),
    (r"锁定晚报", "锁定产物"),
    (r"只读材料", "只读材料流程"),
    (r"回写", "回写流程"),
    (r"硬门", "硬门术语"),
    (r"下一步：执行", "执行流水线"),
)


def _rich_text_plain(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("plain_text") is not None:
            parts.append(str(item.get("plain_text", "")))
            continue
        text = item.get("text")
        if isinstance(text, dict):
            parts.append(str(text.get("content", "")))
    return "".join(parts).strip()


def block_plain_text(block: dict[str, Any]) -> str:
    block_type = block.get("type")
    body = block.get(block_type)
    if not isinstance(body, dict):
        return ""
    return _rich_text_plain(body.get("rich_text"))


def _cell_plain(cell: Any) -> str:
    return _rich_text_plain(cell)


def _annotations(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    annotations = item.get("annotations")
    return annotations if isinstance(annotations, dict) else {}


def _run_color(item: Any) -> str:
    color = _annotations(item).get("color")
    return str(color or "default")


def _run_bold(item: Any) -> bool:
    return bool(_annotations(item).get("bold"))


def _text_runs(block: dict[str, Any]) -> list[dict[str, Any]]:
    block_type = block.get("type")
    body = block.get(block_type)
    if not isinstance(body, dict):
        return []
    runs = body.get("rich_text")
    return [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []


def _table_child_rows(block: dict[str, Any]) -> list[dict[str, Any]]:
    if block.get("type") != "table":
        raise ValueError("review contract expected a table block")
    table = block.get("table")
    if not isinstance(table, dict):
        raise ValueError("review table block is missing table body")
    raw_rows = table.get("children")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("review table block is missing child rows")
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict) or row.get("type") != "table_row":
            raise ValueError("review table child must be table_row")
        rows.append(row)
    return rows


def _cell_runs(block: dict[str, Any], row_index: int, column_index: int) -> list[dict[str, Any]]:
    rows = _table_child_rows(block)
    try:
        row = rows[row_index]
    except IndexError as exc:
        raise ValueError(f"review table missing row {row_index + 1}") from exc
    body = row.get("table_row")
    if not isinstance(body, dict) or not isinstance(body.get("cells"), list):
        raise ValueError("review table_row is missing cells")
    try:
        cell = body["cells"][column_index]
    except IndexError as exc:
        raise ValueError(
            f"review table row {row_index + 1} missing column {column_index + 1}"
        ) from exc
    return [run for run in cell if isinstance(run, dict)] if isinstance(cell, list) else []


def review_score_color(score: int) -> str:
    if score >= 80:
        return "green"
    if score >= 70:
        return "yellow"
    if score >= 60:
        return "orange"
    return "red"


def table_rows(block: dict[str, Any]) -> list[list[str]]:
    raw_rows = _table_child_rows(block)
    rows: list[list[str]] = []
    for row in raw_rows:
        body = row.get("table_row")
        if not isinstance(body, dict) or not isinstance(body.get("cells"), list):
            raise ValueError("review table_row is missing cells")
        rows.append([_cell_plain(cell) for cell in body["cells"]])
    return rows


def _table_text(block: dict[str, Any]) -> str:
    return "\n".join(" | ".join(row) for row in table_rows(block))


def collect_visible_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "table":
            try:
                parts.append(_table_text(block))
            except ValueError:
                parts.append("")
            continue
        parts.append(block_plain_text(block))
    return "\n".join(part for part in parts if part)


def _first_number(value: str) -> int | None:
    match = re.search(r"(?<!\d)(100|[1-9]?\d)(?!\d)", value)
    if not match:
        return None
    return int(match.group(1))


def _assert_score_cell(value: str, label: str) -> int:
    score = _first_number(value)
    if score is None or not 0 <= score <= 100:
        raise ValueError(f"review score table {label} must contain a 0-100 score")
    return score


def _assert_no_system_narrative(text: str) -> None:
    hits: list[str] = []
    for pattern, description in SYSTEM_NARRATIVE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            hits.append(f"{description}: {match.group(0)}")
    if hits:
        raise ValueError(
            "review visible content contains system/process terms: "
            + "; ".join(hits[:8])
        )


def _validate_review_title(title: str | None, trading_date: str | None) -> None:
    if title is None:
        return
    if trading_date:
        expected = f"🔍 {display_date(trading_date)} 晚间独立审查（倒推）"
        if title != expected:
            raise ValueError(f"review title drift: expected {expected!r}, got {title!r}")
        return
    pattern = r"^🔍 20\d{2}\.\d{1,2}\.\d{1,2} 晚间独立审查（倒推）$"
    if not re.match(pattern, title):
        raise ValueError(f"review title does not match independent review format: {title!r}")


def validate_review_blocks(
    children: list[dict[str, Any]],
    *,
    title: str | None = None,
    trading_date: str | None = None,
) -> dict[str, Any]:
    """Validate the visible independent review Notion block contract."""
    if not isinstance(children, list):
        raise ValueError("review payload shape gate requires children array")
    _validate_review_title(title, trading_date)

    actual_types = tuple(
        block.get("type") if isinstance(block, dict) else None
        for block in children
    )
    if actual_types != REVIEW_PAYLOAD_TYPES:
        raise ValueError(
            "review Notion payload block type sequence does not match contract: "
            f"expected={list(REVIEW_PAYLOAD_TYPES)}, actual={list(actual_types)}"
        )

    visible_text = collect_visible_text(children)
    if "??" in visible_text:
        raise ValueError("review visible content looks encoding-corrupted")
    _assert_no_system_narrative(visible_text)

    intro = block_plain_text(children[0])
    if not intro.startswith("审查结论："):
        raise ValueError("review first callout must start with 审查结论：")

    score_heading = block_plain_text(children[1])
    if "综合评分" not in score_heading or "去系统逻辑" not in score_heading:
        raise ValueError(
            "review first section must be 综合评分（去系统逻辑 · 独立打分）"
        )
    score_rows = table_rows(children[2])
    if not score_rows or tuple(score_rows[0]) != REVIEW_SCORE_HEADER:
        raise ValueError(
            "review score table header must be "
            + " / ".join(REVIEW_SCORE_HEADER)
        )
    if len(score_rows) != len(REVIEW_SCORE_ROWS) + 1:
        raise ValueError(
            "review score table must contain exactly five dimensions plus 综合"
        )
    for index, expected_dimension in enumerate(REVIEW_SCORE_ROWS, 1):
        row = score_rows[index]
        if len(row) != len(REVIEW_SCORE_HEADER):
            raise ValueError(f"review score table row {index + 1} has wrong width")
        if row[0] != expected_dimension:
            raise ValueError(
                f"review score table row {index + 1} must be {expected_dimension!r}"
            )
        for column, value in zip(REVIEW_SCORE_HEADER[1:], row[1:]):
            _assert_score_cell(value, f"{expected_dimension}/{column}")

    price_heading = block_plain_text(children[3])
    if not price_heading.startswith("二、价格阶梯"):
        raise ValueError("review second section must start with 二、价格阶梯")
    price_rows = table_rows(children[4])
    if len(price_rows) < 4:
        raise ValueError("review price ladder table must contain header plus evidence rows")
    price_header = tuple(price_rows[0])
    for header in REVIEW_PRICE_TABLE_REQUIRED_HEADERS:
        if header not in price_header:
            raise ValueError(f"review price ladder table missing header {header!r}")
    price_text = "\n".join(" | ".join(row) for row in price_rows)
    missing_segments = [
        segment for segment in REVIEW_REQUIRED_SEGMENTS if segment not in price_text
    ]
    if missing_segments:
        raise ValueError(
            "review price ladder table must cover all three prior segments: "
            + ", ".join(missing_segments)
        )

    conflict = block_plain_text(children[5])
    if not conflict.startswith("核心矛盾："):
        raise ValueError("review middle callout must start with 核心矛盾：")

    finding_heading = block_plain_text(children[6])
    if not finding_heading.startswith("三、关键发现"):
        raise ValueError("review third section must start with 三、关键发现")
    for index in REVIEW_FINDING_BLOCKS:
        text = block_plain_text(children[index])
        if not text.startswith("发现"):
            raise ValueError(f"review finding block {index + 1} must start with 发现")
    boundary = block_plain_text(children[13])
    if not boundary.startswith(("审查边界：", "独立边界：")):
        raise ValueError("review boundary block must start with 审查边界： or 独立边界：")
    final_text = block_plain_text(children[14])
    if final_text.startswith("下一步"):
        raise ValueError("review final block must not contain execution next steps")
    if not final_text.startswith(("复盘结论：", "审查结论：", "独立边界：")):
        raise ValueError("review final block must be a user-facing conclusion")

    return {
        "status": "passed",
        "template": CONTRACT_VERSION,
        "block_count_before_images": len(children),
        "image_count": 0,
        "score_dimensions": list(REVIEW_SCORE_ROWS),
        "segments": list(REVIEW_REQUIRED_SEGMENTS),
    }


def validate_review_payload_shape(payload: dict[str, Any], trading_date: str) -> dict[str, Any]:
    if payload.get("verifier_mode") != "review":
        return {"status": "skipped", "reason": "non-review verifier mode"}
    if not strict_contract_active(trading_date):
        return {"status": "skipped", "reason": "historical report before strict review gate"}
    if payload.get("title_prefix") != "🔍":
        raise ValueError("review payload title_prefix must be 🔍")
    if payload.get("image_paths") != []:
        raise ValueError("review payload must not publish report images")
    if payload.get("image_after_heading") not in ("", None):
        raise ValueError("review payload image_after_heading must be empty")
    return validate_review_blocks(
        payload.get("children"),
        title=str(payload.get("title", "")),
        trading_date=trading_date,
    )


def _assert_cell_style(
    block: dict[str, Any],
    row_index: int,
    column_index: int,
    *,
    expected_color: str,
    label: str,
    require_bold: bool = False,
) -> None:
    runs = _cell_runs(block, row_index, column_index)
    if not runs:
        raise ValueError(f"{label} has no rich_text runs")
    matching = [run for run in runs if _run_color(run) == expected_color]
    if not matching:
        actual = sorted({_run_color(run) for run in runs})
        raise ValueError(
            f"{label} must render font color {expected_color!r}; actual={actual}"
        )
    if require_bold and not any(_run_bold(run) for run in matching):
        raise ValueError(f"{label} must render bold text with color {expected_color!r}")


def _assert_cell_bold(
    block: dict[str, Any],
    row_index: int,
    column_index: int,
    *,
    label: str,
) -> None:
    runs = _cell_runs(block, row_index, column_index)
    if not runs or not any(_run_bold(run) for run in runs):
        raise ValueError(f"{label} must render bold text")


def _assert_text_block_style(
    block: dict[str, Any],
    *,
    expected_color: str,
    label: str,
    require_bold: bool = False,
    first_run_only: bool = False,
) -> None:
    runs = _text_runs(block)
    if not runs:
        raise ValueError(f"{label} has no rich_text runs")
    checked = runs[:1] if first_run_only else runs
    matching = [run for run in checked if _run_color(run) == expected_color]
    if not matching:
        actual = [_run_color(run) for run in checked]
        raise ValueError(
            f"{label} must render font color {expected_color!r}; actual={actual}"
        )
    if require_bold and not any(_run_bold(run) for run in matching):
        raise ValueError(f"{label} must render bold text with color {expected_color!r}")


def review_text_color_summary(children: list[dict[str, Any]]) -> dict[str, Any]:
    color_counts: dict[str, int] = {}
    bold_runs = 0
    total_runs = 0
    for block in children:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "table":
            for row in _table_child_rows(block):
                body = row.get("table_row", {})
                cells = body.get("cells") if isinstance(body, dict) else None
                if not isinstance(cells, list):
                    continue
                for cell in cells:
                    if not isinstance(cell, list):
                        continue
                    for run in cell:
                        if not isinstance(run, dict):
                            continue
                        total_runs += 1
                        if _run_bold(run):
                            bold_runs += 1
                        color = _run_color(run)
                        if color != "default":
                            color_counts[color] = color_counts.get(color, 0) + 1
            continue
        for run in _text_runs(block):
            total_runs += 1
            if _run_bold(run):
                bold_runs += 1
            color = _run_color(run)
            if color != "default":
                color_counts[color] = color_counts.get(color, 0) + 1
    return {
        "total_runs": total_runs,
        "bold_runs": bold_runs,
        "non_default_runs": sum(color_counts.values()),
        "colors": dict(sorted(color_counts.items())),
    }


def validate_review_payload_colors(payload_or_children: Any) -> dict[str, Any]:
    """Validate native Notion rich_text font rendering for independent review pages."""
    if isinstance(payload_or_children, dict):
        if payload_or_children.get("verifier_mode") != "review":
            return {"status": "skipped", "reason": "non-review verifier mode"}
        children = payload_or_children.get("children")
    else:
        children = payload_or_children
    validate_review_blocks(children)

    score_table = children[2]
    score_rows = table_rows(score_table)
    for column_index, header in enumerate(REVIEW_SCORE_HEADER):
        _assert_cell_bold(
            score_table,
            0,
            column_index,
            label=f"review score header {header}",
        )

    score_cells_checked = 0
    for row_index, row in enumerate(score_rows[1:], 1):
        dimension = row[0]
        is_total_row = dimension == REVIEW_SCORE_ROWS[-1]
        for column_index, column in enumerate(REVIEW_SCORE_HEADER[1:], 1):
            score = _assert_score_cell(row[column_index], f"{dimension}/{column}")
            expected_color = review_score_color(score)
            _assert_cell_style(
                score_table,
                row_index,
                column_index,
                expected_color=expected_color,
                label=f"review score cell {dimension}/{column}",
                require_bold=is_total_row or column == REVIEW_SCORE_HEADER[-1],
            )
            score_cells_checked += 1

    price_table = children[4]
    price_rows = table_rows(price_table)
    for column_index, header in enumerate(price_rows[0]):
        _assert_cell_bold(
            price_table,
            0,
            column_index,
            label=f"review price header {header}",
        )
    price_rows_checked = 0
    for row_index, row in enumerate(price_rows[1:], 1):
        if len(row) < 5:
            raise ValueError(f"review price row {row_index + 1} has wrong width")
        segment = row[1]
        expected_color = REVIEW_PRICE_SEGMENT_COLORS.get(segment)
        if expected_color is None:
            raise ValueError(
                f"review price row {row_index + 1} has unknown segment {segment!r}"
            )
        _assert_cell_style(
            price_table,
            row_index,
            1,
            expected_color=expected_color,
            label=f"review price segment {segment}",
            require_bold=True,
        )
        _assert_cell_style(
            price_table,
            row_index,
            4,
            expected_color=expected_color,
            label=f"review price opinion {segment}",
        )
        price_rows_checked += 1

    _assert_text_block_style(
        children[0],
        expected_color="green",
        label="review intro callout",
        require_bold=True,
    )
    _assert_text_block_style(
        children[5],
        expected_color="orange",
        label="review conflict callout",
        require_bold=True,
    )
    for offset, block_index in enumerate(REVIEW_FINDING_BLOCKS):
        expected_color = REVIEW_FINDING_COLORS[offset]
        _assert_text_block_style(
            children[block_index],
            expected_color=expected_color,
            label=f"review finding block {block_index + 1}",
            require_bold=True,
            first_run_only=True,
        )
    _assert_text_block_style(
        children[13],
        expected_color="gray",
        label="review boundary block",
        require_bold=True,
        first_run_only=True,
    )
    _assert_text_block_style(
        children[14],
        expected_color="green",
        label="review final conclusion block",
        require_bold=True,
        first_run_only=True,
    )
    summary = review_text_color_summary(children)
    return {
        "status": "passed",
        "template": REVIEW_FONT_TEMPLATE,
        "score_cells_checked": score_cells_checked,
        "price_rows_checked": price_rows_checked,
        "finding_blocks_checked": len(REVIEW_FINDING_BLOCKS),
        "color_summary": summary,
    }


def _json_hash(value: Any) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def review_children_signature(children: list[dict[str, Any]]) -> str:
    return _json_hash(children)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _resolve_repo_path(value: str, root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _assert_inside(path: Path, allowed_root: Path, message: str) -> None:
    try:
        path.resolve().relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise ValueError(message) from exc


def _score_map(segment: dict[str, Any]) -> dict[str, Any]:
    scores = segment.get("scores")
    if not isinstance(scores, dict):
        scores = segment.get("dimension_scores")
    if not isinstance(scores, dict):
        raise ValueError("review manifest segment is missing dimension scores")
    return scores


def validate_review_manifest(
    manifest: dict[str, Any],
    *,
    trading_date: str,
    report_path: str,
    report_sha256: str,
) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            "review manifest schema_version must be "
            f"{MANIFEST_SCHEMA_VERSION!r}"
        )
    if manifest.get("trading_date") != trading_date:
        raise ValueError("review manifest date mismatch")
    if manifest.get("slot") != "evening":
        raise ValueError("review manifest slot must be evening")
    if manifest.get("report_path") != report_path:
        raise ValueError("review manifest report_path mismatch")
    if manifest.get("report_sha256") != report_sha256:
        raise ValueError("review manifest report_sha256 mismatch")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, list):
        raise ValueError("review manifest inputs must be an array")
    input_labels = {
        str(item.get("label", "")) for item in inputs if isinstance(item, dict)
    }
    missing_inputs = [
        segment for segment in REVIEW_REQUIRED_SEGMENTS if segment not in input_labels
    ]
    if missing_inputs:
        raise ValueError(
            "review manifest inputs missing required segments: "
            + ", ".join(missing_inputs)
        )

    segments = manifest.get("segments")
    if not isinstance(segments, list) or len(segments) != len(REVIEW_REQUIRED_SEGMENTS):
        raise ValueError("review manifest must contain exactly three reviewed segments")
    for required in REVIEW_REQUIRED_SEGMENTS:
        matches = [
            segment
            for segment in segments
            if isinstance(segment, dict)
            and (
                segment.get("label") == required
                or str(segment.get("segment", "")).startswith(required)
            )
        ]
        if len(matches) != 1:
            raise ValueError(f"review manifest must contain one segment for {required}")
        scores = _score_map(matches[0])
        for dimension in REVIEW_SCORE_ROWS:
            if dimension not in scores:
                raise ValueError(
                    f"review manifest {required} missing score dimension {dimension}"
                )
            _assert_score_cell(str(scores[dimension]), f"{required}/{dimension}")
    return {
        "status": "passed",
        "template": CONTRACT_VERSION,
        "schema_version": manifest.get("schema_version"),
        "segments": list(REVIEW_REQUIRED_SEGMENTS),
        "score_dimensions": list(REVIEW_SCORE_ROWS),
    }


def validate_review_payload_source(
    payload: dict[str, Any],
    report_path: Path,
    trading_date: str,
    report_slot: str,
    *,
    root: Path,
) -> dict[str, Any]:
    if payload.get("verifier_mode") != "review":
        return {"status": "skipped", "reason": "non-review verifier mode"}
    if not strict_contract_active(trading_date):
        return {"status": "skipped", "reason": "historical report before strict review gate"}
    if report_slot != "evening":
        raise ValueError("review publish must be bound to the evening combined report")

    root = Path(root).resolve()
    report = report_path.resolve() if report_path.is_absolute() else (root / report_path).resolve()
    _assert_inside(report, root, "review report path escapes repository root")
    report_rel = _relative(report, root)
    report_hash = _sha256_file(report)

    source = payload.get("payload_source")
    if not isinstance(source, dict):
        raise ValueError("review payload is missing payload_source contract evidence")
    if source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError(f"review payload_source schema_version must be {SOURCE_SCHEMA_VERSION}")
    if source.get("kind") != SOURCE_KIND:
        raise ValueError(f"review payload_source kind must be {SOURCE_KIND}")
    if source.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"review payload_source contract_version must be {CONTRACT_VERSION}")
    if source.get("report_path") != report_rel:
        raise ValueError("review payload_source report_path mismatch")
    if source.get("report_sha256") != report_hash:
        raise ValueError("review payload_source report_sha256 mismatch")

    expected_signature = review_children_signature(payload.get("children", []))
    if source.get("children_signature_sha256") != expected_signature:
        raise ValueError("review payload_source children_signature_sha256 mismatch")

    manifest_value = source.get("review_manifest")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise ValueError("review payload_source review_manifest is missing")
    manifest_path = _resolve_repo_path(manifest_value, root)
    runtime_root = root / "runtime_state" / trading_date
    _assert_inside(
        manifest_path,
        runtime_root,
        "review manifest must be inside runtime_state/<date>",
    )
    if not manifest_path.is_file():
        raise ValueError(f"review manifest is missing: {manifest_path}")
    manifest_hash = _sha256_file(manifest_path)
    if source.get("review_manifest_sha256") != manifest_hash:
        raise ValueError("review payload_source review_manifest_sha256 mismatch")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_evidence = validate_review_manifest(
        manifest,
        trading_date=trading_date,
        report_path=report_rel,
        report_sha256=report_hash,
    )
    return {
        "status": "passed",
        "kind": SOURCE_KIND,
        "template": CONTRACT_VERSION,
        "review_manifest": _relative(manifest_path, root),
        "review_manifest_sha256": manifest_hash,
        "report_path": report_rel,
        "report_sha256": report_hash,
        "children_signature_sha256": expected_signature,
        "manifest": manifest_evidence,
    }
