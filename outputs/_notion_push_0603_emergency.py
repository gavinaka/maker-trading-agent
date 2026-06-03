# -*- coding: utf-8 -*-
# 应急盘中日报 -> Notion，按早间链路骨架，100% 对齐 2026.6.2 早间金标：block 类型 + 逐 run 字体颜色全对齐
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR = "red", "yellow", "green", "purple"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.3"
TITLE = "⚡ 2026.6.3 应急盘中日报（13:25 UTC+8）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "⚡ 2026.6.3")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote (default)
    quote("应急盘中报告（13:25 UTC+8）：门禁 6/3＝可交易（身体正常/情绪平静/节奏顺）；连续止损数 2、逼近≥3锁定线→降频谨慎，未触发停牌；心力正常无收缩。现价 67,050（自 77,000 四日瀑布、扫 65,800 低点后反弹）。总评分 71（盘口50+盘面21）≥70 → 必挂 Maker 反弹空于高质量边缘。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做多", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("中性偏空", RED, True),
        R("（美国现货 BTC ETF 6/2 净流出 5.19 亿美元、较前日 4.84 亿扩大·IBIT 占 75%，叠加 ETH ETF 流出 9,020 万、合计 6.09 亿，机构连续多日撤离；过去 24 小时全网爆仓 17.03 亿、主爆多单 15.33 亿、空单仅 1.7 亿＝多头遭血洗；链上派发延续——Garrett Jin 高位转 13.5 亿美元 ETH 精准逃顶、USDH 部署者解质押 101 万枚 HYPE 出售、某 23 连胜巨鲸 20 倍杠杆新开 4,803 万美元 BTC 空单@66,128；美股 AI 概念 risk-on——黄仁勋喊单 MRVL、英伟达组合 NBIS 年内 +485.7%——未传导币市）", YEL, True),
        R("价格部分兑现", GRN, True),
        R("（BTC 自 77,000 暴跌至 65,800 低点、现回升至 67,050、24 小时跌幅收窄至 5.19%）", RED, True)]),

    # 7 技术面 heading_3 (default)
    h3("技术面："),
    # 8 盘口（合约）paragraph (default)
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold, no color)
    para([R("CVD下降　价格上升　资金费率上升（为正值）　持仓横盘", None, True)]),
    # 10 解读 heading_3
    h3([R("解读："), R("中性偏空", YEL, True),
        R("（"), R("1H CVD 创新低 -28,582 但价格反弹＝看跌背离·反弹无量诱多", RED, True),
        R("，资金费率持续正 0.0066-0.0081＝残余多头未投降、属下跌中继；唯 6/3 日线 footprint 缩量 153M（vs 6/2 天量 678M）+ Delta 转正 +1.5M + 砸至 POC 66,282 现锤子吸筹 + 24 小时爆仓主爆多＝超卖反弹有基础，双向博弈，故净中性偏空、反弹大概率被卖）")]),

    # 11 盘面 paragraph (default)
    para("盘面："),
    # 12 日线级别 paragraph
    para([R("日线级别　"), R("暴跌破上升平行通道下轨 +0.618 斐波", RED, True),
          R("，全空头排列、SMA20/200 远在上方，POC 逐级下移至 66,282　"), R("利空", RED, True)]),
    # 13 小时级别 paragraph
    para([R("小时级别　"), R("1H 扫 65,975 低点后反弹、1H SMA20 67,498 转头顶反抽阻力", RED, True),
          R("，4H 全空头排列、前 POC 67,000 附近现价争夺，CVD↓　"), R("利空", RED, True)]),

    # 14 趋势确认 heading_3
    h3([R("趋势确认："), R("空头趋势（单边破位下行 · 盘中超卖反弹）", RED, True)]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("65,300-65,800", GRN, True),
        R("　　日内压力：", None, True), R("67,500-68,200", RED, True)]),

    # 16 策略 heading_3 (default)
    h3("策略："),
    # 17 策略正文 paragraph (yellow bold whole)
    para([R("中线主账户今日新开低多@67,000（50% 仓·5x·$700·1:2.5·左侧 Taker·长持）、持仓中，防守第一层 68,500（设日线低点止损 + 取消加仓）/ 第二层 70,500（保本损）均未激活。系统独立判断：基本面中性偏空（ETF 连续流出 + 机构撤离 + 链上派发）+ 盘面破位下行（破通道下轨 +0.618 + 全空排列）→ 中线大方向仍偏空，此为逆势接飞刀（位置与中线方向背离、风险偏高）；状态机＝守纪律死守防守层，价跌破 4H/日线低点 65,800 即应止损砍短、不补仓加码、盈利放满，价回升至 68,500 方激活第一层浮盈防守。连续止损 2 笔逼近门禁锁定线，严控敞口、降频。", YEL, True)]),

    # 18 divider
    divider(),
    # 19 Maker heading_2 (default)
    h2("BTC（策略）：执行概率 62%（已执行 0%）　胜率 60%"),
    # 20 反弹空 paragraph (bold whole)
    para([R("反弹空：67,500-67,900（1H SMA20 67,498 下沿 + 用户压力 6.3 区 67,800 中部＝最近且 ≥60% 可达的高质量反抽阻力带，现价 67,050 仅需 +0.7~1.3%、反弹进行中）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上", None, True)]),
    # 21 止盈 paragraph (green bold)
    para([R("止盈：65,800（TP1·支撑 6.3 上沿·≈+2.4R）减仓 50% ／ 65,300（TP2·支撑 6.3 下沿·≈+3R）", GRN, True)]),
    # 22 止损 paragraph (red bold)
    para([R("止损：站稳 68,500 上方（有效突破压力 6.3 + 1H SMA20＝反抽空失效）＝结构失效离场（单笔约 1.2%，<3%）", RED, True)]),
    # 23 防守计划 heading_3 (default)
    h3("防守计划："),
    # 24 第一层 paragraph (bold)
    para([R("第一层：价格首次触及 66,500（1.5R）以下→设 4 小时级别低点 65,800 为止损且取消所有加仓", None, True)]),
    # 25 第二层 paragraph (bold)
    para([R("第二层：价格触及 65,800（≈2.4R）以下→减仓 50%、设保本损", None, True)]),
    # 26 注意事项 paragraph (purple bold)
    para([R("注意事项：若价格优先触及 65,800（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)]),
    # 27 ⚠️ 取消价≠止损 paragraph (purple bold)
    para([R("⚠️ 取消价(65,800·成交前撤单) ≠ 止损(68,500·成交后离场)", PUR, True)]),
    # 28 持仓校准 paragraph (default)
    para("持仓校准：主账户今日新开中线低多@67,000（50%·700刀·持仓中）；Maker 今日新开做多 800 刀（左侧·已击中50%·已触第一层防守66,700）·持仓中。本应急稿系统独立判方向为反弹空（与实际多仓相反），仅作独立信号输出、不构成对已持仓的操作建议。"),
]

pid = create_page(date_page, TITLE, blocks)
print("EMERGENCY PAGE:", pid)

ch = get_children(pid)
after = None
for b in ch:
    if b["type"] == "heading_3":
        txt = "".join(x.get("plain_text", "") for x in b["heading_3"]["rich_text"])
        if txt.startswith("基本面"):
            after = b["id"]; break
imgs = [
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03e_1_etf.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03e_2_liq.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03e_3_whale.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
