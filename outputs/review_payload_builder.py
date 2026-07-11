# -*- coding: utf-8 -*-
"""Build evening independent review Notion payloads from a review manifest.

This builder is intentionally separate from daily report payload generation. It
does not read or derive daily source specs, does not run daily lint/freshness
checks, and never creates HTML/Word/PDF review artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUTS_DIR = Path(__file__).resolve().parent
if str(OUTPUTS_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUTS_DIR))

from report_structure_gate import display_date
from runtime.state_store import atomic_json_write

from review_contract import (
    CONTRACT_VERSION,
    MANIFEST_SCHEMA_VERSION,
    REVIEW_FINDING_COLORS,
    REVIEW_PRICE_SEGMENT_COLORS,
    REVIEW_REQUIRED_SEGMENTS,
    REVIEW_SCORE_ROWS,
    SOURCE_KIND,
    SOURCE_SCHEMA_VERSION,
    review_score_color,
    review_children_signature,
    validate_review_blocks,
    validate_review_manifest,
    validate_review_payload_colors,
    validate_review_payload_source,
)


BUILDER_NAME = "review_payload_builder"
REVIEW_RETIREMENT_DATE = "2026-07-09"
BUILDER_VERSION = "1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _resolve(value: str, root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _annotations(*, color: str = "default", bold: bool = False) -> dict[str, Any]:
    return {
        "bold": bool(bold),
        "italic": False,
        "strikethrough": False,
        "underline": False,
        "code": False,
        "color": color or "default",
    }


def _run(text: str, *, color: str = "default", bold: bool = False) -> dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": text},
        "annotations": _annotations(color=color, bold=bold),
    }


def _rich_text(
    text: str,
    *,
    bold: bool = False,
    color: str = "default",
) -> list[dict[str, Any]]:
    return [_run(str(text), color=color, bold=bold)]


def _emphasis_prefix_runs(
    text: str,
    *,
    color: str,
    bold: bool = True,
) -> list[dict[str, Any]]:
    for marker in ("：", ":"):
        if marker in text:
            prefix, rest = text.split(marker, 1)
            runs = [_run(prefix + marker, color=color, bold=bold)]
            if rest:
                runs.append(_run(rest))
            return runs
    return _rich_text(text, color=color, bold=bold)


def _text_block(
    block_type: str,
    text: str,
    *,
    color: str | None = None,
    rich_text: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"rich_text": rich_text if rich_text is not None else _rich_text(text)}
    if color is not None:
        body["color"] = color
    return {"object": "block", "type": block_type, block_type: body}


def _callout(
    text: str,
    *,
    color: str,
    emoji: str,
    text_color: str,
    bold: bool = True,
) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": _rich_text(text, color=text_color, bold=bold),
            "icon": {"emoji": emoji},
            "color": color,
        },
    }


def _table_row(
    cells: list[str],
    *,
    header: bool = False,
    styles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    styles = styles or [{} for _ in cells]
    return {
        "type": "table_row",
        "table_row": {
            "cells": [
                _rich_text(
                    str(cell),
                    bold=bool(header or style.get("bold")),
                    color=str(style.get("color", "default")),
                )
                for cell, style in zip(cells, styles)
            ]
        },
    }


def _table(
    rows: list[list[str]],
    *,
    row_styles: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if not rows or not rows[0]:
        raise ValueError("review table requires at least one row and one column")
    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise ValueError("review table rows must have a stable width")
    row_styles = row_styles or [[{} for _ in row] for row in rows]
    if len(row_styles) != len(rows) or any(len(styles) != width for styles in row_styles):
        raise ValueError("review table style matrix must match table shape")
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": [
                _table_row(row, header=index == 0, styles=row_styles[index])
                for index, row in enumerate(rows)
            ],
        },
    }


def _score_map(segment: dict[str, Any]) -> dict[str, Any]:
    scores = segment.get("scores")
    if isinstance(scores, dict):
        return scores
    scores = segment.get("dimension_scores")
    if isinstance(scores, dict):
        return scores
    raise ValueError("review manifest segment is missing scores")


def _segments_by_label(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    segments = manifest.get("segments")
    if not isinstance(segments, list):
        raise ValueError("review manifest segments must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in segments:
        if not isinstance(item, dict):
            raise ValueError("review manifest segment must be an object")
        label = str(item.get("label") or item.get("segment", "").split(" -> ")[0])
        if label in REVIEW_REQUIRED_SEGMENTS:
            result[label] = item
    missing = [label for label in REVIEW_REQUIRED_SEGMENTS if label not in result]
    if missing:
        raise ValueError("review manifest missing segments: " + ", ".join(missing))
    return result


def _score_rows(manifest: dict[str, Any]) -> list[list[str]]:
    by_label = _segments_by_label(manifest)
    rows = [["维度", *REVIEW_REQUIRED_SEGMENTS, "综合"]]
    for dimension in REVIEW_SCORE_ROWS:
        segment_scores = [
            str(_score_map(by_label[label])[dimension])
            for label in REVIEW_REQUIRED_SEGMENTS
        ]
        aggregate = str(
            manifest.get("aggregate_scores", {}).get(
                dimension,
                round(
                    sum(int(value) for value in segment_scores)
                    / len(segment_scores)
                ),
            )
        )
        rows.append([dimension, *segment_scores, aggregate])
    return rows


def _score_value(value: str) -> int:
    try:
        return int(float(str(value).strip()))
    except ValueError as exc:
        raise ValueError(f"review score value must be numeric: {value!r}") from exc


def _score_table(manifest: dict[str, Any]) -> dict[str, Any]:
    rows = _score_rows(manifest)
    styles: list[list[dict[str, Any]]] = []
    total_row_index = len(rows) - 1
    total_column_index = len(rows[0]) - 1
    for row_index, row in enumerate(rows):
        row_styles: list[dict[str, Any]] = []
        for column_index, cell in enumerate(row):
            style: dict[str, Any] = {}
            if row_index == 0:
                style["bold"] = True
            elif column_index > 0:
                score = _score_value(cell)
                style["color"] = review_score_color(score)
                if row_index == total_row_index or column_index == total_column_index:
                    style["bold"] = True
            elif row_index == total_row_index:
                style["bold"] = True
            row_styles.append(style)
        styles.append(row_styles)
    return _table(rows, row_styles=styles)


def _required_page_value(page: dict[str, Any], key: str) -> str:
    value = page.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"review manifest page.{key} is required")
    return value.strip()


def _price_rows(page: dict[str, Any]) -> list[list[str]]:
    rows = page.get("price_ladder")
    if not isinstance(rows, list) or len(rows) < 3:
        raise ValueError("review manifest page.price_ladder must contain at least three rows")
    out = [["区域", "前序段", "当晚含义", "当前计划处理", "审查意见"]]
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("review manifest price ladder row must be an object")
        out.append(
            [
                str(item.get("zone", "")).strip(),
                str(item.get("segment", "")).strip(),
                str(item.get("meaning", "")).strip(),
                str(item.get("current_plan", "")).strip(),
                str(item.get("review", "")).strip(),
            ]
        )
    if any(not cell for row in out[1:] for cell in row):
        raise ValueError("review manifest price ladder rows must be fully populated")
    return out


def _price_table(page: dict[str, Any]) -> dict[str, Any]:
    rows = _price_rows(page)
    styles: list[list[dict[str, Any]]] = []
    for row_index, row in enumerate(rows):
        row_styles = [{} for _ in row]
        if row_index == 0:
            row_styles = [{"bold": True} for _ in row]
        else:
            segment = row[1]
            segment_color = REVIEW_PRICE_SEGMENT_COLORS.get(segment, "yellow")
            row_styles[1] = {"color": segment_color, "bold": True}
            row_styles[4] = {"color": segment_color}
        styles.append(row_styles)
    return _table(rows, row_styles=styles)


def _findings(page: dict[str, Any]) -> list[str]:
    findings = page.get("findings")
    if not isinstance(findings, list) or len(findings) != 6:
        raise ValueError("review manifest page.findings must contain exactly six items")
    result = []
    for index, item in enumerate(findings, 1):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"review manifest finding {index} is empty")
        text = item.strip()
        if not text.startswith("发现"):
            text = f"发现{index}：" + text
        result.append(text)
    return result


def _finding_block(index: int, text: str) -> dict[str, Any]:
    return _text_block(
        "paragraph",
        text,
        rich_text=_emphasis_prefix_runs(
            text,
            color=REVIEW_FINDING_COLORS[index - 1],
            bold=True,
        ),
    )


def children_from_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    page = manifest.get("page")
    if not isinstance(page, dict):
        raise ValueError("review manifest must include page content")
    children = [
        _callout(
            _required_page_value(page, "intro"),
            color="green_background",
            emoji="🔍",
            text_color="green",
            bold=True,
        ),
        _text_block("heading_2", "一、综合评分（去系统逻辑 · 独立打分）"),
        _score_table(manifest),
        _text_block("heading_2", "二、价格阶梯与三段倒推落点"),
        _price_table(page),
        _callout(
            _required_page_value(page, "core_conflict"),
            color="orange_background",
            emoji="⚠️",
            text_color="orange",
            bold=True,
        ),
        _text_block("heading_2", "三、关键发现"),
    ]
    children.extend(
        _finding_block(index, text)
        for index, text in enumerate(_findings(page), 1)
    )
    boundary = _required_page_value(page, "boundary")
    children.append(
        _text_block(
            "paragraph",
            boundary,
            rich_text=_emphasis_prefix_runs(boundary, color="gray", bold=True),
        )
    )
    final_conclusion = _required_page_value(page, "final_conclusion")
    children.append(
        _text_block(
            "paragraph",
            final_conclusion,
            rich_text=_emphasis_prefix_runs(final_conclusion, color="green", bold=True),
        )
    )
    return children


def build_review_payload(manifest_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("review manifest must be a JSON object")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"review manifest must use {MANIFEST_SCHEMA_VERSION}")
    trading_date = str(manifest.get("trading_date", ""))
    if trading_date >= REVIEW_RETIREMENT_DATE:
        raise RuntimeError(
            "evening independent review generation retired on 2026-07-09; "
            "use the external Trading accuracy evaluator"
        )
    report_rel = str(manifest.get("report_path", ""))
    report = _resolve(report_rel, root)
    report_hash = sha256_file(report)
    validate_review_manifest(
        manifest,
        trading_date=trading_date,
        report_path=_relative(report, root),
        report_sha256=report_hash,
    )
    children = children_from_manifest(manifest)
    title = f"🔍 {display_date(trading_date)} 晚间独立审查（倒推）"
    validate_review_blocks(children, title=title, trading_date=trading_date)
    validate_review_payload_colors({"verifier_mode": "review", "children": children})
    manifest_hash = sha256_file(manifest_path)
    payload = {
        "schema_version": "review-publish-payload-v1",
        "date": trading_date,
        "title": title,
        "title_prefix": "🔍",
        "verifier_mode": "review",
        "report_path": _relative(report, root),
        "children": children,
        "image_after_heading": "",
        "image_paths": [],
        "payload_source": {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "kind": SOURCE_KIND,
            "contract_version": CONTRACT_VERSION,
            "generator": BUILDER_NAME,
            "generator_version": BUILDER_VERSION,
            "review_manifest": _relative(manifest_path, root),
            "review_manifest_sha256": manifest_hash,
            "report_path": _relative(report, root),
            "report_sha256": report_hash,
            "children_signature_sha256": review_children_signature(children),
        },
    }
    validate_review_payload_source(
        payload,
        report,
        trading_date,
        "evening",
        root=root,
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an evening review Notion payload")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_review_payload(args.manifest.resolve(), root=ROOT)
    output = args.output
    if output is None:
        date_value = payload["date"]
        output = ROOT / "outputs" / f"{date_value}_evening_review_payload.json"
    output = output.resolve()
    atomic_json_write(output, payload)
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
