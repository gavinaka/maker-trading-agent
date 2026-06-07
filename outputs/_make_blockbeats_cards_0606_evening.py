# -*- coding: utf-8 -*-
# 生成 BlockBeats 风格快讯卡 PNG（基本面配图）2026-06-06 晚间
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
ACCENT_B = (37, 99, 235)     # 蓝 = 中性/宏观
ACCENT_G = (22, 163, 74)     # 绿 = 利多/企稳
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
    "2026-06-06e_1_macro.png", "22:12", "宏观·强鹰", ACCENT,
    "本周宏观：强劲非农推升加息预期，美股科技单日蒸发超 1 万亿",
    "美国 5 月非农新增 17.2 万人，大幅超出市场预期 8.5 万人，推动重新定价美联储政策路径——12 月加息概率升至 63%，多位美联储官员释放鹰派信号。美元指数重返 100 关口上方，黄金连续第四周下跌，美股科技股周五遭遇重挫，费城半导体指数单日下跌 10%，市值蒸发超 1 万亿美元。日本央行 6 月或加息至 1%（1995 年以来最高，加息概率超 80%）。",
)
make_card(
    "2026-06-06e_2_geo.png", "22:53", "地缘·中东", ACCENT,
    "中东局势升级：伊朗发射导弹、以军空袭黎巴嫩致将军身亡",
    "伊朗当天向科威特和巴林方向发射 7 枚弹道导弹，美军成功拦截其中 6 枚，并击落 4 架伊朗无人机、打击伊朗沿海雷达设施。同日，停火协议签署数日后，以军空袭黎巴嫩南部军车，造成一名准将、一名上尉及一名士兵死亡。特朗普称「伊朗局势进展顺利」，但冲突持续、停火脆弱——中东 risk-off 延续，影响霍尔木兹海峡及伊朗停火谈判。",
)
make_card(
    "2026-06-06e_3_oversold.png", "23:45", "盘面·超卖", ACCENT_G,
    "比特币超卖创 2020 疫情崩盘以来新高，或迎技术性反弹",
    "过去一个月下跌约 30% 后，BTC 日线 RSI 已降至约 15.5，创 2020 年 3 月疫情崩盘以来最低，市场进入极度超卖。历史类似水平（2020 疫情、2026 年 2 月）后曾分别反弹约 50%、30%。目前多头仍守住 6 万美元关键支撑，若有效未来数周或反弹至 20 日 EMA 约 70,650 美元；若跌破 6 万则下探 5 万中段。约 530 万枚长期 BTC 浮亏（高于 FTX 时期），情绪接近恐慌，「底部已经不远」。",
)
print("DONE")
