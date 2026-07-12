# -*- coding: utf-8 -*-
"""Canonical run-level color template for daily Notion reports.

This module owns the mechanical color distribution used by morning/midday
daily-report pages.  It mirrors the hand-written gold template shape: labels
mostly stay default, only semantic values and execution fields receive color.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Iterable

try:
    from .daily_publish_contract import (
        DAILY_VISUAL_PAYLOAD_TYPES_31,
        DAILY_VISUAL_PAYLOAD_TYPES_32,
    )
except ImportError:  # pragma: no cover - direct script/import from outputs/
    from daily_publish_contract import (
        DAILY_VISUAL_PAYLOAD_TYPES_31,
        DAILY_VISUAL_PAYLOAD_TYPES_32,
    )


TEXT_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "quote",
    "bulleted_list_item",
    "numbered_list_item",
    "callout",
    "toggle",
}

DAILY_TEXT_BLOCK_TYPES_25 = (
    "quote",
    "heading_2",
    "heading_3",
    "heading_3",
    "paragraph",
    "paragraph",
    "heading_3",
    "paragraph",
    "paragraph",
    "paragraph",
    "heading_3",
    "heading_3",
    "heading_3",
    "paragraph",
    "divider",
    "heading_2",
    "paragraph",
    "paragraph",
    "paragraph",
    "heading_3",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
    "paragraph",
)
DAILY_TEXT_BLOCK_TYPES_26 = DAILY_TEXT_BLOCK_TYPES_25 + ("paragraph",)
DAILY_TEXT_BLOCK_TYPE_SEQUENCES = {
    DAILY_TEXT_BLOCK_TYPES_25,
    DAILY_TEXT_BLOCK_TYPES_26,
    DAILY_VISUAL_PAYLOAD_TYPES_31,
    DAILY_VISUAL_PAYLOAD_TYPES_32,
}

VISUAL_V3_TO_LEGACY_STYLE_INDEX = {
    0: 0,
    2: 1,
    4: 2,
    6: 4,
    7: 5,
    9: 6,
    10: 7,
    11: 8,
    12: 9,
    14: 10,
    16: 11,
    18: 13,
    21: 15,
    22: 16,
    23: 17,
    24: 18,
    26: 20,
    27: 21,
    28: 22,
    29: 23,
    30: 24,
    31: 25,
}

SENTIMENT_COLORS = {
    "中性偏多偏空": "yellow",
    "中性偏空": "red",
    "中性偏多": "green",
    "中性": "yellow",
    "利空": "red",
    "利多": "green",
    "利好": "green",
    "空头趋势": "red",
    "多头趋势": "green",
    "震荡结构": "yellow",
}

BEARISH_HINTS = (
    "利空",
    "偏空",
    "空头",
    "卖压",
    "破位",
    "跌破",
    "下行",
    "做空",
    "高空",
    "反弹空",
)
BULLISH_HINTS = (
    "利多",
    "利好",
    "偏多",
    "多头",
    "买盘",
    "站上",
    "收复",
    "上升",
    "做多",
    "低多",
    "反弹多",
)


def _annotations(color: str = "default", bold: bool = False) -> dict:
    return {
        "bold": bool(bold),
        "italic": False,
        "strikethrough": False,
        "underline": False,
        "code": False,
        "color": color or "default",
    }


def _run(text: str, color: str = "default", bold: bool = False) -> dict:
    return {
        "type": "text",
        "text": {"content": text},
        "annotations": _annotations(color, bold),
    }


def _plain(block: dict) -> str:
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
    return "".join(parts)


def _set_runs(block: dict, runs: list[dict]) -> None:
    block_type = block.get("type")
    if block_type not in TEXT_TYPES:
        return
    body = block.setdefault(block_type, {})
    body["rich_text"] = [run for run in runs if run["text"]["content"]]


def _first_sentiment(text: str) -> tuple[str, str] | tuple[None, str]:
    value = text.lstrip()
    offset = len(text) - len(value)
    for sentiment in sorted(SENTIMENT_COLORS, key=len, reverse=True):
        if value.startswith(sentiment):
            return sentiment, text[offset + len(sentiment) :]
    return None, text


def _color_for_text(text: str, fallback: str = "yellow") -> str:
    stripped = text.strip()
    for sentiment, color in SENTIMENT_COLORS.items():
        if stripped == sentiment or sentiment in stripped:
            return color
    if any(token in stripped for token in BEARISH_HINTS):
        return "red"
    if any(token in stripped for token in BULLISH_HINTS):
        return "green"
    return fallback


def _split_prefix(text: str, prefixes: Iterable[str]) -> tuple[str, str]:
    for prefix in prefixes:
        if text.startswith(prefix):
            return prefix, text[len(prefix) :]
    return "", text


def _style_cannot_do(text: str) -> list[dict]:
    prefix, rest = _split_prefix(text, ("不能做：", "不能做:"))
    if not prefix:
        return [_run(text, "red", True)]
    return [_run(prefix), _run(rest, "red", True)]


def _style_price_realization(text: str) -> list[dict]:
    realized_prefixes = (
        "价格已部分兑现",
        "价格已兑现部分",
        "价格已经部分兑现",
        "价格已经兑现部分",
        "价格已兑现",
        "价格已经兑现",
    )
    for prefix in realized_prefixes:
        if text.startswith(prefix):
            tail = text[len(prefix) :]
            runs = [_run(prefix, "green", True)]
            if tail:
                color = "red" if any(token in tail for token in ("跌至", "跌破", "下行", "利空")) else "yellow"
                runs.append(_run(tail, color, True))
            return runs
    return [_run(text, "yellow", True)]


def _style_fundamental_tail(tail: str) -> list[dict]:
    if not tail:
        return []
    if tail.startswith("（"):
        close = tail.find("）")
        if close >= 0:
            reason = tail[: close + 1]
            rest = tail[close + 1 :]
            return [_run(reason, "yellow", True)] + _style_price_realization(rest)
    return _style_price_realization(tail)


def _style_fundamental(text: str) -> list[dict]:
    prefix, rest = _split_prefix(text, ("基本面：", "基本面:"))
    runs = [_run(prefix or "基本面：")]
    sentiment, tail = _first_sentiment(rest)
    if sentiment:
        runs.append(_run(sentiment, SENTIMENT_COLORS[sentiment], True))
    else:
        tail = rest
    runs.extend(_style_fundamental_tail(tail))
    return runs


def _split_first_clause(text: str) -> tuple[str, str]:
    for separator in ("，", "；", ";", "。"):
        index = text.find(separator)
        if index > 0:
            return text[:index], text[index:]
    return text, ""


def _style_interpretation(text: str) -> list[dict]:
    prefix, rest = _split_prefix(text, ("解读：", "解读:"))
    runs = [_run(prefix or "解读：")]
    sentiment, tail = _first_sentiment(rest)
    sentiment_color = "yellow"
    if sentiment:
        sentiment_color = SENTIMENT_COLORS[sentiment]
        runs.append(_run(sentiment, sentiment_color, True))
    else:
        tail = rest
    if tail.startswith("（"):
        runs.append(_run("（"))
        tail = tail[1:]
        close = "）" if tail.endswith("）") else ""
        if close:
            tail = tail[:-1]
        first, remaining = _split_first_clause(tail)
        if first:
            runs.append(_run(first, _color_for_text(first, sentiment_color), True))
        if remaining:
            runs.append(_run(remaining))
        if close:
            runs.append(_run(close))
    elif tail:
        runs.append(_run(tail))
    return runs


def _style_terminal_sentiment(text: str) -> list[dict]:
    match = re.search(
        r"(中性偏多偏空|中性偏空|中性偏多|利空|利多|中性)([。.]?)$",
        text.strip(),
    )
    if not match:
        return [_run(text)]
    start, end = match.span(1)
    prefix = text[:start]
    sentiment = match.group(1)
    suffix = text[end:]
    return [
        _run(prefix),
        _run(sentiment, SENTIMENT_COLORS.get(sentiment, _color_for_text(sentiment)), True),
        _run(suffix),
    ]


def _technical_signal_span(text: str) -> tuple[int, int, str] | None:
    signal_patterns = (
        (r"重新站上[^，；。]*", "green"),
        (r"站上[^，；。]*", "green"),
        (r"收复[^，；。]*", "green"),
        (r"短线多头结构未破", "green"),
        (r"跌破[^，；。]*", "red"),
        (r"价(?:格)?(?:于|在)[^，；。]*(?:下方|下方、[^，；。]*压制)", "red"),
        (r"下降趋势线压制", "red"),
    )
    matches = []
    for pattern, color in signal_patterns:
        match = re.search(pattern, text)
        if match:
            matches.append((match.start(), match.end(), color))
    if not matches:
        return None
    return sorted(matches, key=lambda item: item[0])[0]


def _style_technical_paragraph(text: str) -> list[dict]:
    terminal_runs = _style_terminal_sentiment(text)
    if len(terminal_runs) != 3:
        return terminal_runs
    body_text, sentiment_text, suffix = (
        terminal_runs[0][ "text"]["content"],
        terminal_runs[1][ "text"]["content"],
        terminal_runs[2][ "text"]["content"],
    )
    signal = _technical_signal_span(body_text)
    if signal is None:
        return terminal_runs
    start, end, color = signal
    runs = []
    if start:
        runs.append(_run(body_text[:start]))
    runs.append(_run(body_text[start:end], color, True))
    if body_text[end:]:
        runs.append(_run(body_text[end:]))
    runs.append(_run(sentiment_text, terminal_runs[1]["annotations"]["color"], True))
    if suffix:
        runs.append(_run(suffix))
    return runs


def _style_trend(text: str) -> list[dict]:
    prefix, rest = _split_prefix(text, ("趋势确认：", "趋势确认:"))
    if not prefix:
        return [_run(text)]
    color = _color_for_text(rest)
    return [_run(prefix), _run(rest, color, True)]


def _style_support_pressure(text: str) -> list[dict]:
    support_label, rest = _split_prefix(text, ("日内支撑：", "日内支撑:"))
    pressure_pos = rest.find("日内压力")
    if not support_label or pressure_pos < 0:
        return [_run(text)]
    before_pressure = rest[:pressure_pos]
    pressure_text = rest[pressure_pos:]
    separator_match = re.search(r"[\s\u3000]*$", before_pressure)
    separator = separator_match.group(0) if separator_match else ""
    support_value = before_pressure[: len(before_pressure) - len(separator)]
    pressure_label, pressure_value = _split_prefix(
        pressure_text,
        ("日内压力：", "日内压力:"),
    )
    return [
        _run(support_label, bold=True),
        _run(support_value, "green", True),
        _run(separator, bold=True),
        _run(pressure_label, bold=True),
        _run(pressure_value, "red", True),
    ]


def _style_entry(text: str) -> list[dict]:
    directional_prefixes = {
        "低多：": "green",
        "低多:": "green",
        "反弹多：": "green",
        "反弹多:": "green",
        "高多：": "green",
        "高多:": "green",
        "做多：": "green",
        "做多:": "green",
        "反弹空：": "red",
        "反弹空:": "red",
        "高空：": "red",
        "高空:": "red",
        "低空：": "red",
        "低空:": "red",
        "做空：": "red",
        "做空:": "red",
    }
    for prefix, color in directional_prefixes.items():
        if text.startswith(prefix):
            return [_run(prefix, color, True), _run(text[len(prefix) :], bold=True)]
    return [_run(text, bold=True)]


def _style_by_index(index: int, text: str) -> list[dict] | None:
    if index == 1:
        return _style_cannot_do(text)
    if index == 2:
        return _style_fundamental(text)
    if index == 3:
        return [_run(text)]
    if index == 4:
        return [_run(text)]
    if index == 5:
        return [_run(text, bold=True)]
    if index == 6:
        return _style_interpretation(text)
    if index == 7:
        return [_run(text)]
    if index in (8, 9):
        return _style_technical_paragraph(text)
    if index == 10:
        return _style_trend(text)
    if index == 11:
        return _style_support_pressure(text)
    if index == 12:
        return [_run(text)]
    if index == 13:
        return [_run(text, "yellow", True)]
    if index == 15:
        return [_run(text)]
    if index == 16:
        return _style_entry(text)
    if index == 17:
        return [_run(text, "green", True)]
    if index == 18:
        return [_run(text, "red", True)]
    if index == 19:
        return [_run(text)]
    if index in (20, 21):
        return [_run(text, bold=True)]
    if index in (22, 23):
        return [_run(text, "purple", True)]
    if index == 24:
        return [_run(text)]
    return None


def _text_blocks(blocks: list[dict]) -> list[dict]:
    return [block for block in blocks if block.get("type") != "image"]


def _run_signature(runs: list[dict]) -> list[tuple[str, str, bool]]:
    signature: list[tuple[str, str, bool]] = []
    for item in runs:
        text = item.get("plain_text")
        if text is None:
            text_body = item.get("text")
            text = text_body.get("content", "") if isinstance(text_body, dict) else ""
        annotations = item.get("annotations") or {}
        color = annotations.get("color", "default")
        bold = bool(annotations.get("bold", False))
        if not text:
            continue
        if signature and signature[-1][1:] == (color, bold):
            prev_text, _, _ = signature[-1]
            signature[-1] = (prev_text + text, color, bold)
        else:
            signature.append((str(text), color, bold))
    return signature


def expected_signature_for_block(
    index: int, block: dict, *, visual_v3: bool = False
) -> list[tuple[str, str, bool]]:
    text = _plain(block)
    style_index = VISUAL_V3_TO_LEGACY_STYLE_INDEX.get(index) if visual_v3 else index
    runs = _style_by_index(style_index, text) if style_index is not None else [_run(text)]
    if runs is None:
        block_type = block.get("type")
        body = block.get(block_type)
        if not isinstance(body, dict):
            return []
        return _run_signature(body.get("rich_text", []))
    return _run_signature(runs)


def actual_signature_for_block(block: dict) -> list[tuple[str, str, bool]]:
    block_type = block.get("type")
    body = block.get(block_type)
    if not isinstance(body, dict):
        return []
    return _run_signature(body.get("rich_text", []))


def style_daily_payload_children(children: list[dict]) -> dict:
    """Mutate daily payload children to the canonical run-level color template."""
    text_blocks = _text_blocks(children)
    actual_types = tuple(block.get("type") for block in text_blocks)
    if actual_types not in DAILY_TEXT_BLOCK_TYPE_SEQUENCES:
        raise ValueError("daily color template requires the frozen daily block sequence")
    visual_v3 = actual_types in {
        DAILY_VISUAL_PAYLOAD_TYPES_31,
        DAILY_VISUAL_PAYLOAD_TYPES_32,
    }
    changed = 0
    checked = 0
    for index, block in enumerate(text_blocks):
        style_index = VISUAL_V3_TO_LEGACY_STYLE_INDEX.get(index) if visual_v3 else index
        runs = _style_by_index(style_index, _plain(block)) if style_index is not None else [_run(_plain(block))]
        if runs is None:
            continue
        checked += 1
        before = actual_signature_for_block(block)
        _set_runs(block, runs)
        after = actual_signature_for_block(block)
        if before != after:
            changed += 1
    return {
        "status": "passed",
        "template": "daily-visual-colors-v3" if visual_v3 else "daily-gold-run-colors-v1",
        "checked_blocks": checked,
        "changed_blocks": changed,
    }


def style_published_daily_blocks(blocks: list[dict]) -> dict:
    """Mutate live Notion blocks fetched from a page, skipping inserted images."""
    return style_daily_payload_children(_text_blocks(blocks))


def audit_daily_blocks(blocks: list[dict]) -> tuple[list[dict], dict]:
    """Return (violations, summary) for a daily page/payload color template."""
    text_blocks = _text_blocks(blocks)
    actual_types = tuple(block.get("type") for block in text_blocks)
    if actual_types not in DAILY_TEXT_BLOCK_TYPE_SEQUENCES:
        return [
            {
                "block": 0,
                "reason": "block_type_sequence",
                "expected": [
                    list(DAILY_TEXT_BLOCK_TYPES_25),
                    list(DAILY_TEXT_BLOCK_TYPES_26),
                ],
                "actual": list(actual_types),
            }
        ], {
            "status": "failed",
            "template": "daily-gold-run-colors-v1",
            "checked_blocks": 0,
        }
    visual_v3 = actual_types in {
        DAILY_VISUAL_PAYLOAD_TYPES_31,
        DAILY_VISUAL_PAYLOAD_TYPES_32,
    }
    template = "daily-visual-colors-v3" if visual_v3 else "daily-gold-run-colors-v1"
    violations = []
    checked = 0
    for index, block in enumerate(text_blocks):
        style_index = VISUAL_V3_TO_LEGACY_STYLE_INDEX.get(index) if visual_v3 else index
        runs = _style_by_index(style_index, _plain(block)) if style_index is not None else [_run(_plain(block))]
        if runs is None:
            continue
        checked += 1
        expected = expected_signature_for_block(index, block, visual_v3=visual_v3)
        actual = actual_signature_for_block(block)
        if actual != expected:
            violations.append(
                {
                    "block": index + 1,
                    "type": block.get("type"),
                    "text_prefix": _plain(block)[:36],
                    "expected": expected,
                    "actual": actual,
                }
            )
    return violations, {
        "status": "passed" if not violations else "failed",
        "template": template,
        "checked_blocks": checked,
        "violation_count": len(violations),
    }


def styled_copy(children: list[dict]) -> list[dict]:
    result = deepcopy(children)
    style_daily_payload_children(result)
    return result
