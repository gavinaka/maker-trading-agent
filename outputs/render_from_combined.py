# -*- coding: utf-8 -*-
"""Render a combined Markdown daily report into a clean DOCX.

The combined Markdown file is the single content source.  This renderer:
- converts Markdown headings to real Word heading styles;
- converts ``-`` items to real Word list paragraphs;
- converts ``**bold**`` and inline-code markers to formatted runs;
- reuses ``report_colors`` as the sole sentiment-color authority; and
- never exposes generator/debug labels in the document title.

Usage: py render_from_combined.py <combined_md_path> --date YYYY-MM-DD --slot SLOT
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_colors as rc  # 单一配色权威
from runtime.state_store import atomic_json_write
from runtime.usage_logger import append_usage

# Notion 色名 → docx RGB（与现有手打脚本同值，统一来源）
DOCX_RGB = {
    "red": RGBColor(0xC0, 0x00, 0x00), "green": RGBColor(0x1E, 0x7A, 0x32),
    "yellow": RGBColor(0xB0, 0x60, 0x00), "purple": RGBColor(0x6A, 0x00, 0x99),
}
HEADING_BLUE = RGBColor(0x1F, 0x49, 0x7D)
SUBTITLE_GRAY = RGBColor(0x66, 0x66, 0x66)
SENT_WORDS = sorted(rc.SENTIMENT.keys(), key=len, reverse=True)  # 长词优先(中性偏空 在 中性 之前)
LABELS = ("不能做", "基本面", "技术面", "盘口（合约）", "解读", "盘面", "日线级别",
          "小时级别", "趋势确认", "日内支撑", "日内压力", "策略", "BTC（策略）",
          "观望理由", "触发门槛", "核心", "情形一", "情形二")
INLINE_MARKUP = re.compile(r"(\*\*.*?\*\*|`[^`]*`)")
SLOT_CN = {"morning": "早间", "midday": "午间", "evening": "晚间"}
TITLE_FORBIDDEN = re.compile(
    r"(?i)(?:\.md\b|_combined\b|_render\b|\bmorning\b|\bmidday\b|"
    r"\bevening\b|\breport\b|\bv\d+\b|\bpoc\b|\bdebug\b|\btest\b)"
)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_docx_path(trading_date, slot, root=ROOT):
    return Path(root) / "outputs" / f"{trading_date}_{slot}_render.docx"


def render_manifest_path(trading_date, slot, root=ROOT):
    return Path(root) / "runtime_state" / trading_date / f"render_{slot}.json"


def _load_object(path):
    if not Path(path).is_file():
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _date_matches_title(title, trading_date):
    year, month, day = (int(part) for part in trading_date.split("-"))
    patterns = {
        f"{year:04d}-{month:02d}-{day:02d}",
        f"{year:04d}.{month}.{day}",
        f"{year:04d}/{month}/{day}",
        f"{year:04d}年{month}月{day}日",
    }
    return any(value in title for value in patterns)


def preflight(lines, trading_date, slot):
    """Resolve a safe title and block known render-loop markers before DOCX."""
    if slot not in SLOT_CN:
        raise ValueError(f"unsupported slot: {slot}")
    lone_markers = [
        index
        for index, line in enumerate(lines, 1)
        if line.strip() == ">"
    ]
    if lone_markers:
        raise ValueError(f"lone blockquote marker at line(s): {lone_markers}")
    headings = [
        plain_markdown(line[2:].strip())
        for line in lines
        if line.startswith("# ")
    ]
    if len(headings) > 1:
        raise ValueError("combined report contains multiple H1 titles")
    title = headings[0] if headings else f"{trading_date} {SLOT_CN[slot]}日报"
    if not _date_matches_title(title, trading_date):
        raise ValueError(f"title date does not match {trading_date}: {title}")
    forbidden = TITLE_FORBIDDEN.search(title)
    if forbidden:
        raise ValueError(f"forbidden generator/debug marker in title: {forbidden.group(0)}")
    if SLOT_CN[slot] not in title or "日报" not in title:
        raise ValueError(f"title does not match {slot}: {title}")
    return title


def renderer_sha256():
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name("report_colors.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def setfont(run, size=10.5, bold=False, color=None):
    run.font.name = 'Microsoft YaHei'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color


def color_for(word):
    c = rc.expected_color(word)
    return DOCX_RGB.get(c) if c else None


def plain_markdown(text):
    """Remove supported inline Markdown markers without changing content."""
    return re.sub(r"\*\*(.*?)\*\*", r"\1", text).replace("`", "")


def _emit_colored_text(paragraph, text, size, force_bold=False, code=False):
    for tok in re.split(
        "(" + "|".join(map(re.escape, SENT_WORDS)) + ")",
        text,
    ):
        if not tok:
            continue
        col = color_for(tok) if tok in rc.SENTIMENT else None
        run = paragraph.add_run(tok)
        setfont(run, size=size, bold=force_bold or bool(col), color=col)
        if code:
            run.font.name = "Consolas"


def emit_paragraph(doc, text, size=10.5, style=None):
    """Write one Markdown line as formatted Word runs."""
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_after = Pt(2)
    idx = 0
    m = re.match(r"^(" + "|".join(map(re.escape, LABELS)) + r")(：|:)?", text)
    if m:
        r = p.add_run(m.group(0))
        setfont(r, size=size, bold=True)
        idx = m.end()
    rest = text[idx:]
    cursor = 0
    for markup in INLINE_MARKUP.finditer(rest):
        if markup.start() > cursor:
            _emit_colored_text(p, rest[cursor:markup.start()], size)
        token = markup.group(0)
        if token.startswith("**"):
            _emit_colored_text(p, token[2:-2], size, force_bold=True)
        else:
            _emit_colored_text(p, token[1:-1], size, code=True)
        cursor = markup.end()
    if cursor < len(rest):
        _emit_colored_text(p, rest[cursor:], size)
    return p


def render(combined_path, out_path, *, source_title=None):
    with open(combined_path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    doc = Document()
    st = doc.styles['Normal']
    st.font.name = 'Microsoft YaHei'
    st.font.size = Pt(10.5)
    st._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    base = os.path.basename(combined_path).replace("_combined.md", "")
    display_base = (
        base.replace("_evening", " 晚间")
        .replace("_morning", " 早间")
        .replace("_midday", " 午间")
    )
    source_title = source_title or next(
        (
            plain_markdown(line[2:].strip())
            for line in lines
            if line.startswith("# ")
        ),
        f"{display_base}日报",
    )
    title_main = source_title
    title_detail = ""
    if "（" in source_title and source_title.endswith("）"):
        title_main, detail = source_title.split("（", 1)
        title_detail = "（" + detail

    hp = doc.add_paragraph()
    hp.paragraph_format.space_after = Pt(3 if title_detail else 10)
    hr = hp.add_run(title_main.strip())
    setfont(hr, size=15, bold=True, color=HEADING_BLUE)
    if title_detail:
        subtitle = doc.add_paragraph()
        subtitle.paragraph_format.space_after = Pt(10)
        sr = subtitle.add_run(title_detail)
        setfont(sr, size=10.5, color=SUBTITLE_GRAY)

    colored = 0
    for ln in lines:
        s = ln.rstrip()
        if not s:
            continue
        if s == ">":                                  # 合法 quote 段内空行
            continue
        if s.startswith("# "):
            continue
        if s.startswith("> "):                       # 作者自查 → 小号注释
            emit_paragraph(doc, s[2:], size=9)
        elif s.startswith("### "):                    # 子标题
            p = doc.add_paragraph(style="Heading 2")
            r = p.add_run(plain_markdown(s[4:]))
            setfont(r, size=12, bold=True, color=HEADING_BLUE)
        elif s.startswith("## "):                     # 段标题(①②③)
            p = doc.add_paragraph(style="Heading 1")
            r = p.add_run(plain_markdown(s[3:]))
            setfont(r, size=13, bold=True, color=HEADING_BLUE)
        elif re.match(r"^\s*-\s+", s):                # ③后附/情形条目
            item = re.sub(r"^\s*-\s+", "", s)
            emit_paragraph(doc, item, style="List Bullet")
        else:
            emit_paragraph(doc, s)

    # 统计上色 run 数(验证用)
    for p in doc.paragraphs:
        for r in p.runs:
            if r.font.color and r.font.color.rgb in DOCX_RGB.values():
                colored += 1

    doc.save(out_path)
    return len(doc.paragraphs), colored


def render_canonical(combined_path, trading_date, slot, *, root=ROOT):
    root = Path(root).resolve()
    source = Path(combined_path).resolve()
    lines = source.read_text(encoding="utf-8").splitlines()
    title = preflight(lines, trading_date, slot)
    target = canonical_docx_path(trading_date, slot, root).resolve()
    manifest_path = render_manifest_path(trading_date, slot, root)
    duplicates = [
        path
        for path in target.parent.glob(f"{trading_date}*.docx")
        if path.resolve() != target
        and (
            f"_{slot}" in path.stem.lower()
            or SLOT_CN[slot] in path.stem
        )
    ]
    if duplicates:
        raise ValueError(
            "non-canonical DOCX artifacts exist for this report: "
            + ", ".join(path.name for path in duplicates)
        )

    source_hash = sha256_file(source)
    renderer_hash = renderer_sha256()
    existing = _load_object(manifest_path) or {}
    key = hashlib.sha256(
        f"{trading_date}:{slot}:{source_hash}:{renderer_hash}".encode("ascii")
    ).hexdigest()
    if (
        existing.get("status") == "success"
        and existing.get("source_sha256") == source_hash
        and existing.get("renderer_sha256") == renderer_hash
        and target.is_file()
        and existing.get("docx_sha256") == sha256_file(target)
    ):
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="render_docx",
            status="success",
            event_id=f"{key}:render:cache",
            retries=max(int(existing.get("attempts", 1)) - 1, 0),
            details={
                "cache_hit": True,
                "attempt": existing.get("attempts", 1),
                "backend": "python-docx",
                "input_sha256": source_hash,
                "renderer_sha256": renderer_hash,
                "output_sha256": existing["docx_sha256"],
                "docx_path": str(target),
            },
            root=root,
        )
        result = dict(existing)
        result["cache_hit"] = True
        return result

    attempts = int(existing.get("attempts", 0))
    if attempts >= 2:
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="render_docx",
            status="blocked",
            event_id=f"{key}:render:attempt-limit",
            retries=1,
            details={
                "cache_hit": False,
                "attempt": attempts,
                "backend": "python-docx",
                "input_sha256": source_hash,
                "renderer_sha256": renderer_hash,
                "failure_reason": "render attempt limit reached; third attempt forbidden",
            },
            root=root,
        )
        raise RuntimeError(
            "render attempt limit reached (2); third attempt is forbidden"
        )
    attempt = attempts + 1
    started = time.perf_counter()
    temporary = target.with_name(f".{target.name}.attempt-{attempt}.tmp.docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        paragraph_count, colored_runs = render(
            source,
            temporary,
            source_title=title,
        )
        os.replace(temporary, target)
        docx_hash = sha256_file(target)
        payload = {
            "schema_version": "1.0",
            "status": "success",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": trading_date,
            "slot": slot,
            "attempts": attempt,
            "cache_hit": False,
            "backend": "python-docx",
            "source_path": str(source),
            "source_sha256": source_hash,
            "renderer_sha256": renderer_hash,
            "resolved_title": title,
            "docx_path": str(target),
            "docx_sha256": docx_hash,
            "paragraph_count": paragraph_count,
            "colored_runs": colored_runs,
        }
        atomic_json_write(manifest_path, payload)
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="render_docx",
            status="success",
            event_id=f"{key}:render:{attempt}",
            duration_ms=round((time.perf_counter() - started) * 1000),
            retries=attempt - 1,
            details={
                "cache_hit": False,
                "attempt": attempt,
                "backend": "python-docx",
                "input_sha256": source_hash,
                "renderer_sha256": renderer_hash,
                "output_sha256": docx_hash,
                "docx_path": str(target),
            },
            root=root,
        )
        return payload
    except BaseException as exc:
        temporary.unlink(missing_ok=True)
        failure = {
            "schema_version": "1.0",
            "status": "failed",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": trading_date,
            "slot": slot,
            "attempts": attempt,
            "source_path": str(source),
            "source_sha256": source_hash,
            "renderer_sha256": renderer_hash,
            "docx_path": str(target),
            "failure_reason": str(exc),
        }
        atomic_json_write(manifest_path, failure)
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="render_docx",
            status="failed",
            event_id=f"{key}:render:{attempt}:failed",
            duration_ms=round((time.perf_counter() - started) * 1000),
            retries=attempt - 1,
            details={
                "cache_hit": False,
                "attempt": attempt,
                "backend": "python-docx",
                "input_sha256": source_hash,
                "renderer_sha256": renderer_hash,
                "failure_reason": str(exc),
            },
            root=root,
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("combined", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=tuple(SLOT_CN))
    args = parser.parse_args()
    result = render_canonical(args.combined, args.date, args.slot)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
