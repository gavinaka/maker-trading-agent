# -*- coding: utf-8 -*-
# 晚间日报 6/6 -> Word（本地备份·观望样本日），中文字体 Microsoft YaHei
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn

RED = RGBColor(0xC0, 0x00, 0x00); GRN = RGBColor(0x1F, 0x7A, 0x1F)
YEL = RGBColor(0xB8, 0x86, 0x00); PUR = RGBColor(0x7A, 0x1F, 0x7A)

doc = Document()
st = doc.styles["Normal"]; st.font.name = "Microsoft YaHei"; st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

def P(runs, size=10.5, bold=False):
    p = doc.add_paragraph()
    if isinstance(runs, str): runs = [(runs, None, bold)]
    for t, c, b in runs:
        r = p.add_run(t); r.font.size = Pt(size); r.bold = b
        r.font.name = "Microsoft YaHei"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        if c: r.font.color.rgb = c
    return p

def H(t, size=13):
    p = doc.add_paragraph(); r = p.add_run(t); r.bold = True; r.font.size = Pt(size)
    r.font.name = "Microsoft YaHei"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    return p

H("2026-06-06 晚间日报（20:00 UTC+8 · 系统独立稿 · 链 B · 样本日）", 15)
P([("门禁 6/6＝开启·可交易（节奏顺/连续止损 0/情绪平静/身体正常·无疲惫备注）＝正常可交易日。用户今日个人休息·无盘中交易，本稿为系统独立测试样本。现价 60,656；日内路径（周六）＝开 61,056 → 早 03:00 探低 59,500（15m 59,200）→ 反抽约 62,000 → 震荡收敛回落 → 60,668（收·-0.63%），周末缩量横盘坐 15m 上升趋势线企稳。总评分 63（盘口45+盘面18）＜70 → 观望·不挂单。", None, False)])
doc.add_paragraph()

H("① 日报正文", 13)
P([("不能做：", None, True), ("（追）做空", RED, True)])
P([("基本面：", None, True), ("中性偏空", YEL, True),
   ("（强非农推升加息预期＋中东地缘升级＝利空主导：美 5 月非农 17.2 万远超预期 8.5 万、12 月加息概率升至 63%、美元指数重返 100 上方、黄金连续第四周下跌、费城半导体单日 -10%＝美股科技股单日蒸发超 1 万亿美元、日本央行 6 月或加息至 1%（概率 >80%）；伊朗向科威特/巴林发射 7 枚导弹（美军拦 6）、以军空袭黎巴嫩致一名将军身亡＝停火脆弱、中东 risk-off；Longling Capital 卖出 1 万枚 ETH＋三巨鲸 34.5 万枚 ETH 面临清算（>5.3 亿）＝山寨抛压。对冲（反弹燃料）：BTC 日线 RSI 约 15.5＝创 2020 年疫情崩盘以来最低、极度超卖（历史类似位后曾反弹约 50%/30%）、短期持有者已实现盈亏比历史最低、530 万枚长期 BTC 浮亏（高于 FTX 时期）、情绪接近恐慌；多头守住 6 万美元关键支撑；某巨鲸今日 1,633 美元增持 9.33 万 ETH 抄底；Zcash Orchard 漏洞已修复。Tier1 宏观强鹰＋地缘升级主导＝利空，唯极度超卖＋守 6 万＝企稳燃料）", YEL, False),
   ("价格部分兑现", GRN, True), ("（BTC 近一月已跌约 30% 至 6.1k 下、宏观重定价大体走完、6 万未破）", YEL, False)])
H("技术面：", 11)
P("盘口（合约）：")
P([("CVD下降　价格横盘　资金费率横盘（接近0值）　持仓下降", None, True)])
P([("解读：", None, True), ("中性偏空", YEL, True),
   ("（1H CVD -40,341K 续创新低＝卖压未止，但价格横盘拒随 CVD 续创决定性新低＝看涨背离酝酿；资费 0.0010 接近 0 的超卖区、6/4 附近偶现负柱＝多头接近投降；OI 自 58.5K 回落至 57.0K＝去杠杆出清；6/6 日线缩量 230M（vs 6/5 650M·约 1/3）+Delta -14M（负但幅度全周最小）+POC 自 59,778 上移至 60,930+H-L 收窄至 2,047.8＝瀑布末段卖压衰竭横盘；唯 CVD 累积深负（Exo -190M）买方尚未接管＝企稳未确认）", None, False)])
