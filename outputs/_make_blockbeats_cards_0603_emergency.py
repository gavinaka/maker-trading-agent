# -*- coding: utf-8 -*-
# 生成应急盘中报告 BlockBeats 风格快讯卡 PNG（基本面配图·3 张）
import os
from PIL import Image, ImageDraw, ImageFont

OUT = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats"
os.makedirs(OUT, exist_ok=True)
F = r"C:\Windows\Fonts\msyh.ttc"
FB = r"C:\Windows\Fonts\msyhbd.ttc"

W = 760
PAD = 28
BG = (255, 255, 255)
ACCENT = (220, 38, 38)       # 红 = 利空/资金撤离
ACCENT_B = (37, 99, 235)     # 蓝 = 行业/链上
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
    "2026-06-03e_1_etf.png", "11:53", "资金·机构撤离", ACCENT,
    "美国现货比特币 ETF 单日净流出 5.19 亿美元，机构资金持续撤离",
    "据 Farside Investors 数据，美国现货比特币 ETF 于 6 月 2 日录得 5.191 亿美元净流出，较前一交易日 4.838 亿净流出进一步扩大，其中贝莱德 IBIT 单日流出 3.886 亿、占整体约 75%。同日现货以太坊 ETF 净流出 9,020 万美元，两者合计净流出约 6.09 亿。比特币 ETF 已连续多个交易日大额流出，反映机构风险偏好仍偏谨慎。",
)
make_card(
    "2026-06-03e_2_liq.png", "11:45", "行业·多头血洗", ACCENT,
    "过去 24 小时全网爆仓升至 17.03 亿美元，主爆多单 15.33 亿",
    "据 Coinglass 数据，过去 24 小时全网爆仓金额升至 17.03 亿美元，其中多单爆仓 15.33 亿美元、空单爆仓仅 1.7 亿美元。BTC 自约 77,000 四日瀑布式破位下行，多头杠杆遭集中清洗，主动卖压与去杠杆同步加剧。",
)
make_card(
    "2026-06-03e_3_whale.png", "12:15", "链上·巨鲸做空", ACCENT_B,
    "某 23 连胜巨鲸开立 4,803 万美元 BTC 空仓，系今日最大建仓",
    "据 Coinbob 监控，今日 Hyperliquid 上建仓规模最大的 BTC 头寸来自地址 0x50b：1 小时前以 20 倍杠杆做空 724.1 枚 BTC，持仓价值约 4,803 万美元，建仓均价 66,128，清算价 71,715，目前小幅浮亏。该地址近期 BTC 日内短线已连续 23 次盈利、周胜率 92%、近 7 日累计盈利 257 万美元。",
)
print("DONE")
