# -*- coding: utf-8 -*-
# 早间日报 -> Notion，严格 100% 对齐 2026.6.2 早间金标：block 类型 + 逐 run 字体颜色（按情绪词确定性着色）
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR = "red", "yellow", "green", "purple"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.4"
TITLE = "🌅 2026.6.4 早间日报（11:00 评分点）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "🌅 2026.6.4")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote
    quote("门禁 6/4＝可交易（今日行仅填情绪平静度＝平静，无「不可交易/收缩机制」标记 → 按可交易处理）；心力最新 6/3＝专注 7/消耗 3/无异常。总评分 71（盘口50+盘面21）≥70 → 必挂 Maker 单于高质量边缘。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做空", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("中性偏空", YEL, True),
        R("（周四开门黑、BTC跌破6.5万跌势延续，过去24h全网爆仓9.84亿、多单爆仓8.04亿=多头继续被血洗；美股三大股指收跌、微软英伟达跌逾3%=risk-off传导，日韩股市低开；美股资金分化270亿流入科技、其余板块流出40亿=币市持续失血。对冲项=地缘转缓和：特朗普称对伊谈判「非常顺利」协议本周末或达成、伊朗四阶段计划首阶段全面停火，但今晨仍称打击美军指挥舰、缓和未落实）", YEL, True),
        R("价格部分兑现", GRN, True)]),

    # 7 技术面 heading_3
    h3("技术面："),
    # 8 盘口（合约）paragraph
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold)
    para([R("CVD下降　价格下降　资金费率下降（为正值）　持仓横盘", None, True)]),
    # 10 解读 heading_3
    h3([R("解读："), R("利空", RED, True),
        R("（"), R("价格与CVD同步创新低=空头趋势确认、非背离", RED, True),
        R("，资费自0.0093回落但仍为正=多头未投降、下行空间未尽；OI横盘58.5K=多头止损被新空替代。隔夜瀑布resume，6/3的超卖反抽thesis已失效、再创新低）")]),

    # 11 盘面 paragraph
    para("盘面："),
    # 12 日线级别 paragraph
    para([R("日线级别　"), R("巨阴-3.96%破上升通道下轨+0.618斐波，跌穿日线POC 67,000", RED, True),
          R("，SMA200 74,885远在上方、全空排列　"), R("利空", RED, True)]),
    # 13 小时级别 paragraph
    para([R("小时级别　"), R("1H/4H全空排列、SMA20（66,335/69,406）向下并转头顶压力", RED, True),
          R("，15m跌破用户手绘支撑(6.3) 65,300-65,800　"), R("利空", RED, True)]),

    # 14 趋势确认 heading_3
    h3([R("趋势确认："), R("空头趋势（单边·瀑布破位下行）", RED, True)]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("63,500-64,000", GRN, True),
        R("　　日内压力：", None, True), R("65,300-65,800", RED, True)]),

    # 16 策略 heading_3
    h3("策略："),
    # 17 策略正文 paragraph (yellow bold)
    para([R("中线主账户（6/3新开中线低多@67,000·50%仓·5x·700刀·左侧Taker·1:2.5·长持）隔夜随破位已止损出局、现无持仓（Notion状态=已平仓、按计划执行、未情绪化）。状态机＝现金观望、0%仓；空头单边未止跌前不新增中线多单、禁左侧接飞刀，待资费转负+CVD背离+超卖capitulation信号共振企稳再评估重建。", YEL, True)]),

    # 18 divider
    divider(),
    # 19 Maker heading_2
    h2("BTC（策略）：执行概率 62%（已执行 0%）　胜率 62%"),
    # 20 反弹空 paragraph (bold)
    para([R("反弹空：65,300-65,800（跌破的用户支撑(6.3)转阻力 + 1H SMA20 66,335 下沿 = 最近且≥60%可达的高质量反抽阻力带，现价64,114需+1.8~2.6%）　持仓 700 刀　Binance　左侧　盈亏比 1:2.5 以上", None, True)]),
    # 21 止盈 paragraph (green bold)
    para([R("止盈：63,400（TP1·+2.5R）减仓50% ／ 62,700（TP2·+3.4R）", GRN, True)]),
    # 22 止损 paragraph (red bold)
    para([R("止损：站稳 66,400 上方（有效突破1H SMA20 66,335+前结构=反抽空失效）= 结构失效离场（单笔约1.3%，<3%）", RED, True)]),
    # 23 防守计划 heading_3
    h3("防守计划："),
    # 24 第一层 paragraph (bold)
    para([R("第一层：价格首次触及 64,300（1.5R）以下→设4小时级别低点为止损且取消所有加仓", None, True)]),
    # 25 第二层 paragraph (bold)
    para([R("第二层：价格触及 63,400（2.5R）以下→减仓50%同时设保本损", None, True)]),
    # 26 注意事项 paragraph (purple bold)
    para([R("注意事项：若价格优先触及 63,400（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)]),
    # 27 取消价≠止损 paragraph (purple bold)
    para([R("⚠️ 取消价(63,400·成交前撤单) ≠ 止损(66,400·成交后离场)", PUR, True)]),
    # 28 持仓校准 paragraph
    para("持仓校准：主账户6/3中线低多@67,000隔夜已止损出局、现无持仓；Maker 6/3做多800刀已TP1止盈出局（盈$10）、当前 Maker 无实际持仓。"),
]

pid = create_page(date_page, TITLE, blocks)
print("MORNING PAGE:", pid)

ch = get_children(pid)
after = None
for b in ch:
    if b["type"] == "heading_3":
        txt = "".join(x.get("plain_text", "") for x in b["heading_3"]["rich_text"])
        if txt.startswith("基本面"):
            after = b["id"]; break
imgs = [
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-04_1_btc.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-04_2_equity.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-04_3_iran.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
