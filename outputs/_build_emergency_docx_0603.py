# -*- coding: utf-8 -*-
# 应急盘中日报 -> Word（本地备份），中文字体 Microsoft YaHei
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

H("2026-06-03 应急盘中日报（13:25 UTC+8 · 系统独立稿）", 15)
P([("门禁 6/3＝可交易；连续止损 2 逼近锁定线→降频；心力正常。现价 67,050（四日瀑布、扫 65,800 低点后反弹）。总评分 71（盘口50+盘面21）≥70 → 必挂 Maker 反弹空。", None, False)])
doc.add_paragraph()

H("① 日报正文", 13)
P([("不能做：", None, True), ("（追）做多", RED, True)])
P([("基本面：", None, True), ("中性偏空", RED, True),
   ("（BTC ETF 6/2 净流出 5.19 亿·IBIT 占 75%，合计 BTC+ETH 6.09 亿、机构连续撤离；24h 全网爆仓 17.03 亿·主爆多单 15.33 亿＝多头血洗；链上派发——Garrett Jin 转 13.5 亿 ETH 逃顶、USDH 解质押 101 万 HYPE 出售、23 连胜巨鲸 20x 新开 4,803 万 BTC 空@66,128；黄仁勋喊单 MRVL/英伟达组合 risk-on 未传导币市）", YEL, False),
   ("价格部分兑现", GRN, True), ("（自 77,000 跌至 65,800 低点、现回升 67,050、24h 跌幅收窄至 5.19%）", RED, False)])
H("技术面：", 11)
P("盘口（合约）：")
P([("CVD下降　价格上升　资金费率上升（为正值）　持仓横盘", None, True)])
P([("解读：", None, True), ("中性偏空", YEL, True),
   ("（1H CVD 创新低 -28,582 但价格反弹＝看跌背离·反弹无量诱多；资费持续正 0.0066-0.0081＝残余多头未投降、下跌中继；唯 6/3 日线缩量 153M+Delta 转正+1.5M+砸 POC 66,282 锤子吸筹+爆仓主爆多＝超卖反弹有基础，双向博弈，净中性偏空、反弹大概率被卖）", None, False)])
P("盘面：")
P([("日线级别　", None, False), ("破上升通道下轨+0.618、全空排列、SMA20/200 远上、POC 下移至 66,282　", RED, False), ("利空", RED, True)])
P([("小时级别　", None, False), ("1H 扫 65,975 低点后反弹、SMA20 67,498 转头顶阻力、4H 全空排列、前 POC 67,000 争夺、CVD↓　", RED, False), ("利空", RED, True)])
P([("趋势确认：", None, True), ("空头趋势（单边破位下行 · 盘中超卖反弹）", RED, True)])
P([("日内支撑：", None, True), ("65,300-65,800", GRN, True), ("　　日内压力：", None, True), ("67,500-68,200", RED, True)])
H("策略：", 11)
P([("中线主账户今日新开低多@67,000（50%·5x·$700·1:2.5·左侧 Taker·长持）持仓中，防守第一层 68,500/第二层 70,500 未激活。系统独立判断：基本面中性偏空+盘面破位下行→中线大方向仍偏空，此为逆势接飞刀（位置与方向背离、风险偏高）；纪律守损：跌破 4H/日线低点 65,800 即止损砍短、不补仓、盈利放满，价回 68,500 方激活第一层防守。连续止损 2 笔、严控敞口降频。", YEL, True)])
doc.add_paragraph()

H("② Maker 计划", 13)
P([("BTC（策略）：执行概率 62%（已执行 0%）　胜率 60%", None, True)])
P([("反弹空：67,500-67,900（1H SMA20 67,498 下沿 + 压力 6.3 区 67,800 中部＝最近且 ≥60% 可达高质量反抽带，现价 67,050 仅需 +0.7~1.3%）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上", None, True)])
P([("止盈：65,800（TP1·支撑 6.3 上沿·≈+2.4R）减仓 50% ／ 65,300（TP2·≈+3R）", GRN, True)])
P([("止损：站稳 68,500 上方（突破压力 6.3+1H SMA20＝反抽空失效）结构失效离场（单笔约 1.2%，<3%）", RED, True)])
H("浮盈防守计划：", 11)
P([("第一层：价格首次触及 66,500（1.5R）以下→设 4H 级别低点 65,800 为止损且取消所有加仓", None, True)])
P([("第二层：价格触及 65,800（≈2.4R）以下→减仓 50%、设保本损", None, True)])
P([("注意事项：若价格优先触及 65,800（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)])
P([("⚠️ 取消价(65,800·成交前撤单) ≠ 止损(68,500·成交后离场)", PUR, True)])
P([("核心：四日瀑布破位后超卖反弹无量、CVD 创新低看跌背离、资费仍正＝残余多头未投降下跌中继；反弹至 1H SMA20+压力 6.3 高质量反抽带＝资金保全左侧反应空。", None, False)])
doc.add_paragraph()

H("③ 后附（系统内部备份·不进 Notion）", 13)
P("评分：盘口 50（看跌背离·反弹无量诱多，超卖 capitulation 反弹有基础削弱确定性）+ 盘面 21（接近度7/掠夺6/SMA20 4/量价2/斐波2）= 71 ≥70 必挂。")
P("持仓校准（REST·禁沿用）：主账户今日新开中线低多@67,000（50%·700刀·持仓中，防守 68,500/70,500）；Maker 今日新开做多 800 刀（左侧·击中50%·已触第一层防守 66,700，取消价 67,800）。⚠️ 实际两仓均做多，系统独立判反弹空（相反），仅作独立信号、不构成对已持仓操作建议。")

out = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-03_应急盘中日报.docx"
doc.save(out)
print("SAVED", out)
