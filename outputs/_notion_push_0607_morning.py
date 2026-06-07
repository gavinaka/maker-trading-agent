# -*- coding: utf-8 -*-
# 早间日报 6/7（观望样本日）-> Notion 🌅 子页，镜像 2026.6.2 早间金标 28 块结构；
# Maker 段如实为「观望·不挂单」（不臆造挂单），块类型逐块对齐金标、配色按情绪词唯一规则。
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR, ORG = "red", "yellow", "green", "purple", "orange"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.7"
TITLE = "🌅 2026.6.7 早间日报（11:00 评分点）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "🌅 2026.6.7")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote
    quote("评分点 11:00 ｜ 现价 61,303（15m 61,303 / 1H 61,283 / 4H 61,320 / 日线 61,295；Coinglass 61,245；Exo POC 61,254）。日内路径（6/7·周日·进行中）：隔夜 60,400-60,900 缩量横盘 → 09:00 后反抽冲 61,714 → 现 61,303 小幅回落，周日缩量企稳、小幅反抽站上 61k、坐 15m 上升趋势线。门禁 6/7＝可交易（身体正常/情绪平静/节奏顺/连续止损 0/结果依赖无）＝正常可交易日；心力最新 6/4＝消耗 10/收缩机制（团建），6/5–6/7 未填、以当日门禁为准 → 6/7 正常无收缩。两账户均空仓。总评分 68（盘口 45→50＋盘面 18）＜70 门槛 → 观望·不挂单。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做空", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("中性偏空", YEL, True),
        R("（Tier1 地缘＋宏观利空主导——美伊战争满 100 天、中东战火小规模重燃（伊朗再袭美军第五舰队、以军黎巴嫩南部 2 名士兵阵亡、革命卫队对 4 艘油轮开火）、停火脆弱（Polymarket「6 月底前永久和平」概率仅 16%）；degentrading 预警韩股「南方两倍做多海力士（7709.HK）」周一约 200 万股强制卖压（相当当日正常成交量 40%·gamma 越跌越卖）、半导体板块极度看空＝传统市场 risk-off 传染；中国央行连续第 19 个月增持黄金（5 月末 2331.52 吨）＝避险延续；加密恐慌与贪婪指数 12「极度恐慌」（昨日亦 12·连续）。对冲（反弹燃料）＝某巨鲸近 24h 囤积约 1723 枚 BTC（约 1.0558 亿美元）、以太坊 OG 巨鲸均价 1563 美元抄底 35723 枚 ETH、BTC 回升突破 61,000（24h 跌幅收窄至 0.53%）、Tom Lee 称美股牛市稳固）"),
        R("价格部分兑现", GRN, True),
        R("（BTC 本轮已跌约 30%、破 61k 回升企稳、6 万未破）")]),

    # 7 技术面 heading_3
    h3("技术面："),
    # 8 盘口（合约）paragraph
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold)
    para([R("CVD上升　价格横盘　资金费率横盘（接近0值·为正值）　持仓上升", None, True)]),
    # 10 解读 heading_3 (中性偏多 = yellow)
    h3([R("解读："), R("中性偏多", YEL, True),
        R("（CVD 自约 -40K 回补至 -37,008K＝本轮首次明显回升、不再续创新低；日线 footprint 6/7 Delta 自 6/6 的 -29M 转正 +15M＝自 6/1 以来首次买盘边际回归；OI 自 57K 回升至 58.0K＝杠杆边际回补；POC 连续上移 59,778→60,798→61,254＝企稳重心抬升；叠加 6/6 探 59,200 即反包（扫 6 万下方止损后 V 反＝空头流动性掠夺）、守 6 万、价反抽站上 61k＝卖压衰竭·买方边际回归·看涨背离自酝酿转确认中。但 CVD 累积仍 -171M 深负＝买方尚未真正接管、一日 Delta 转正不足确认反转、逆势企稳早期）")]),

    # 11 盘面 paragraph
    para("盘面："),
    # 12 日线级别 paragraph (中性偏空 yellow 收口)
    para([R("日线级别　价 61,295 破上升通道下轨 +0.618 斐波、跌穿日线 POC 67,000、SMA20 71,657/SMA200 远在上方、全空排列，RSI 极度超卖、6/7 极度缩量（Exo Vol 78M）守 6 万手绘支撑（下方 58,000/52,800）　"), R("中性偏空", YEL, True)]),
    # 13 小时级别 paragraph (中性 yellow 收口)
    para([R("小时级别　1H 价 61,283 站上 SMA20 60,854 并走平微翘、4H SMA20 62,088 向下转头顶近压、15m 自 6/6 低 59,200 反抽后于 60,000-61,700 收敛横盘、刚冲 61,714 回落坐 15m 上升趋势线（≈60,800-61,000）　"), R("中性", YEL, True)]),

    # 14 趋势确认 heading_3 (空头趋势 red)
    h3([R("趋势确认："), R("空头趋势", RED, True), R("（单边·瀑布末段转底部企稳整理）")]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("60,000-60,400", GRN, True),
        R("　　日内压力：", None, True), R("61,700-62,200", RED, True)]),

    # 16 策略 heading_3
    h3("策略："),
    # 17 策略正文 paragraph (yellow)
    para([R("中线主账户：6/3 接飞刀低多@67,000 已止损出局、本轮中线计划已终结，现金观望、0% 仓。状态机＝不新增防守层；盘口企稳信号增强（Delta 转正＋CVD 回补＋OI 回升＋POC 上移＋守 6 万反包）但大结构仍强空、极度超卖、CVD 累积深负＝企稳证据不足以确认反转，禁左侧接飞刀（连环左侧抄底教训）；待价站稳 62k＋CVD 转正＋日线放量企稳共振，再评估中线重建。中线（基本面＞盘面＞盘口）与 Maker 日内（盘口＞盘面＞基本面）分流，互不干扰。", YEL, True)]),

    # 18 divider
    divider(),
    # 19 Maker heading_2（观望·不挂单）
    h2("BTC（策略）：总评分 68（盘口 50＋盘面 18）＜70 门槛　观望·不挂单"),
    # 20 观望理由 paragraph (yellow)
    para([R("盘口企稳信号增强（CVD 回补＋Delta 转正＋OI 回升＋POC 上移＋守 6 万反包）但逆势 early-stage：大结构仍强空头瀑布（-30%）、极度超卖、CVD 累积仍 -171M 深负（买方尚未接管）、一日 Delta 转正不足确认反转；基本面中性偏空（地缘战火重燃＋韩股半导体强制卖压风险传染）。现价处区间中上部，无「既高质量又 ≥60% 可达」的最近边缘 → 系统判观望，不挂单（绝不为占格凑挂单）。", YEL, True)]),
    # 21 假设性方向倾向① paragraph（偏多·仅记录·不挂）
    para([R("情形一（企稳低多·右侧）：若价回踩 60,000-60,400 高质量支撑（6 万整数关＋15m 区间下沿＋上升趋势线）并伴 CVD 持续回补、Delta 维持转正＝企稳反弹做多机会。当前现价 61,303 距该支撑约 -1.5%（可达 <60%）＋逆势接飞刀风险（CVD 累积仍深负）→ 不挂。")]),
    # 22 假设性方向倾向② paragraph（偏空已弱·仅记录·不挂）
    para([R("情形二（反抽空·左侧）已弱化：守 6 万＋CVD 回补＋Delta 转正使「反抽空」thesis 减弱，仅在价反抽至 61,700-62,200／62,200-62,800（6/4 破位支撑转阻力带）遇明确遇阻＋CVD 重新走弱时才考虑左侧反应空，当前不成立。")]),
    # 23 升级门槛 heading_3
    h3("升级门槛："),
    # 24 第一档 paragraph (bold)
    para([R("第一档：价站稳 62k 上方＋CVD 转正＋OI 放量回补 → 升级低多确认（届时重评分挂单）；或价反抽至 62,200-62,800 遇阻＋CVD 转弱 → 反抽空重新成立。", None, True)]),
    # 25 第二档 paragraph (bold)
    para([R("第二档：在总评分回升 ≥70 基础上，挂价须为 ≥60% 可达的高质量边缘（执行概率达宪法门槛），R:R ≥1:2.5、胜率 ≥70% 方可挂边缘单。", None, True)]),
    # 26 注意事项 paragraph (purple)
    para([R("注意事项：极度超卖（恐慌指数 12）＋守 6 万＋6/6 探 59,200 即反包＝右侧追空最易被反弹反包，严格不在 6 万-61k 区右侧追空（对应「不能做＝（追）做空」）。", PUR, True)]),
    # 27 提示 paragraph (purple)
    para([R("⚠️ 今日为纯评分未达 70 门槛的观望（门禁开启正常·非门禁阻断、非风控阻断、非连续止损降频）；门禁/心力一切正常，仅因盘面无高质量机会、不臆造挂单凑门槛（准确性优先）。", PUR, True)]),
    # 28 持仓校准 paragraph (default)
    para("持仓校准：主账户最新 6/3 低多@67,000 已止损出局（盈亏 +13·PCT3%）现空仓 0%（6/4-6/7 无新仓）；Maker 最新 6/4 做多 800 刀状态＝未开仓（挂单未成交·用户手写未开仓计划），当前 Maker 无实际持仓。两账户均空仓。系统独立判观望，持仓状态仅作事实校准、未参照用户判断。"),
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
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-07_1_geo.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-07_2_risk.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-07_3_whale.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
