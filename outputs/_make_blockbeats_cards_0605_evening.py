# -*- coding: utf-8 -*-
# 生成 BlockBeats 风格快讯卡 PNG（基本面配图）2026-06-05 晚间
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
    "2026-06-05e_1_nfp.png", "20:30", "宏观·非农", ACCENT,
    "「沃什时代」首份非农出炉：就业人口远超预期",
    "美国 5 月季调后非农就业人口 17.2 万人，预期仅 8.5 万人，前值由 11.5 万人上修至 17.9 万人；5 月失业率 4.3%、预期与前值均 4.30%。就业远超预期，市场定价美联储进一步收紧货币政策——美元指数 DXY 短线走高 15 点至 99.36，现货黄金短线下挫近 20 美元，比特币现报 61,801 美元、24h 跌约 3%，标普 500、纳指期货跌至盘中低点。",
)
make_card(
    "2026-06-05e_2_hike.png", "20:36", "宏观·加息", ACCENT,
    "非农彻底推翻降息理由，美联储 12 月加息概率升至 63%",
    "机构分析师 Anstey 评非农：这无疑将彻底推翻美联储未来几个月降息的任何理由。美国利率期货数据显示，美联储 12 月加息概率自之前的 48% 上升至 63%；市场目前定价美联储将在明年 1 月加息，非农公布前预期时间点为明年 3 月。非农公布后，6 月 17 日 FOMC 会议「不变」概率升至 98.4%、降息概率降至 1.6%。",
)
make_card(
    "2026-06-05e_3_whale.png", "20:44", "链上·抄底", ACCENT_G,
    "某巨鲸今日累计自 Aave 借 7642 万美元买入 44,845 枚 ETH",
    "据余烬监测，某巨鲸今日已累计从 Aave 借款 7642 万 USDT、杠杆买入 44,845 枚 ETH，均价 1704 美元；20 分钟前继续借 3200 万 USDT 买入 18,994.5 枚。此外 F2Pool 联创王纯半小时前自 Binance 提出 9719 枚 ETH（价值 1616 万美元）疑似抄底、灰度 Hyperliquid ETF 上线首日净流入 470 万——大资金在 risk-off 中逆势吸筹 ETH。",
)
print("DONE")
