# -*- coding: utf-8 -*-
# 晚间日报 -> Notion 🌙 子页，100% 对齐 2026.6.2 晚间金标：29 块 block 类型 + 逐 run 字体颜色 + 3 张快讯卡
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR, ORG = "red", "yellow", "green", "purple", "orange"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.3"
TITLE = "🌙 2026.6.3 晚间日报（20:00 评分点）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "🌙 2026.6.3")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote
    quote("评分点 20:00 ｜ 现价 67,250（15m 67,253 / 1H 67,247 / 4H 67,259 / 日线 67,259；Coinglass 67,247；Exo 67,142）。门禁 6/3＝可交易；今日 Maker 做多 800 刀已止盈出局（盈 $10·仅成交 50%）＝连续止损 streak 中断、降频警示解除；心力正常无收缩。总评分 73（盘口50+盘面23）≥70 → 必挂 Maker 反弹空于高质量边缘。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做多", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("中性偏空", ORG, True),
        R("（Strategy 四年来首次出售 32 枚 BTC、打破「只囤不卖」信仰预期（MSTR 罕见抛售付优先股股息·QCP+BiyaPay 双源确认）；现货 BTC ETF 连续 11 日净流出约 35 亿美元、机构持续撤离；克利夫兰联储主席称通胀持续或需重启加息＝联储鹰派、美国强劲就业削弱降息预期；贝莱德向 Coinbase 存入 6,005.46 枚 BTC（4.03 亿·存入交易所＝潜在卖压/分发）；QCP 期权 30 天平值 IV 升至 41.4、风险逆转大幅为负、短期结构倒挂＝防御浓厚（买下行保护非追涨）；一夜超 25 万人爆仓、清算超 16 亿。中性/噪音：摩根大通看好美股盈利「超级周期」（2026 标普+20%）＝risk-on 未传导币市、Arthur Hayes 喊单 WLD+23%、龙虾 meme+31%；地缘特朗普要求以色列对贝鲁特停火＝潜在缓和未定）"),
        R("价格部分兑现", GRN, True),
        R("（BTC 自 77,000 瀑布至 65,000 低点、现回升 67,250、本周累跌约 11.6%；市场为对冲下行而非恐慌离场）")]),

    # 7 技术面 heading_3
    h3("技术面："),
    # 8 盘口（合约）paragraph
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold, no color)
    para([R("CVD下降　价格横盘　资金费率下降（为正值 0.0039）　持仓横盘", None, True)]),
    # 10 解读 heading_3 (label red = 块位置色·非情绪)
    h3([R("解读："), R("中性偏空", RED, True),
        R("（1H CVD 创新低 -27,475 但价格横盘反抽＝看跌背离·反弹乏力无量；资金费率自 0.0100 高位回落至 0.0039＝多头降温但仍正、未投降、属下跌中继；OI 59,161 自 62K 峰回落后横盘＝去杠杆后企稳；唯 6/3 日线 footprint 缩量 229M（vs 6/2 天量 678M）+ Delta 转正 +12M + POC 上移至 66,774 + 一夜爆仓 16 亿近 capitulation＝超卖反抽有基础，双向博弈，故净中性偏空、反弹大概率被卖）")]),

    # 11 盘面 paragraph
    para("盘面："),
    # 12 日线级别 paragraph
    para([R("日线级别　4 日瀑布破上升平行通道下轨 +0.618 斐波、砸至日线 POC 66,774 企稳，缩量反抽（229M vs 678M 天量·无量），SMA20 75,042 远在上方下行、全空头排列　"), R("利空", RED, True)]),
    # 13 小时级别 paragraph
    para([R("小时级别　4H/1H 全空头排列，1H SMA20 67,000-67,500 转头顶压制、4H SMA20 70,707 下行，1H CVD 创新低 -27,475 看跌背离，价横盘反抽贴 SMA20 下方　"), R("利空", RED, True)]),

    # 14 趋势确认 heading_3
    h3([R("趋势确认："), R("空头趋势", RED, True), R("（单边破位下行 · 盘中超卖反抽整理）")]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("65,300-65,800", GRN, True),
        R("　　日内压力：", None, True), R("67,900-68,800", RED, True)]),

    # 16 策略 heading_3
    h3("策略："),
    # 17 策略正文 paragraph (red lead + default rest)
    para([R("中线主账户低多 @67,000（50%底仓·5x·$700·1:2.5·左侧 Taker·接飞刀）今日新开、持仓中，现价 67,250 浮盈微正（约 +0.4%·价格口径）。", RED, True),
          R("防守第一层 68,500（设日线低点止损 + 取消加仓）/ 第二层 70,500（保本损）均未激活。系统独立判断：基本面中性偏空（Strategy 首卖 + ETF 连续 11 日流出 35 亿 + 联储鹰派）+ 盘面空头排列下跌中继 → 中线大方向仍偏空，此为逆势接飞刀（位置与中线方向背离、风险偏高）；状态机＝守纪律死守防守层，价跌破日线低点 65,800 即应止损砍短、不补仓加码、盈利放满，价回升至 68,500 方激活第一层浮盈防守。今日 Maker 做多 800 刀已止盈出局（盈 $10·仅成交 50%）＝连续止损 streak 中断、降频警示解除、门禁可交易。⚠️ 系统晚间盘口独立判向＝反弹空（与主账户低多持仓相反·日内 Maker 框架盘口＞盘面＞基本面），与中线（基本面＞盘面＞盘口）框架分流、互不干扰；本稿方向仅独立信号、不构成对已持仓的操作建议。")]),

    # 18 divider
    divider(),
    # 19 Maker heading_2
    h2("BTC（策略）：执行概率 62%（已执行 0%）　胜率 62%"),
    # 20 反弹空 paragraph (red lead + default)
    para([R("反弹空：入场 67,900-68,200", RED, True),
          R("（用户压力 6.3 下沿 + 4H POC 67,972 共振 = 最近且 ≥60% 可达的高质量反抽空边缘）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上")]),
    # 21 止盈 paragraph (green bold)
    para([R("止盈：66,000（TP1·≈+2.5R）减仓 50% ／ 65,300（TP2·支撑 6.3 下沿·≈+3.4R）", GRN, True)]),
    # 22 止损 paragraph (red bold)
    para([R("止损：站稳 68,800 上方（有效突破压力 6.3 上沿 = 反抽空失效）＝结构失效离场（R≈800·单笔约 1.2%，<3%）", RED, True)]),
    # 23 防守计划 heading_3
    h3("防守计划："),
    # 24 第一层 paragraph (bold)
    para([R("第一层：价格触及 66,800（1.5R）　设立 4 小时级别高点极点为止损 同时取消所有加仓策略", None, True)]),
    # 25 第二层 paragraph (bold)
    para([R("第二层：价格触及 66,000（2.5R）　设立保本损", None, True)]),
    # 26 注意事项 paragraph (purple bold)
    para([R("注意事项：若价格（成交前）优先触及 65,300（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)]),
    # 27 ⚠️ 取消价≠止损 paragraph (purple bold)
    para([R("⚠️ 取消价(65,300·成交前撤单) ≠ 止损(68,800·成交后离场)", PUR, True)]),
    # 28 核心 paragraph (default)
    para("核心（开仓理由）：4 日瀑布破位后超卖反抽至压力 6.3 下沿 + 4H POC + 1H SMA20 共振压制、缩量无量反弹、1h CVD 创新低看跌背离、资费正回落＝多头降温未投降下跌中继；现价 67,250 距入场区 67,900-68,200 仅 +0.6~1.4%（高质量反抽空边缘，执行概率≈62% 达宪法门槛）；TP1≈+2.5R、R:R 1:2.5。挂单于边缘等待，价不触及不成交（绝不追价）。"),
    # 29 持仓校准 paragraph (default)
    para("持仓校准：主账户今日新开中线低多@67,000（50%·700刀·持仓中，防守 68,500/70,500 未激活）；Maker 今日做多 800 刀已止盈出局·盈 $10（PCT 2%·TP1·仅成交 50%），当前 Maker 无实际持仓。系统独立判晚间方向为反弹空（与主账户多仓相反），仅作独立信号输出、不构成对已持仓的操作建议。"),
]

pid = create_page(date_page, TITLE, blocks)
print("EVENING PAGE:", pid)

ch = get_children(pid)
after = None
for b in ch:
    if b["type"] == "heading_3":
        txt = "".join(x.get("plain_text", "") for x in b["heading_3"]["rich_text"])
        if txt.startswith("基本面"):
            after = b["id"]; break
imgs = [
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03ev_1_mstr.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03ev_2_blk.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03ev_3_qcp.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
