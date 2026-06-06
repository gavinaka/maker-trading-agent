# -*- coding: utf-8 -*-
# 生成 BlockBeats 风格快讯卡 PNG（基本面配图）2026-06-04 早间
import os
from PIL import Image, ImageDraw, ImageFont

OUT = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats"
os.makedirs(OUT, exist_ok=True)
F = r"C:\Windows\Fonts\msyh.ttc"
FB = r"C:\Windows\Fonts\msyhbd.ttc"

W = 760
PAD = 28
BG = (255, 255, 255)
ACCENT = (220, 38, 38)       # 红 = 利空/risk-off
ACCENT_B = (37, 99, 235)     # 蓝 = 中性/缓和
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
    y += 30
    y += 14
    y += len(title_lines) * 36
    y += 16
    y += len(body_lines) * 32
    y += PAD
    H = y
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 6, H], fill=tag_color)
    yy = PAD
    d.text((PAD, yy), time, font=f_meta, fill=SUB)
    d.text((PAD + 78, yy), "BlockBeats 快讯", font=f_meta, fill=SUB)
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
    "2026-06-04_1_btc.png", "07:06", "盘面·利空", ACCENT,
    "周四开门黑，比特币跌破 6.5 万美元、跌势延续",
    "据 HTX 行情数据，比特币跌破 6.5 万美元、现报 64,609 美元，24 小时跌幅 2.8%。过去 24 小时全网爆仓 9.84 亿美元，其中多单爆仓 8.04 亿美元、空单爆仓 1.8 亿美元——多头继续遭血洗、清算逼近超卖。",
)
make_card(
    "2026-06-04_2_equity.png", "07:06", "宏观·risk-off", ACCENT,
    "美股三大股指收跌，微软、英伟达均跌逾 3%",
    "据 Bitget 行情数据，美股周三收盘道指跌 1.2%、标普 500 跌 0.7%、纳指跌 0.89%，微软与英伟达均跌逾 3%。同时日韩股市低开（日经 -0.65%、KOSPI -1.94%）。自 3 月 30 日低点以来美股科技 ETF 累计净流入 270 亿美元、其余板块合计流出 40 亿美元，资金持续从币市等资产撤向美股科技。",
)
make_card(
    "2026-06-04_3_iran.png", "01:09", "地缘·缓和", ACCENT_B,
    "伊朗概述与美国达成协议的四阶段计划，首阶段全面停火",
    "据伊朗媒体 Fars News 报道，伊朗方面概述了与美国达成协议的四阶段计划：第一阶段全面停止所有战线军事行动；第二阶段落实霍尔木兹海峡机制、解除封锁与石油制裁、解冻部分资产；第三阶段启动制裁与核问题谈判；第四阶段成立监督委员会。特朗普称与伊朗谈判「非常顺利」、协议或本周末达成（但伊朗今晨仍称打击美军指挥舰，缓和尚未落实）。",
)
print("DONE")
