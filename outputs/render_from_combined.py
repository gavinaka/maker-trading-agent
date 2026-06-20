# -*- coding: utf-8 -*-
"""
render_from_combined.py — 【POC · 2026-06-20 O3 本地干跑】
从单一数据源 outputs/<date>_<slot>_combined.md 生成日报 docx，
消除"combined / docx脚本 / push脚本 三处手打同一正文"的重复总结与三处分叉返工
（证据：context_log #45 F段 SMA20 错误曾需 combined/Notion/docx 三处同改）。

状态（诚实标注·勿误用）：
  ✅ docx 路径 = 本地干跑已验证（正文 100% 来自 combined·配色复用 report_colors 权威·无双源）
  ⏳ Notion 推送路径 = 待线上回归（需 $env:NOTION_TOKEN + 门①金标逐块比对）·本文件不含
  ⛔ 尚未接入 daily-report SOP —— 人工出稿仍走现有手打脚本；待 Notion 路径线上回归通过再切换。

用法： py render_from_combined.py <combined_md_path> [out_docx_path]
配色权威：复用 report_colors.SENTIMENT / expected_color（不另造色表·不双源漂移）。
"""
import sys, os, re
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_colors as rc  # 单一配色权威

# Notion 色名 → docx RGB（与现有手打脚本同值，统一来源）
DOCX_RGB = {
    "red": RGBColor(0xC0, 0x00, 0x00), "green": RGBColor(0x1E, 0x7A, 0x32),
    "yellow": RGBColor(0xB0, 0x60, 0x00), "purple": RGBColor(0x6A, 0x00, 0x99),
}
HEADING_BLUE = RGBColor(0x1F, 0x49, 0x7D)
SENT_WORDS = sorted(rc.SENTIMENT.keys(), key=len, reverse=True)  # 长词优先(中性偏空 在 中性 之前)
LABELS = ("不能做", "基本面", "技术面", "盘口（合约）", "解读", "盘面", "日线级别",
          "小时级别", "趋势确认", "日内支撑", "日内压力", "策略", "BTC（策略）",
          "观望理由", "触发门槛", "核心", "情形一", "情形二")


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


def emit_paragraph(doc, text, size=10.5):
    """把一行 combined 文本拆成带色 run 写入一个段落(标签加粗+情绪词上色)。"""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    idx = 0
    m = re.match(r"^(" + "|".join(map(re.escape, LABELS)) + r")(：|:)?", text)
    if m:
        r = p.add_run(m.group(0)); setfont(r, bold=True); idx = m.end()
    rest = text[idx:]
    for tok in re.split("(" + "|".join(map(re.escape, SENT_WORDS)) + ")", rest):
        if not tok:
            continue
        col = color_for(tok) if tok in rc.SENTIMENT else None
        r = p.add_run(tok); setfont(r, bold=bool(col), color=col)
    return p


def render(combined_path, out_path):
    with open(combined_path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    doc = Document()
    st = doc.styles['Normal']
    st.font.name = 'Microsoft YaHei'
    st.font.size = Pt(10.5)
    st._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

    base = os.path.basename(combined_path).replace("_combined.md", "")
    hp = doc.add_paragraph(); hr = hp.add_run(f"{base} 日报（render_from_combined·POC）")
    setfont(hr, size=15, bold=True, color=HEADING_BLUE)

    colored = 0
    for ln in lines:
        s = ln.rstrip()
        if not s:
            continue
        if s.startswith("> "):                       # 作者自查 → 小号灰注
            emit_paragraph(doc, s[2:], size=9)
        elif s.startswith("### "):                    # 子标题
            p = doc.add_paragraph(); r = p.add_run(s[4:]); setfont(r, size=12, bold=True, color=HEADING_BLUE)
        elif s.startswith("## "):                     # 段标题(①②③)
            p = doc.add_paragraph(); r = p.add_run(s[3:]); setfont(r, size=13, bold=True, color=HEADING_BLUE)
        elif s.startswith("- "):                      # ③后附/情形条目
            emit_paragraph(doc, s[2:])
        else:
            emit_paragraph(doc, s)

    # 统计上色 run 数(验证用)
    for p in doc.paragraphs:
        for r in p.runs:
            if r.font.color and r.font.color.rgb in DOCX_RGB.values():
                colored += 1

    doc.save(out_path)
    return len(doc.paragraphs), colored


if __name__ == "__main__":
    cm = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else cm.replace("_combined.md", "_render.docx")
    n, c = render(cm, out)
    print(f"SAVED {out}  paragraphs={n}  colored_runs={c}")
