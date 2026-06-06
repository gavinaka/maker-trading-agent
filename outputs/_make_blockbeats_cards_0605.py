# -*- coding: utf-8 -*-
# 生成 BlockBeats 风格快讯卡 PNG（基本面配图）2026-06-05 早间
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
    "2026-06-05_1_btc.png", "14:17", "盘面·利空", ACCENT,
    "比特币跌破 6.2 万美元，以太坊跌破 1700 美元",
    "据 HTX 行情数据，比特币跌破 62,000 美元、24 小时跌幅 3.73%，以太坊跌破 1700 美元、24h 跌 5.2%。过去 24 小时全网爆仓 7.92 亿美元，其中多单爆仓 6.11 亿、空单爆仓 1.81 亿，逾 18.5 万人被爆，最大单笔为 Binance BTCUSDT 1181 万美元——多头继续被爆、清算延续但规模较前两日缩小。",
)
make_card(
    "2026-06-05_2_etf.png", "13:48", "资金·企稳", ACCENT_G,
    "美比特币、以太坊现货 ETF 双双终结连续流出转净流入",
    "据 Farside Investors 监测，昨日美国比特币现货 ETF 净流入 320 万美元，终结连续 13 日流出，其中 IBIT 净流入 4770 万美元；以太坊现货 ETF 净流入 1930 万美元，终结连续 17 日流出，其中 ETHA 净流入 1930 万美元——机构连续撤离首次出现反转，叠加爆仓规模缩量，企稳信号初现。",
)
make_card(
    "2026-06-05_3_nfp.png", "14:29", "宏观·非农", ACCENT_B,
    "「沃什时代」首份非农将于今晚 20:30 公布",
    "美国劳工统计局将于今晚 20:30 公布 5 月非农就业数据。市场普遍预计 5 月新增非农约 8.5 万人、明显低于此前两个月平均约 15 万人，失业率维持 4.3%；高盛预计仅 6 万、安永 5 万、先锋 2 万。若数据大体符合预期，美联储大概率在 6 月 16-17 日会议按兵不动；但通胀仍高，联储或发更鹰派双向声明、强调加息仍是可选工具。",
)
print("DONE")
