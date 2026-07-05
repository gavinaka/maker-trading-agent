# -*- coding: utf-8 -*-
"""Hard gates for daily-report human-facing structure.

The trading date may be ISO internally, but human-facing report titles and
date pages must use the historical ``YYYY.M.D`` format.  This module also
keeps the Word draft skeleton stable so free-form Markdown cannot silently
change the rendered document shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

STRICT_FROM = date(2026, 7, 5)
SLOT_CN = {
    "morning": "早间",
    "midday": "午间",
    "evening": "晚间",
}
REQUIRED_SOURCES = (
    "BlockBeats",
    "Coinglass",
    "Exocharts",
    "FedWatch",
    "Farside",
    "TradingView",
)
REQUIRED_H2_ORDER = ("① 正文", "不能做", "② Maker 计划", "③ 后附")
REQUIRED_H3_IN_BODY = ("基本面", "技术面", "解读", "趋势确认", "日内支撑/压力", "策略")
MAX_H3_HEADING_CHARS = 70
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TITLE_MARKER_RE = re.compile(
    r"(?i)(?:\.md\b|_combined\b|_render\b|\bmorning\b|\bmidday\b|"
    r"\bevening\b|\breport\b|\bv\d+\b|\bpoc\b|\bdebug\b|\btest\b)"
)


@dataclass(frozen=True)
class StructureIssue:
    line: int
    code: str
    message: str

    def format(self) -> str:
        loc = f"L{self.line}" if self.line else "document"
        return f"{loc} {self.code}: {self.message}"


def parse_iso_date(trading_date: str) -> date:
    year, month, day = (int(part) for part in trading_date.split("-"))
    return date(year, month, day)


def strict_contract_active(trading_date: str) -> bool:
    return parse_iso_date(trading_date) >= STRICT_FROM


def display_date(trading_date: str) -> str:
    parsed = parse_iso_date(trading_date)
    return f"{parsed.year}.{parsed.month}.{parsed.day}"


def expected_title(trading_date: str, slot: str) -> str:
    if slot not in SLOT_CN:
        raise ValueError(f"unsupported slot: {slot}")
    return f"{display_date(trading_date)} {SLOT_CN[slot]}日报"


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    out = []
    for lineno, line in enumerate(lines, 1):
        match = _HEADING_RE.match(line)
        if match:
            out.append((lineno, len(match.group(1)), match.group(2).strip()))
    return out


def _h2_prefix_positions(headings: list[tuple[int, int, str]]) -> dict[str, tuple[int, str]]:
    positions: dict[str, tuple[int, str]] = {}
    for lineno, level, text in headings:
        if level != 2:
            continue
        for prefix in REQUIRED_H2_ORDER:
            if text.startswith(prefix) and prefix not in positions:
                positions[prefix] = (lineno, text)
    return positions


def _section_text(lines: list[str], start_marker: str) -> str:
    start = None
    for index, line in enumerate(lines):
        if line.startswith(start_marker):
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def _section_between_h2(lines: list[str], start_prefix: str, end_prefix: str) -> str:
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"## {start_prefix}"):
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith(f"## {end_prefix}"):
            end = index
            break
    return "\n".join(lines[start:end])


def validate_combined_structure(
    lines: list[str],
    trading_date: str,
    slot: str,
) -> tuple[str, list[StructureIssue]]:
    """Return normalized title and hard structure issues for a combined report."""
    issues: list[StructureIssue] = []
    title = expected_title(trading_date, slot)
    headings = _headings(lines)
    h1 = [(line, text) for line, level, text in headings if level == 1]
    strict = strict_contract_active(trading_date)

    for lineno, text in h1:
        marker = _TITLE_MARKER_RE.search(text)
        if marker:
            issues.append(
                StructureIssue(
                    lineno,
                    "title.generator_marker",
                    f"forbidden generator/debug marker in H1: {marker.group(0)}",
                )
            )

    if strict and len(h1) != 1:
        issues.append(StructureIssue(0, "title.count", f"expected exactly one H1, got {len(h1)}"))
    elif not strict and len(h1) > 1:
        issues.append(StructureIssue(0, "title.count", f"expected at most one H1, got {len(h1)}"))
    elif strict and h1[0][1] != title:
        issues.append(
            StructureIssue(
                h1[0][0],
                "title.display_date",
                f"human-facing title must be '{title}', got '{h1[0][1]}'",
            )
        )

    for lineno, line in enumerate(lines, 1):
        if line.strip() == ">":
            issues.append(StructureIssue(lineno, "markdown.lone_quote", "lone '>' is forbidden"))
        if line.strip() == "---":
            issues.append(
                StructureIssue(
                    lineno,
                    "markdown.raw_hr",
                    "raw '---' renders as stray text; use a real section boundary",
                )
            )

    if not strict:
        return title, issues

    positions = _h2_prefix_positions(headings)
    for marker in REQUIRED_H2_ORDER:
        if marker not in positions:
            issues.append(StructureIssue(0, "skeleton.h2_missing", f"missing H2 '{marker}'"))
    if all(marker in positions for marker in REQUIRED_H2_ORDER):
        ordered = [positions[marker][0] for marker in REQUIRED_H2_ORDER]
        if ordered != sorted(ordered):
            issues.append(
                StructureIssue(
                    0,
                    "skeleton.h2_order",
                    "H2 order must be ①正文 -> 不能做 -> ②Maker计划 -> ③后附",
                )
            )
    if "不能做" in positions and positions["不能做"][1] != "不能做":
        issues.append(
            StructureIssue(
                positions["不能做"][0],
                "skeleton.cannot_do_heading",
                "H2 must be exactly '不能做'; put the action in the following paragraph",
            )
        )

    body = _section_between_h2(lines, "① 正文", "② Maker")
    for marker in REQUIRED_H3_IN_BODY:
        if not re.search(rf"^###\s+{re.escape(marker)}(?:$|[：:/])", body, re.M):
            issues.append(StructureIssue(0, "skeleton.h3_missing", f"missing body H3 '{marker}'"))

    for lineno, level, text in headings:
        if level == 3 and len(text) > MAX_H3_HEADING_CHARS:
            issues.append(
                StructureIssue(
                    lineno,
                    "skeleton.long_heading",
                    f"H3 is {len(text)} chars; keep evidence/detail in body text",
                )
            )

    full_text = "\n".join(lines)
    for match in re.finditer(r"五源", full_text):
        line = full_text[: match.start()].count("\n") + 1
        issues.append(StructureIssue(line, "sources.legacy_five", "reports are six-source after 2026-07-05"))

    appendix = _section_text(lines, "## ③")
    for source in REQUIRED_SOURCES:
        if source not in appendix:
            issues.append(
                StructureIssue(0, "sources.six_missing", f"③ 后附 must include six-source evidence: {source}")
            )

    return title, issues


def assert_combined_structure(lines: list[str], trading_date: str, slot: str) -> str:
    title, issues = validate_combined_structure(lines, trading_date, slot)
    if issues:
        raise ValueError("report structure gate failed: " + "; ".join(issue.format() for issue in issues))
    return title


def assert_rendered_docx_structure(docx_path: str | Path, trading_date: str, slot: str) -> None:
    """Validate rendered Word draft skeleton before it can become canonical."""
    from docx import Document

    doc = Document(str(docx_path))
    paragraphs = [paragraph for paragraph in doc.paragraphs if paragraph.text.strip()]
    title = expected_title(trading_date, slot)
    issues: list[StructureIssue] = []
    if not paragraphs:
        issues.append(StructureIssue(0, "docx.empty", "DOCX contains no non-empty paragraphs"))
    elif paragraphs[0].text.strip() != title:
        issues.append(
            StructureIssue(
                1,
                "docx.title",
                f"first paragraph must be '{title}', got '{paragraphs[0].text.strip()}'",
            )
        )
    for index, paragraph in enumerate(paragraphs, 1):
        text = paragraph.text.strip()
        if text == "---":
            issues.append(StructureIssue(index, "docx.raw_hr", "stray '---' rendered into Word"))
    if not strict_contract_active(trading_date):
        if issues:
            raise ValueError("rendered DOCX structure gate failed: " + "; ".join(issue.format() for issue in issues))
        return
    headings = [
        paragraph.text.strip()
        for paragraph in paragraphs
        if paragraph.style is not None and paragraph.style.name.startswith("Heading")
    ]
    for marker in REQUIRED_H2_ORDER:
        if not any(text.startswith(marker) for text in headings):
            issues.append(StructureIssue(0, "docx.heading_missing", f"rendered DOCX missing heading '{marker}'"))
    if issues:
        raise ValueError("rendered DOCX structure gate failed: " + "; ".join(issue.format() for issue in issues))
