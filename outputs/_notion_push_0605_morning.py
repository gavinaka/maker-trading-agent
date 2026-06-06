# -*- coding: utf-8 -*-
# 早间日报 -> Notion，严格 100% 对齐 2026.6.2 早间金标：block 类型 + 逐 run 字体颜色（按情绪词确定性着色）
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR = "red", "yellow", "green", "purple"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.5"
TITLE = "🌅 2026.6.5 早间日报（11:00 评分点）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "🌅 2026.6.5")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote
    quote("门禁 6/5＝可交易（身体正常·平静·节奏顺·连续止损0·结果依赖无），但备注「工作团建（宿醉）身体比较疲惫」；心力最新 6/4＝专注 0/消耗 10/收缩机制（环境干扰·团建）。综合＝门禁未关闭（非硬停）但叠加团建宿醉疲惫＋昨日收缩机制 → 降频谨慎日、挂单门槛从严。总评分 72（盘口50+盘面22）≥70 → 必挂 Maker 单于高质量边缘。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做空", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("中性偏空", YEL, True),
        R("（价格续破位——BTC跌破6.2万（24h-3.73%）、ETH跌破1700，过去24h全网爆仓7.92亿、多单爆仓6.11亿=多头继续被爆；ZEC因Orchard伪造漏洞24h暴跌39.5%山寨黑天鹅、BIT关联巨鲸12万ETH多头浮亏超6900万=risk-off。对冲项（企稳信号初现）=美BTC现货ETF昨日净流入320万（IBIT+4770万）终结连续13日流出、ETH现货ETF净流入1930万终结连续17日流出=机构连续撤离首次反转；24h爆仓7.92亿较前两日9.84亿/17亿明显缩量。今晚20:30非农，预期新增仅约8.5万明显低于前值=偏鸽，但通胀粘性下联储或鹰派双向）", YEL, True),
        R("价格部分兑现", GRN, True)]),

    # 7 技术面 heading_3
    h3("技术面："),
    # 8 盘口（合约）paragraph
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold)
    para([R("CVD下降　价格下降　资金费率下降（接近0值）　持仓横盘", None, True)]),
    # 10 解读 heading_3
    h3([R("解读："), R("中性偏空", YEL, True),
        R("（价格与CVD同步创新低=空头趋势确认、非背离、下跌中继；但资费自0.0092大幅回落至0.0021并偶现负值=本轮单边下跌中多头首次接近投降，叠加爆仓缩量+ETF转净流入，超卖反弹/反包风险显著升；OI横盘57.2K自低点回升=多空换手未单边离场。空头单边延续但临近超卖末段）")]),

    # 11 盘面 paragraph
    para("盘面："),
    # 12 日线级别 paragraph
    para([R("日线级别　"), R("6/5缩量192M（vs 6/4 513M）巨幅下跌后卖压衰减，价61,470破上升通道下轨+0.618斐波、跌穿日线POC 67,000", RED, True),
          R("，SMA200 74,885远在上方、全空排列　"), R("利空", RED, True)]),
    # 13 小时级别 paragraph
    para([R("小时级别　"), R("1H/4H全空、价砸穿所有均线、SMA20（1H 63,352/4H 65,690）向下并转头顶压力", RED, True),
          R("，15m跌破用户手绘支撑(6.4) 62,000-62,500、贴61.5k运行　"), R("利空", RED, True)]),

    # 14 趋势确认 heading_3
    h3([R("趋势确认："), R("空头趋势（单边·瀑布破位下行·临近超卖末段）", RED, True)]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("59,600-60,100", GRN, True),
        R("　　日内压力：", None, True), R("62,400-63,000", RED, True)]),

    # 16 策略 heading_3
    h3("策略："),
    # 17 策略正文 paragraph (yellow bold)
    para([R("中线主账户（6/3接飞刀低多@67,000已止损出局、本轮中线计划再度终结）现金观望、0%仓。状态机＝不新增防守层；空头单边砸至61.5k、ETF虽现单日小额转流入但未确认持续、今晚非农未落地＝企稳证据不足，禁左侧接飞刀（连环左侧抄底教训），待ETF持续净流入+CVD背离+资费转负capitulation共振企稳再评估重建。", YEL, True)]),

    # 18 divider
    divider(),
    # 19 Maker heading_2
    h2("BTC（策略）：执行概率 60%（已执行 0%）　胜率 60%"),
    # 20 反弹空 paragraph (bold)
    para([R("反弹空：62,400-63,000（跌破的用户支撑(6.4) 62,000-62,500转阻力 + 逼近1H SMA20 63,352 = 最近且≥60%可达的高质量反抽阻力带，现价61,470需+1.5~2.5%）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上", None, True)]),
    # 21 止盈 paragraph (green bold)
    para([R("止盈：59,450（TP1·+2.5R）减仓50% ／ 58,300（TP2·+3.4R）", GRN, True)]),
    # 22 止损 paragraph (red bold)
    para([R("止损：站稳 64,000 上方（回补破位+站上1H SMA20 63,352并进压力(6.4)=反抽空失效）= 结构失效离场（单笔约1.6%，<3%）", RED, True)]),
    # 23 防守计划 heading_3
    h3("防守计划："),
    # 24 第一层 paragraph (bold)
    para([R("第一层：价格首次触及 60,750（1.5R）以下→设4小时级别K线极点为止损且取消所有加仓", None, True)]),
    # 25 第二层 paragraph (bold)
    para([R("第二层：价格触及 59,450（2.5R）以下→减仓50%同时设保本损", None, True)]),
    # 26 注意事项 paragraph (purple bold)
    para([R("注意事项：若价格优先触及 59,400（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)]),
    # 27 取消价≠止损 paragraph (purple bold)
    para([R("⚠️ 取消价(59,400·成交前撤单) ≠ 止损(64,000·成交后离场)", PUR, True)]),
    # 28 持仓校准 paragraph
    para("持仓校准：主账户6/3中线低多@67,000已止损出局、现无持仓；Maker 最新6/4做多800刀挂单未开仓（属用户手写未开仓计划、独立成稿不引用其方向）、当前 Maker 无实际持仓。两账户均空仓。"),
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
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-05_1_btc.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-05_2_etf.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-05_3_nfp.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
