# -*- coding: utf-8 -*-
# 晚间日报 6/6（观望样本日）-> Notion 🌙 子页，镜像 2026.6.2 晚间金标 29 块结构；
# Maker 段如实为「观望·不挂单」（不臆造挂单），块类型逐块对齐金标、配色按情绪词唯一规则。
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR, ORG = "red", "yellow", "green", "purple", "orange"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.6"
TITLE = "🌙 2026.6.6 晚间日报（20:00 评分点）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "🌙 2026.6.6")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote
    quote("评分点 20:00 ｜ 现价 60,656（15m 60,656 / 1H 60,689 / 4H 60,684 / 日线收 60,668；Coinglass 60,642；Exo 60,613）。日内路径（6/6·周六）：开 61,056 → 早 03:00 探低 59,500（15m 59,200）→ 反抽至约 62,000（06:00）→ 震荡收敛回落 → 60,668（收·-0.63%），周末缩量横盘、坐 15m 上升趋势线企稳。门禁 6/6＝开启·可交易（节奏顺/连续止损 0/情绪平静/身体正常·无疲惫备注）＝正常可交易日。用户今日个人休息·无盘中交易，本稿为系统独立测试样本。总评分 63（盘口 45＋盘面 18）＜70 门槛 → 观望·不挂单。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做空", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("中性偏空", YEL, True),
        R("（强非农推升加息预期＋中东地缘升级＝利空主导：美 5 月非农 17.2 万远超预期 8.5 万、12 月加息概率升至 63%、美元指数重返 100 上方、黄金连续第四周下跌、费城半导体单日 -10%＝美股科技股单日蒸发超 1 万亿美元、日本央行 6 月或加息至 1%（概率 >80%）；伊朗向科威特/巴林发射 7 枚导弹（美军拦 6）、以军空袭黎巴嫩致一名将军身亡＝停火脆弱、中东 risk-off；Longling Capital 卖出 1 万枚 ETH＋三巨鲸 34.5 万枚 ETH 面临清算（>5.3 亿）＝山寨抛压。对冲（反弹燃料积累）：BTC 日线 RSI 约 15.5＝创 2020 年疫情崩盘以来最低、极度超卖（历史类似位后曾反弹约 50%/30%）、短期持有者已实现盈亏比历史最低、530 万枚长期 BTC 浮亏（高于 FTX 时期）、情绪接近恐慌「底部不远」；多头守住 6 万美元关键支撑；某巨鲸今日 1,633 美元增持 9.33 万 ETH 抄底；Zcash Orchard 漏洞已修复无资金损失。Tier1 宏观强鹰＋地缘升级主导＝利空，唯极度超卖＋守 6 万＝企稳燃料）"),
        R("价格部分兑现", GRN, True),
        R("（BTC 近一月已跌约 30% 至 6.1k 下、宏观重定价大体走完、6 万未破）")]),

    # 7 技术面 heading_3
    h3("技术面："),
    # 8 盘口（合约）paragraph
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold, no color)
    para([R("CVD下降　价格横盘　资金费率横盘（接近0值·0.0010）　持仓下降", None, True)]),
    # 10 解读 heading_3 (中性偏空 = yellow)
    h3([R("解读："), R("中性偏空", YEL, True),
        R("（1H CVD -40,341K 续创新低＝卖压未止，但价格横盘拒随 CVD 续创决定性新低＝看涨背离酝酿；资费 0.0010 接近 0 的超卖区、6/4 附近偶现负柱＝多头接近投降；OI 自 58.5K 回落至 57.0K＝去杠杆出清；6/6 日线 footprint 缩量 230M（vs 6/5 650M·约 1/3）+ Delta -14M（负但幅度全周最小）+ POC 自 59,778 上移至 60,930 + H-L 收窄至 2,047.8＝瀑布末段卖压衰竭横盘；唯 CVD 累积深负（Exo -190M）买方尚未接管＝企稳未确认）")]),

    # 11 盘面 paragraph
    para("盘面："),
    # 12 日线级别 paragraph (中性偏空 yellow 收口)
    para([R("日线级别　多日瀑布破上升平行通道下轨 +0.618 斐波、砸穿 POC 67,000，SMA20 72,431 远在上方下行、全空头排列；唯 6/6 缩量 230M + 振幅骤收 + POC 上移＝动能显著衰减、瀑布转横盘整理　"), R("中性偏空", YEL, True)]),
    # 13 小时级别 paragraph
    para([R("小时级别　1H 价 60,689 贴 SMA20 60,984 下方走平；15m 自 59,200 探低反抽后坐用户手绘上升趋势线（现≈60,400-60,600）企稳收敛；4H SMA20 62,872 向下转阻力、POC 67,000 头顶　"), R("中性偏空", YEL, True)]),

    # 14 趋势确认 heading_3
    h3([R("趋势确认："), R("震荡结构", YEL, True), R("（超卖末段企稳 · 盘整区间）")]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("60,000-60,400", GRN, True),
        R("　　日内压力：", None, True), R("60,900-61,500", RED, True)]),

    # 16 策略 heading_3
    h3("策略："),
    # 17 策略正文 paragraph (yellow·空仓待机)
    para([R("中线主账户与 Maker 当前均空仓（主账户 6/3 低多@67,000 已止损出局、本轮中线计划终结；Maker 6/4 做多 800 刀挂单未成交＝用户手写未开仓计划、独立稿不引用其方向）＝无在持仓位、无防守层需守。系统独立判断：基本面 Tier1 宏观强鹰＋地缘升级仍偏空，盘口卖压衰竭横盘＋极度超卖（RSI 15.5 创 2020 以来最低）＋守 6 万＝瀑布末段企稳酝酿但买方未接管、看涨背离未确认 → 中线大方向暂偏空、状态机＝空仓待机；新开中线低多须等价格守稳 6 万并给出右侧企稳/看涨背离确认信号再议，不在 6 万上方接飞刀左侧抄底（延续 6/3、5/28 左侧接飞刀连环止损教训）。今日系统晚间总评分 63＜70＝Maker 日内框架观望不挂单，与中线（基本面＞盘面＞盘口）分流互不干扰。", YEL, True)]),

    # 18 divider
    divider(),
    # 19 Maker heading_2（观望·不挂单）
    h2("BTC（策略）：总评分 63（盘口 45＋盘面 18）＜70 门槛　观望·不挂单"),
    # 20 观望理由 paragraph (yellow)
    para([R("周末缩量横盘（Vol 230M·约 6/5 的 1/3）＋看涨背离酝酿（价格横盘拒随 CVD 续创新低）＋资费接近 0 超卖＝结构处下跌末段企稳过渡区；非清晰单边、非 C01/C02 极端组合，当前无 ≥60% 可达的高质量反抽空边缘，亦无确认的右侧企稳低多信号 → 系统判观望，不挂单（绝不为占格凑挂单）。", YEL, True)]),
    # 21 假设性方向倾向① paragraph（仅记录·不挂）
    para([R("情形一（反抽空·左侧反应）：若后续反抽至 60,900-61,500（1H SMA20 60,984 ＋ 6/6 日线高 61,530）被拒、且 CVD 恢复下行＝反抽空机会，挂价将设于此带左侧。", None, False)]),
    # 22 假设性方向倾向② paragraph
    para([R("情形二（右侧企稳低多）：若价格守稳 6 万整数关、CVD 转上行 ＋ 资费转负＝看涨背离确认，则右侧企稳低多机会。", None, False)]),
    # 23 触发门槛 heading_3
    h3("触发门槛："),
    # 24 条件一 paragraph (bold)
    para([R("第一档：上述情形出现且总评分回升 ≥70（盘口命中 C01/C02 极端或一致性增强）→ 方可按 Maker 模板挂边缘单。", None, True)]),
    # 25 条件二 paragraph (bold)
    para([R("第二档：在 ≥70 基础上，挂价须为 ≥60% 可达的高质量边缘（执行概率达宪法门槛），R:R ≥1:2.5、胜率 ≥70%。", None, True)]),
    # 26 说明 paragraph
    para([R("说明：今日两情形均未满足（价格处区间中下部、背离仅酝酿未确认），故不挂单、不预埋；待右侧信号。", None, False)]),
    # 27 提示 paragraph
    para([R("⚠️ 今日为纯评分未达 70 门槛的观望（门禁开启正常·非门禁阻断、非风控阻断、非连续止损降频）；门禁/心力一切正常，仅因盘面无高质量机会。", PUR, True)]),
    # 28 核心 paragraph (default)
    para("核心（观望逻辑）：BTC 日线 RSI 约 15.5 创 2020 以来最低＝极度超卖，瀑布末段缩量横盘、守 6 万、看涨背离酝酿但买方（CVD）尚未接管、价格未给右侧确认；左侧接飞刀低多已在 6/3、5/28 连环止损＝纪律上不在此位左侧抄底，右侧反抽空又距边缘 +0.5~1.4% 且评分未达门槛＝不挂。系统选择空仓观望、等右侧信号，纪律优先于行情。"),
    # 29 持仓校准 paragraph (default)
    para("持仓校准：主账户最新 6/3 低多@67,000 已止损出局（盈亏 +13·PCT3%）现空仓 0%（6/4-6/6 无新仓）；Maker 最新 6/4 做多 800 刀状态＝未开仓（挂单未成交·用户手写未开仓计划），当前 Maker 无实际持仓。两账户均空仓、今日个人休息无盘中开仓。系统独立判观望，持仓状态仅作事实校准、未参照用户判断。"),
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
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-06e_1_macro.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-06e_2_geo.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-06e_3_oversold.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
