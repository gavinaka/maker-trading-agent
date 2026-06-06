# -*- coding: utf-8 -*-
# 晚间日报 -> Notion 🌙 子页，100% 对齐 2026.6.2 晚间金标：29 块 block 类型 + 逐 run 字体颜色 + 3 张快讯卡
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR, ORG = "red", "yellow", "green", "purple", "orange"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.5"
TITLE = "🌙 2026.6.5 晚间日报（20:00 评分点）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "🌙 2026.6.5")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote
    quote("评分点 20:00 ｜ 现价 61,950（15m 61,962 / 1H 61,957 / 4H 61,892 / 日线 61,884；Coinglass 61,882）。日内路径：早间 61,470 → 强反抽至高点 63,259（+2.9%·上破 1H SMA20 63,023 后于 63k 被拒）→ NFP 20:30 超预期打回 → 61,950（冲高回落）。门禁 6/5＝开启·可交易（备注「工作团建宿醉身体比较疲惫」）＋心力最新 6/4＝消耗 10·工作团建·有疲惫感·收缩机制＝非硬停、降频谨慎日。总评分 72（盘口50+盘面22）≥70 → 必挂 Maker 反弹空于高质量边缘（只挂边缘左侧、不主动追）。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做空", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("利空", RED, True),
        R("（「沃什时代」首份非农远超预期：美 5 月季调后非农就业 17.2 万人、预期仅 8.5 万、前值由 11.5 万上修至 17.9 万、失业率 4.3% 持平＝就业强劲；分析师称数据彻底推翻美联储未来几月降息理由、联储 12 月加息概率自 48% 骤升至 63%、市场定价美联储明年 1 月加息（原预期 3 月）；美元 DXY 短线 +15 至 99.36、现货黄金挫近 20 美元、美股标普/纳指期货跌至盘中低点＝risk-off；BTC 承压现报 61,801（24h -3%）；ZEC 因无限增发漏洞 24h 暴跌 39.6%＝山寨黑天鹅延续；贝莱德 ETF 向 Coinbase 存入 1,978 BTC＋14,244 ETH＝潜在卖压。对冲（逢低吸筹）：某巨鲸今日累计自 Aave 借 7,642 万买 44,845 ETH（均价 1,704）、F2Pool 王纯提 9,719 ETH 抄底、灰度 Hyperliquid ETF 首日净流入 470 万。Tier1 宏观转鹰主导＝利空）"),
        R("价格部分兑现", GRN, True),
        R("（BTC 自非农前回落约 3% 至 61.8k、美元/加息预期重定价仍在进行）")]),

    # 7 技术面 heading_3
    h3("技术面："),
    # 8 盘口（合约）paragraph
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold, no color)
    para([R("CVD下降　价格冲高回落（日内反抽 63,259 被拒）　资金费率上升（为正值·低位 0.0025）　持仓下降", None, True)]),
    # 10 解读 heading_3 (中性偏空 = yellow·按情绪词规则)
    h3([R("解读："), R("中性偏空", YEL, True),
        R("（日内价格强反抽至 63,259（上破 1H SMA20 63,023）即遭 63k 供给 + NFP 拒绝、冲高回落至 61,950＝反弹失败、卖方守住阻力；1H CVD -36,246K 全程未随价反抽走强、维持近低位＝买盘无量、反抽不被验证；资费自 6/4 偶现负柱回升至 0.0025＝接近 0 的超卖区多头试探未投降；OI 56.5K 自 58K 回落＝去杠杆；6/5 日线 footprint 缩量 168M（vs 6/4 317M·约半）+ Delta 转正 +3.5M（=日内反抽买盘但被阻力吞没）+ POC 下移 61,897＝瀑布末段缩量，但反抽于 63k 被拒 + NFP 宏观转鹰＝净中性偏空、反弹被卖）")]),

    # 11 盘面 paragraph
    para("盘面："),
    # 12 日线级别 paragraph
    para([R("日线级别　多日瀑布破上升平行通道下轨 +0.618 斐波、砸穿 POC 67,000 续创新低 61.9k，SMA20 73,311 远在上方下行、全空头排列；唯 6/5 缩量（168M）+ Delta 转正＝动能衰减　"), R("利空", RED, True)]),
    # 13 小时级别 paragraph
    para([R("小时级别　4H/1H 全空头排列，日内反抽一度上破 1H SMA20 63,023 至 63,259、即被 63k 供给 + NFP 打回收复均线下方、4H SMA20 64,914 下行，CVD 未随反抽走强　"), R("利空", RED, True)]),

    # 14 趋势确认 heading_3
    h3([R("趋势确认："), R("空头趋势", RED, True), R("（单边破位下行 · 日内反抽至 63,259 失败被拒）")]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("59,600-60,000", GRN, True),
        R("　　日内压力：", None, True), R("62,800-63,300", RED, True)]),

    # 16 策略 heading_3
    h3("策略："),
    # 17 策略正文 paragraph (yellow·空仓待机)
    para([R("中线主账户与 Maker 当前均空仓（主账户 6/3 低多@67,000 已止损出局、本轮中线计划终结；Maker 6/4 做多 800 刀挂单未成交＝用户手写未开仓计划、独立稿不引用其方向）＝无在持仓位、无防守层需守。系统独立判断：基本面利空（NFP 17.2 万远超 8.5 万预期＝降息理由被推翻、加息预期骤升、美元走强）+ 盘面空头排列下跌中继 → 中线大方向仍偏空；状态机＝空仓待机，新开中线仓须等高质量反转/确认信号，不在 near lows 追空亦不接飞刀左侧抄底。今日系统晚间盘口独立判向＝反弹空（≥70 必挂·日内 Maker 框架盘口＞盘面＞基本面），与中线（基本面＞盘面＞盘口）分流互不干扰。⚠️ 门禁备注疲惫+心力团建收缩＝降频谨慎日：照 ≥70 必挂但只挂高质量边缘等左侧反应、不主动追价、不加码。", YEL, True)]),

    # 18 divider
    divider(),
    # 19 Maker heading_2
    h2("BTC（策略）：执行概率 62%（已执行 0%）　胜率 60%"),
    # 20 反弹空 paragraph (red lead + default)
    para([R("反弹空：入场 62,500-63,000", RED, True),
          R("（破位的用户支撑 6.4（62,200-62,600）转阻力 + 1H SMA20 63,023 共振、且日内反抽高 63,259 已在此带上方被拒证明为有效供给 = 最近且 ≥60% 可达的高质量反抽空边缘）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上")]),
    # 21 止盈 paragraph (green bold)
    para([R("止盈：59,600（TP1·近 60,000 整数关下沿/日线低点 59,608·≈+2.5R）减仓 50% ／ 58,500（TP2·≈+3.4R）", GRN, True)]),
    # 22 止损 paragraph (red bold)
    para([R("止损：站稳 64,000 上方（有效站上 = 结构反转、反抽空失效）＝结构失效离场（R≈1,250·单笔约 2.0%，<3%）", RED, True)]),
    # 23 防守计划 heading_3
    h3("防守计划："),
    # 24 第一层 paragraph (bold)
    para([R("第一层：价格触及 60,800（1.5R）　设立 4 小时级别高点极点为止损 同时取消所有加仓策略", None, True)]),
    # 25 第二层 paragraph (bold)
    para([R("第二层：价格触及 59,600（2.5R）　减仓 50%、设立保本损", None, True)]),
    # 26 注意事项 paragraph (purple bold)
    para([R("注意事项：若价格（成交前）优先触及 59,400（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)]),
    # 27 ⚠️ 取消价≠止损 paragraph (purple bold)
    para([R("⚠️ 取消价(59,400·成交前撤单) ≠ 止损(64,000·成交后离场)", PUR, True)]),
    # 28 核心 paragraph (default)
    para("核心（开仓理由）：日内强反抽至 63,259（上破 1H SMA20 63,023）即被 63k 供给 + NFP 打回＝反抽失败、阻力带有效，破位支撑 6.4 转阻力 + 1H SMA20 63,023 共振压制＝最近高质量反抽空带；基本面 NFP 超预期宏观转鹰（降息理由推翻、加息预期 48→63%、美元走强）强化空头方向；现价 61,950 距入场区 62,500-63,000 仅 +0.9~1.7%（高质量反抽空边缘，执行概率≈62% 达宪法门槛）；TP1≈+2.5R、R:R 1:2.5。唯缩量+日线 Delta 转正＝瀑布末段量能衰减，只挂边缘左侧等待、价不触及不成交（绝不追价）、降频谨慎不加码。",),
    # 29 持仓校准 paragraph (default)
    para("持仓校准：主账户 6/3 低多@67,000 已止损出局（盈亏 +13·PCT3%）现空仓 0%；Maker 最新 6/4 做多 800 刀状态＝未开仓（挂单未成交·用户手写未开仓计划），当前 Maker 无实际持仓。两账户均空仓。系统独立判晚间方向为反弹空（≥70 必挂），持仓状态仅作事实校准、未参照用户判断。"),
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
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-05e_1_nfp.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-05e_2_hike.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-05e_3_whale.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