P("盘面：")
P([("日线级别　", None, False), ("多日瀑布破上升通道下轨+0.618、砸穿 POC 67,000、SMA20 72,431 远上下行、全空排列；唯 6/6 缩量 230M+振幅骤收+POC 上移＝动能显著衰减、瀑布转横盘整理　", YEL, False), ("中性偏空", YEL, True)])
P([("小时级别　", None, False), ("1H 价 60,689 贴 SMA20 60,984 下方走平；15m 自 59,200 探低反抽后坐用户手绘上升趋势线（现≈60,400-60,600）企稳收敛；4H SMA20 62,872 向下转阻力、POC 67,000 头顶　", YEL, False), ("中性偏空", YEL, True)])
P([("趋势确认：", None, True), ("震荡结构（超卖末段企稳 · 盘整区间）", YEL, True)])
P([("日内支撑：", None, True), ("60,000-60,400", GRN, True), ("　　日内压力：", None, True), ("60,900-61,500", RED, True)])
H("策略：", 11)
P([("中线主账户与 Maker 当前均空仓（主账户 6/3 低多@67,000 已止损出局、本轮中线计划终结；Maker 6/4 做多 800 刀挂单未成交＝用户手写未开仓计划、独立稿不引用其方向）＝无在持仓位、无防守层需守。系统独立判断：基本面 Tier1 宏观强鹰＋地缘升级仍偏空，盘口卖压衰竭横盘＋极度超卖（RSI 15.5 创 2020 以来最低）＋守 6 万＝瀑布末段企稳酝酿但买方未接管、看涨背离未确认→中线大方向暂偏空、状态机＝空仓待机；新开中线低多须等价格守稳 6 万并给出右侧企稳/看涨背离确认信号再议，不在 6 万上方接飞刀左侧抄底（延续 6/3、5/28 左侧接飞刀连环止损教训）。今日系统晚间总评分 63＜70＝Maker 日内框架观望不挂单，与中线（基本面＞盘面＞盘口）分流互不干扰。", YEL, True)])
doc.add_paragraph()

H("② Maker 计划", 13)
P([("BTC（策略）：总评分 63（盘口 45＋盘面 18）＜70 门槛 → 观望·不挂单", None, True)])
P([("周末缩量横盘（Vol 230M·约 6/5 的 1/3）＋看涨背离酝酿（价格横盘拒随 CVD 续创新低）＋资费接近 0 超卖＝结构处下跌末段企稳过渡区，非清晰单边、非 C01/C02 极端，无 ≥60% 可达的高质量反抽空边缘，亦无确认的右侧企稳低多信号 → 系统判观望，不挂单。", YEL, False)])
P([("假设性参考（不挂·仅记录方向倾向）：若反抽至 60,900-61,500（1H SMA20 60,984＋6/6 日线高 61,530）被拒且 CVD 恢复下行＝反抽空左侧反应；若守稳 6 万、CVD 转上行＋资费转负＝看涨背离确认右侧低多。二者均须先满足 ≥70 评分门槛方可挂单，当前未达。", None, False)])
doc.add_paragraph()

H("③ 后附（系统内部备份·不进 Notion）", 13)
P("评分：盘口 45（CVD 续创新低卖压未止+价格横盘拒随 CVD 创决定性新低=看涨背离酝酿+资费接近 0 超卖+OI 去杠杆=瀑布末段卖压衰竭横盘；非 C01/C02 极端；与 5/30 校准锚点同型→45）+ 盘面 18（接近度5/掠夺5/SMA20 4/量价2/斐波2）= 63 ＜70 → 观望·不挂单（门禁开启正常·纯评分未达门槛）。")
P("持仓校准（REST·禁沿用）：主账户最新 6/3 低多@67,000 已止损出局（盈亏 +13·PCT3%）现空仓 0%（6/4-6/6 无新仓）；Maker 最新 6/4 做多 800 刀状态＝未开仓（挂单未成交·用户手写未开仓计划），当前 Maker 无实际持仓。两账户均空仓、今日个人休息无盘中开仓。⚠️ 系统独立判观望，持仓状态仅作事实校准、未参照用户判断。")

out = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-06_晚间日报.docx"
doc.save(out)
print("SAVED", out)
