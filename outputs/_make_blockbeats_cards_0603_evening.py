# -*- coding: utf-8 -*-
# 生成晚间日报 BlockBeats 风格快讯卡 PNG（基本面配图·3 张）
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
    "2026-06-03ev_1_mstr.png", "18:55", "资金·信仰动摇", ACCENT,
    "Strategy 四年来首次出售比特币，打破「只囤不卖」预期",
    "据 QCP Capital 与 BiyaPay 分析，Strategy（MSTR）罕见出售 32 枚 BTC 用于支付优先股股息，虽规模不大，但打破其长期「永不卖出」的市场信仰，引发情绪波动。叠加现货 BTC ETF 已连续 11 日净流出约 35 亿美元、机构持续撤离，比特币本周累计下跌约 11.6%，一夜跌回 6 万美元关口附近，未能重返关键上涨区间。",
)
make_card(
    "2026-06-03ev_2_blk.png", "19:32", "链上·分发卖压", ACCENT_B,
    "贝莱德向 Coinbase 存入 6,005.46 枚比特币，价值 4.03 亿美元",
    "据 OnchainLens 监测，6 月 3 日贝莱德向 Coinbase 存入 6,005.46 枚比特币，价值约 4.0315 亿美元。机构向交易所大额转入通常被视为潜在卖压/分发信号，与现货 ETF 连续净流出相互印证，反映机构端风险偏好仍偏谨慎。",
)
make_card(
    "2026-06-03ev_3_qcp.png", "18:52", "宏观·防御浓厚", ACCENT,
    "QCP：比特币需守 6.7 万，期权风险逆转大幅为负、防御情绪浓厚",
    "QCP Capital 称，比特币需守住 67,000-68,000 美元区间，否则反弹仍显脆弱。期权市场 30 天平值隐含波动率升至 41.4、短期结构倒挂、风险逆转指标大幅为负，市场更倾向购买下行保护而非追涨。宏观上中东冲突推高油价、美国强劲就业削弱降息预期，克利夫兰联储主席称通胀持续或需重启加息；一夜超 25 万人爆仓、清算超 16 亿美元。市场为对冲下行而非恐慌离场。",
)
print("DONE")
