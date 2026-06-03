# -*- coding: utf-8 -*-
# 早间日报 -> Notion，严格 100% 对齐 2026.6.2 早间页：block 类型 + 逐 run 字体颜色全对齐
import sys, json, requests
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import (para, h2, h3, quote, divider, rt, _h,
                             create_page, find_child_page, ensure_date_page,
                             get_children, insert_after, image_block, upload_image)

RED, YEL, GRN, PUR = "red", "yellow", "green", "purple"
def R(t, c=None, b=False): return rt(t, color=c, bold=b)

DATE = "2026.6.3"
TITLE = "🌅 2026.6.3 早间日报（11:00 评分点）"
date_page = ensure_date_page(DATE)

old = find_child_page(date_page, "🌅 2026.6.3")
if old:
    requests.patch(f"https://api.notion.com/v1/pages/{old}",
                   headers=_h(), data=json.dumps({"archived": True})).raise_for_status()
    print("archived old:", old)

blocks = [
    # 1 quote (default)
    quote("门禁 6/3＝可交易（身体正常/情绪平静/节奏顺/结果依赖无）；连续止损数 2、逼近≥3锁定线→降频谨慎，未触发停牌；心力正常无收缩机制。总评分 74（盘口52+盘面22）≥70 → 必挂 Maker 单于高质量边缘。"),

    # 2 不能做 heading_2
    h2([R("不能做："), R("（追）做空", RED, True)]),

    # 3 基本面 heading_3
    h3([R("基本面："), R("中性偏空", RED, True),
        R("（地缘伊朗强硬延续——美国务卿不以解除对伊制裁换取霍尔木兹海峡通航、冲突进入第4个月，较6/2「和谈一周内或达成」明显转回强硬；美联储主席沃什任命2名保守派顾问推改革=取消双重使命仅控通胀+缩表、鹰派；降息预期月内大幅price out；加密自身结构性去杠杆延续：Garrett Jin 1268枚BTC 5x多单浮亏超1150万、麻吉加仓做多周亏超百万=多头巨鲸普遍被套未投降）", YEL, True),
        R("价格部分兑现", GRN, True),
        R("（BTC自约77,000暴跌至66.7k）", RED, True)]),

    # 7 技术面 heading_3 (default)
    h3("技术面："),
    # 8 盘口（合约）paragraph (default)
    para("盘口（合约）："),
    # 9 CVD line paragraph (bold, no color)
    para([R("CVD下降　价格下降　资金费率上升（为正值）　持仓横盘", None, True)]),
    # 10 解读 heading_3
    h3([R("解读："), R("利空", YEL, True),
        R("（"), R("6/2放天量678M破位、主动卖压持续不竭", RED, True),
        R("，CVD累积深负+资费仍正=残余多头未投降，属下跌中继/多头出清；唯6/3早盘砸至日线POC 66,666后微现正Delta，关注超卖反弹）")]),

    # 11 盘面 paragraph (default)
    para("盘面："),
    # 12 日线级别 paragraph
    para([R("日线级别　"), R("暴跌破上升平行通道下轨+0.618斐波", RED, True),
          R("，SMA20/200下方空头排列，POC逐级下移、现价砸落日线POC 66,666　"), R("利空", RED, True)]),
    # 13 小时级别 paragraph
    para([R("小时级别　"), R("1H/4H全空头排列，SMA20向下并跌穿68,300/69,100", RED, True),
          R("，前POC 67,000转为头顶压力，CVD↓　"), R("利空", RED, True)]),

    # 14 趋势确认 heading_3
    h3([R("趋势确认："), R("空头趋势（单边·放量破位下行）", RED, True)]),
    # 15 日内支撑/压力 heading_3
    h3([R("日内支撑：", None, True), R("65,800-66,300", GRN, True),
        R("　　日内压力：", None, True), R("67,000-67,600", RED, True)]),

    # 16 策略 heading_3 (default)
    h3("策略："),
    # 17 策略正文 paragraph (yellow bold whole)
    para([R("中线主账户（5/28做多@73,500·底仓30%·5x·$1000·1:3·左侧Taker）已触发第三层防守计划、止损出局@68,000（价格口径约-7.5%、PCT 8%、亏损），中线计划本轮终结、现无持仓。状态机＝现金观望，不逆势抄底新中线仓；待基本面与盘面共振企稳、出现高质量入场信号再重建。连续止损2笔、逼近门禁锁定线，保持纪律、严控敞口。", YEL, True)]),

    # 18 divider
    divider(),
    # 19 Maker heading_2 (default)
    h2("BTC（策略）：执行概率 60%（已执行 0%）　胜率 65%"),
    # 20 反弹空 paragraph (bold whole)
    para([R("反弹空：67,200-67,600（破位前POC 67,000 + 1H SMA20 下沿 = 最近且≥60%可达的高质量反抽阻力带，现价66,748仅需+0.7~1.3%）　持仓 700 刀　Binance　左侧　盈亏比 1:2.5 以上", None, True)]),
    # 21 止盈 paragraph (green bold)
    para([R("止盈：65,400（TP1·+2R）减仓50% ／ 64,400（TP2·+3R）", GRN, True)]),
    # 22 止损 paragraph (red bold)
    para([R("止损：站稳 68,400 上方（有效突破1H SMA20+前结构=反抽空失效）= 结构失效离场（单笔约1.5%，<3%）", RED, True)]),
    # 23 防守计划 heading_3 (default)
    h3("防守计划："),
    # 24 第一层 paragraph (bold)
    para([R("第一层：价格首次触及 65,900（1.5R）以下→设4小时级别低点为止损且取消所有加仓", None, True)]),
    # 25 第二层 paragraph (bold)
    para([R("第二层：价格触及 65,400（2R）以下→设保本损", None, True)]),
    # 26 注意事项 paragraph (purple bold)
    para([R("注意事项：若价格优先触及 65,400（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)]),
    # 27 ⚠️ 取消价≠止损 paragraph (purple bold)
    para([R("⚠️ 取消价(65,400·成交前撤单) ≠ 止损(68,400·成交后离场)", PUR, True)]),
    # 28 持仓校准 paragraph (default)
    para("持仓校准：主账户中线多单已止损出局@68,000、现无持仓；Maker 6/1做多700刀已平仓、6/2手写做多800刀挂单(取消价71,400)随暴跌至66.7k已失效，当前 Maker 无实际持仓。"),
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
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03_1_fed.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03_2_iran.png",
    r"C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\2026-06-03_3_longs.png",
]
insert_after(pid, after, [image_block(upload_image(p)) for p in imgs])
print("IMAGES inserted after 基本面:", after)
