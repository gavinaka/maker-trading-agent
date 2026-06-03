# -*- coding: utf-8 -*-
# 晚间日报 -> Word（本地备份），中文字体 Microsoft YaHei
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

H("2026-06-03 晚间日报（20:00 UTC+8 · 系统独立稿 · 链 B）", 15)
P([("门禁 6/3＝可交易；今日 Maker 做多 800 刀已止盈出局（盈 $10）＝连续止损 streak 中断、降频警示解除；心力正常。现价 67,250（4 日瀑布、扫 65,000 低点后反抽横盘）。总评分 73（盘口50+盘面23）≥70 → 必挂 Maker 反弹空。", None, False)])
doc.add_paragraph()

H("① 日报正文", 13)
P([("不能做：", None, True), ("（追）做多", RED, True)])
P([("基本面：", None, True), ("中性偏空", RED, True),
   ("（Strategy 四年来首次出售 32 枚 BTC、打破「只囤不卖」信仰（MSTR 罕见抛售付优先股股息·QCP+BiyaPay 双源）；现货 BTC ETF 连续 11 日净流出约 35 亿美元、机构持续撤离；克利夫兰联储主席称通胀持续或需重启加息＝联储鹰派；贝莱德向 Coinbase 存入 6,005.46 枚 BTC（4.03 亿·潜在卖压）；QCP 期权 IV 升至 41.4、风险逆转大幅为负＝防御浓厚；一夜超 25 万人爆仓、清算超 16 亿。噪音：摩根大通美股盈利超级周期 risk-on 未传导币市、Arthur Hayes 喊单 WLD+23%。地缘：特朗普要求以色列对贝鲁特停火＝潜在缓和未定）", YEL, False),
   ("价格部分兑现", GRN, True), ("（自 77,000 瀑布至 65,000 低点、现回升 67,250、本周累跌约 11.6%、市场对冲非恐慌）", RED, False)])
H("技术面：", 11)
P("盘口（合约）：")
P([("CVD下降　价格横盘　资金费率下降（为正值）　持仓横盘", None, True)])
P([("解读：", None, True), ("中性偏空", YEL, True),
   ("（1H CVD 创新低 -27,475 但价格横盘反抽＝看跌背离·反弹乏力无量；资费自 0.0100 高位回落至 0.0039＝多头降温但仍正、未投降、下跌中继；OI 59,161 自 62K 峰回落后横盘＝去杠杆企稳；唯 6/3 日线缩量 229M+Delta 转正+12M+POC 上移 66,774+一夜爆仓 16 亿近 capitulation＝超卖反抽有基础，双向博弈，净中性偏空、反弹大概率被卖）", None, False)])
P("盘面：")
P([("日线级别　", None, False), ("4 日瀑布破上升通道下轨+0.618、砸日线 POC 66,774 企稳、缩量反抽（229M vs 678M·无量）、SMA20 75,042 远上下行、全空排列　", RED, False), ("利空", RED, True)])
P([("小时级别　", None, False), ("4H/1H 全空排列、1H SMA20 67,000-67,500 转头顶压制、4H SMA20 70,707 下行、1H CVD 创新低看跌背离、价横盘反抽贴 SMA20 下方　", RED, False), ("利空", RED, True)])
P([("趋势确认：", None, True), ("空头趋势（单边破位下行 · 盘中超卖反抽整理）", RED, True)])
P([("日内支撑：", None, True), ("65,300-65,800", GRN, True), ("　　日内压力：", None, True), ("67,900-68,800", RED, True)])
H("策略：", 11)
P([("中线主账户今日新开低多@67,000（50%·5x·$700·1:2.5·左侧 Taker·接飞刀·长持）持仓中，现价 67,250 浮盈微正（约 +0.4%）；防守第一层 68,500/第二层 70,500 未激活。系统独立判断：基本面中性偏空（Strategy 首卖+ETF 连续 11 日流出 35 亿+联储鹰派）+盘面空头排列下跌中继→中线大方向仍偏空，此为逆势接飞刀（位置与方向背离、风险偏高）；纪律守损：跌破日线低点 65,800 即止损砍短、不补仓、盈利放满，价回 68,500 方激活第一层防守。今日 Maker 做多止盈出局（盈 $10·仅成交 50%）＝连续止损 streak 中断、降频警示解除、门禁可交易。", YEL, True)])
P([("⚠️ 系统晚间盘口独立判向＝反弹空（与主账户低多持仓相反·日内 Maker 框架盘口＞盘面＞基本面），与中线（基本面＞盘面＞盘口）框架分流、互不干扰；本稿方向仅独立信号、不构成对已持仓操作建议。", PUR, True)])
doc.add_paragraph()

H("② Maker 计划", 13)
P([("BTC（策略）：执行概率 62%（已执行 0%）　胜率 62%", None, True)])
P([("反弹空：67,900-68,200（用户压力 6.3 下沿 + 4H POC 67,972 共振＝最近且 ≥60% 可达高质量反抽带，现价 67,250 仅需 +0.6~1.4%）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上", None, True)])
P([("止盈：66,000（TP1·≈+2.5R）减仓 50% ／ 65,300（TP2·支撑 6.3 下沿·≈+3.4R）", GRN, True)])
P([("止损：站稳 68,800 上方（有效突破压力 6.3 上沿＝反抽空失效）结构失效离场（R≈800·单笔约 1.2%，<3%）", RED, True)])
H("浮盈防守计划：", 11)
P([("第一层：价格首次触及 66,800（1.5R）以下→设 4 小时级别高点为止损且取消所有加仓", None, True)])
P([("第二层：价格触及 66,000（2.5R）以下→减仓 50%、设保本损", None, True)])
P([("注意事项：若价格优先触及 65,300（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)])
P([("⚠️ 取消价(65,300·成交前撤单) ≠ 止损(68,800·成交后离场)", PUR, True)])
P([("核心：4 日瀑布破位后超卖反抽至压力 6.3 下沿+4H POC+1H SMA20 共振压制、缩量无量反弹、1H CVD 创新低看跌背离、资费正回落＝多头降温未投降下跌中继；基本面利空＝高质量反抽空、资金保全左侧反应。", None, False)])
doc.add_paragraph()

H("③ 后附（系统内部备份·不进 Notion）", 13)
P("评分：盘口 50（看跌背离·反弹乏力无量，超卖 capitulation 反抽有基础削弱确定性）+ 盘面 23（接近度8/掠夺7/SMA20 5/量价2/斐波1）= 73 ≥70 必挂。")
P("持仓校准（REST·禁沿用）：主账户今日新开中线低多@67,000（50%·700刀·持仓中，防守 68,500/70,500）；Maker 今日做多 800 刀已止盈出局（盈 $10·PCT 2%·TP1·仅成交 50%），当前 Maker 无持仓。⚠️ 主账户实际持仓做多，系统独立判反弹空（相反），仅作独立信号、不构成对已持仓操作建议。")

out = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-03_晚间日报.docx"
doc.save(out)
print("SAVED", out)
