# -*- coding: utf-8 -*-
# 生成 BlockBeats 风格快讯卡 PNG（基本面配图）
import os
from PIL import Image, ImageDraw, ImageFont

OUT = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats"
os.makedirs(OUT, exist_ok=True)
F = r"C:\Windows\Fonts\msyh.ttc"
FB = r"C:\Windows\Fonts\msyhbd.ttc"

W = 760
PAD = 28
BG = (255, 255, 255)
ACCENT = (220, 38, 38)       # 红 = Tier1 利空/地缘
ACCENT_B = (37, 99, 235)     # 蓝 = 行业/中性
INK = (17, 24, 39)
SUB = (107, 114, 128)

f_meta = ImageFont.truetype(F, 18)
f_title = ImageFont.truetype(FB, 26)
f_body = ImageFont.truetype(F, 21)
f_tag = ImageFont.truetype(FB, 17)

def wrap(draw, text, font, maxw):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        t = cur + ch
        if draw.textlength(t, font=font) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = ch
    if cur: lines.append(cur)
    return lines

def make_card(fname, time, tag, tag_color, title, body):
    tmp = Image.new("RGB", (W, 2000), BG); d = ImageDraw.Draw(tmp)
    inner = W - 2 * PAD
    title_lines = wrap(d, title, f_title, inner)
    body_lines = wrap(d, body, f_body, inner)
    y = PAD
    y += 30           # meta row
    y += 14
    y += len(title_lines) * 36
    y += 16
    y += len(body_lines) * 32
    y += PAD
    H = y
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img)
    # left accent bar
    d.rectangle([0, 0, 6, H], fill=tag_color)
    yy = PAD
    # meta: time + source + tag
    d.text((PAD, yy), time, font=f_meta, fill=SUB)
    tw = d.textlength("BlockBeats 快讯", font=f_meta)
    d.text((PAD + 78, yy), "BlockBeats 快讯", font=f_meta, fill=SUB)
    # tag pill (right)
    pad_x = 12
    pw = d.textlength(tag, font=f_tag) + pad_x * 2
    d.rounded_rectangle([W - PAD - pw, yy - 2, W - PAD, yy + 26], radius=6, fill=tag_color)
    d.text((W - PAD - pw + pad_x, yy + 1), tag, font=f_tag, fill=(255, 255, 255))
    yy += 30 + 14
    for ln in title_lines:
        d.text((PAD, yy), ln, font=f_title, fill=INK); yy += 36
    yy += 16
    for ln in body_lines:
        d.text((PAD, yy), ln, font=f_body, fill=(55, 65, 81)); yy += 32
    p = os.path.join(OUT, fname)
    img.save(p)
    print("SAVED", p, img.size)

make_card(
    "2026-06-03_1_fed.png", "08:18", "宏观·鹰派", ACCENT,
    "美联储主席沃什任命两名保守派顾问，推动改革议程",
    "沃什于履新初期任命保罗·温弗里和丹尼尔·海尔两名保守派政策专家担任临时顾问。温弗里曾参与撰写保守派蓝图「2025 项目」美联储章节，主张取消美联储「充分就业与物价稳定」双重使命、仅保留控制通胀目标，并推动缩减资产负债表、限制「最后贷款人」职能。沃什称将领导一个「以改革为导向」的美联储。",
)
make_card(
    "2026-06-03_2_iran.png", "08:13", "地缘·趋紧", ACCENT,
    "美国务卿强硬表态：不以解除对伊制裁换取霍尔木兹海峡通航",
    "国务卿鲁比奥在国会听证会上表示，特朗普政府不会以解除对伊朗制裁作为交换条件换取霍尔木兹海峡恢复通航，任何制裁松动都须以伊朗放弃核计划为前提。伊朗冲突已进入第四个月，国会两党持续质疑战争策略。（较 6/2「和谈一周内或达成」明显转回强硬）",
)
make_card(
    "2026-06-03_3_longs.png", "08:21", "行业·多头被套", ACCENT_B,
    "Garrett Jin 所持 1,268 枚 BTC 多单浮亏已超 1,150 万美元",
    "据 OnchainLens 监测，随市场下跌，「BTC OG 内幕巨鲸」代理人 Garrett Jin 持有的 1,268 枚 BTC、5 倍杠杆多头仓位账面浮亏已超 1,150 万美元。同期「麻吉」无惧清算加仓做多、近一周亏损超 100 万美元——下跌中多头巨鲸普遍被套、尚未投降。",
)
print("DONE")
