# -*- coding: utf-8 -*-
# 生成 BlockBeats 风格快讯卡 PNG（基本面配图）2026-06-07 早间
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
    "2026-06-07_1_geo.png", "09:06", "地缘·中东", ACCENT,
    "美伊战争满 100 天，中东战火小规模重燃、停火脆弱",
    "美伊战争今日进入爆发后第 100 天，和谈陷入僵局，特朗普为谈判设定 60 天期限并要求伊朗迅速回应。中东战火小规模重燃：伊朗称再袭美军第五舰队重要设施、革命卫队对 4 艘未经许可穿越霍尔木兹海峡的油轮开火；以军称打击黎巴嫩南部约 150 处真主党目标、两名士兵阵亡（停火以来以方阵亡升至 16 人）。Polymarket「6 月底前达成永久和平」概率仅 16%、7 月底 28%。",
)
make_card(
    "2026-06-07_2_risk.png", "09:56", "风险·传染", ACCENT,
    "海力士周一面临约 200 万股强制卖压，加密恐慌指数 12「极度恐慌」",
    "研究员 degentrading 指出，港股杠杆基金「南方两倍做多海力士（7709.HK）」因上周韩股 SK 海力士大跌，需在周一开盘强制卖出约 200 万股，相当于当日正常成交量的 40%，且 gamma 效应越跌越卖、或引发连锁反应，大胆预测 EWY（韩国 ETF）或从 175 跌至 145 美元——半导体板块极度看空、传统市场 risk-off 传染。同期加密恐慌与贪婪指数今报 12（昨日亦 12），市场持续处于「极度恐慌」。",
)
make_card(
    "2026-06-07_3_whale.png", "10:18", "盘面·抄底", ACCENT_G,
    "巨鲸 24h 囤 1723 枚 BTC，以太坊 OG 1563 美元抄底 35723 枚 ETH",
    "据链上监测，某巨鲸近 24 小时囤积约 1723 枚比特币（约 1.0558 亿美元）；一周前以约 2040 美元均价卖出 6 万枚 ETH 的以太坊 OG 巨鲸再次入场，过去两天以平均 1563 美元买入 35723 枚 ETH 回补。BitMine 董事长 Tom Lee 称当前美股牛市依然稳固。HTX 行情显示比特币回升突破 61,000 美元，24 小时跌幅收窄至 0.53%——极度恐慌中现巨鲸抄底、价格企稳回升。",
)
print("DONE")
