# -*- coding: utf-8 -*-
"""
BlockBeats 快讯卡 · 唯一权威渲染器（对齐用户手工报告格式 2026-06-21）
============================================================
用户手工格式 = BlockBeats（律动）夜间真卡：
  · 深蓝黑背景（非白底·非左色条）
  · 顶行：时间(橙金加粗) + 两空格 + 标题(白色加粗)，同一行内自然换行
  · 正文：浅灰，按 \n 保留段落空行
  · 无右上 Tier pill、无单独「BlockBeats 快讯」meta 行（正文自带「BlockBeats 消息」）
所有每日脚本（_make_blockbeats_cards_{date}.py）一律 import 本模块的 make_card，
禁各自重画样式 —— 改格式只改这一处。
"""
import os
import re
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), "blockbeats")
os.makedirs(OUT, exist_ok=True)

F  = r"C:\Windows\Fonts\msyh.ttc"     # 微软雅黑 常规
FB = r"C:\Windows\Fonts\msyhbd.ttc"   # 微软雅黑 加粗

# ---- 手工格式取色（BlockBeats 夜间底）----
W        = 820
PAD      = 34
BG       = (18, 25, 38)      # 深蓝黑背景
C_TIME   = (240, 173, 78)    # 时间 橙金
C_TITLE  = (236, 240, 246)   # 标题 近白
C_BODY   = (150, 161, 175)   # 正文 浅灰

f_title = ImageFont.truetype(FB, 25)
f_body  = ImageFont.truetype(F, 21)

LH_TITLE = 36   # 标题行高
LH_BODY  = 33   # 正文行高
GAP_PARA = 13   # 段落间距
GAP_T2B  = 20   # 标题到正文间距


def _wrap_colored(draw, runs, font, maxw):
    """按字符换行，保留每字符颜色。runs=[(text,color),...]。返回 [[(ch,color),...],...]。"""
    lines, cur, w = [], [], 0
    for text, color in runs:
        for ch in text:
            if ch == "\n":
                lines.append(cur); cur, w = [], 0; continue
            cw = draw.textlength(ch, font=font)
            if w + cw > maxw and cur:
                lines.append(cur); cur, w = [], 0
            cur.append((ch, color)); w += cw
    if cur:
        lines.append(cur)
    return lines


def _draw_line(draw, x, y, line, font):
    """画一行带颜色字符；连续同色合并绘制。"""
    if not line:
        return
    seg, seg_color = line[0][0], line[0][1]
    for ch, color in line[1:]:
        if color == seg_color:
            seg += ch
        else:
            draw.text((x, y), seg, font=font, fill=seg_color)
            x += draw.textlength(seg, font=font)
            seg, seg_color = ch, color
    draw.text((x, y), seg, font=font, fill=seg_color)


def make_card(fname, time, title, body, *, output_dir=None, quiet=False, **_ignore):
    """生成一张夜间风格快讯卡。**_ignore 吞掉历史 tag/tag_color 参数以兼容旧调用。"""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.png", str(fname)):
        raise ValueError(f"invalid BlockBeats card filename: {fname}")
    inner = W - 2 * PAD
    tmp = Image.new("RGB", (W, 4000), BG)
    d = ImageDraw.Draw(tmp)

    title_runs = [(time, C_TIME), ("  ", C_TITLE), (title, C_TITLE)]
    title_lines = _wrap_colored(d, title_runs, f_title, inner)

    # 正文按 \n 切段，逐段换行，段间留空
    body_paras = body.split("\n")
    body_blocks = [_wrap_colored(d, [(p, C_BODY)], f_body, inner) for p in body_paras]

    # 量高
    H = PAD
    H += len(title_lines) * LH_TITLE
    H += GAP_T2B
    for i, blk in enumerate(body_blocks):
        H += len(blk) * LH_BODY
        if i != len(body_blocks) - 1:
            H += GAP_PARA
    H += PAD

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    y = PAD
    for ln in title_lines:
        _draw_line(d, PAD, y, ln, f_title); y += LH_TITLE
    y += GAP_T2B
    for i, blk in enumerate(body_blocks):
        for ln in blk:
            _draw_line(d, PAD, y, ln, f_body); y += LH_BODY
        if i != len(body_blocks) - 1:
            y += GAP_PARA

    destination = os.fspath(output_dir) if output_dir is not None else OUT
    os.makedirs(destination, exist_ok=True)
    p = os.path.join(destination, fname)
    img.save(p)
    if not quiet:
        print("SAVED", p, img.size)
    return p
