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

H("2026-06-05 晚间日报（20:00 UTC+8 · 系统独立稿 · 链 B）", 15)
P([("门禁 6/5＝开启·可交易（备注「工作团建宿醉身体比较疲惫」）＋心力最新 6/4＝消耗 10·工作团建·有疲惫感·收缩机制＝非硬停、降频谨慎日（照 ≥70 必挂但只挂边缘左侧、不主动追）。现价 61,950；日内路径＝早间 61,470 → 强反抽至高点 63,259（+2.9%·上破 1H SMA20 63,023 后于 63k 被拒）→ NFP 20:30 超预期打回 → 61,950（冲高回落）。总评分 72（盘口50+盘面22）≥70 → 必挂 Maker 反弹空。", None, False)])
doc.add_paragraph()

H("① 日报正文", 13)
P([("不能做：", None, True), ("（追）做空", RED, True)])
P([("基本面：", None, True), ("利空", RED, True),
   ("（「沃什时代」首份非农远超预期：美 5 月季调后非农就业 17.2 万人、预期仅 8.5 万、前值由 11.5 万上修至 17.9 万、失业率 4.3% 持平＝就业强劲；分析师称数据彻底推翻美联储未来几月降息理由、联储 12 月加息概率自 48% 骤升至 63%、市场定价美联储明年 1 月加息（原预期 3 月）；美元 DXY 短线 +15 至 99.36、现货黄金挫近 20 美元、美股标普/纳指期货跌至盘中低点＝risk-off；BTC 承压现报 61,801（24h -3%）；ZEC 因无限增发漏洞 24h 暴跌 39.6%＝山寨黑天鹅延续；贝莱德 ETF 向 Coinbase 存入 1,978 BTC+14,244 ETH＝潜在卖压。对冲（逢低吸筹）：某巨鲸今日累计自 Aave 借 7,642 万买 44,845 ETH（均价 1,704）、F2Pool 王纯提 9,719 ETH 抄底、灰度 Hyperliquid ETF 首日净流入 470 万。Tier1 宏观转鹰主导＝利空）", YEL, False),
   ("价格部分兑现", GRN, True), ("（BTC 自非农前回落约 3% 至 61.8k、美元/加息预期重定价仍在进行）", RED, False)])
H("技术面：", 11)
P("盘口（合约）：")
P([("CVD下降　价格冲高回落（日内反抽 63,259 被拒）　资金费率上升（为正值·低位）　持仓下降", None, True)])
P([("解读：", None, True), ("中性偏空", YEL, True),
   ("（日内价格强反抽至 63,259（上破 1H SMA20 63,023）即遭 63k 供给 + NFP 拒绝、冲高回落至 61,950＝反弹失败、卖方守住阻力；1H CVD -36,246K 全程未随价反抽走强、维持近低位＝买盘无量、反抽不被验证；资费自 6/4 偶现负柱回升至 0.0025＝接近 0 的超卖区多头试探未投降；OI 56.5K 自 58K 回落＝去杠杆；6/5 日线缩量 168M（vs 6/4 317M·约半）+Delta 转正 +3.5M（=日内反抽买盘但被阻力吞没）+POC 下移 61,897＝瀑布末段缩量，但反抽于 63k 被拒 + NFP 宏观转鹰＝净中性偏空、反弹被卖）", None, False)])
P("盘面：")
P([("日线级别　", None, False), ("多日瀑布破上升通道下轨+0.618、砸穿 POC 67,000 续创新低 61.9k、SMA20 73,311 远上下行、全空排列；唯 6/5 缩量（168M）+Delta 转正＝动能衰减　", RED, False), ("利空", RED, True)])
P([("小时级别　", None, False), ("4H/1H 全空排列、日内反抽一度上破 1H SMA20 63,023 至 63,259、即被 63k 供给 + NFP 打回收复均线下方、4H SMA20 64,914 下行、CVD 未随反抽走强　", RED, False), ("利空", RED, True)])
P([("趋势确认：", None, True), ("空头趋势（单边破位下行 · 日内反抽至 63,259 失败被拒）", RED, True)])
P([("日内支撑：", None, True), ("59,600-60,000", GRN, True), ("　　日内压力：", None, True), ("62,800-63,300", RED, True)])
H("策略：", 11)
P([("中线主账户与 Maker 当前均空仓（主账户 6/3 低多@67,000 已止损出局、本轮中线计划终结；Maker 6/4 做多 800 刀挂单未成交＝用户手写未开仓计划、独立稿不引用其方向）＝无在持仓位、无防守层需守。系统独立判断：基本面利空（NFP 17.2 万远超 8.5 万预期＝降息理由被推翻、加息预期骤升、美元走强）+盘面空头排列下跌中继→中线大方向仍偏空；状态机＝空仓待机，新开中线仓须等高质量反转/确认信号，不在 near lows 追空亦不接飞刀左侧抄底。今日系统晚间盘口独立判向＝反弹空（≥70 必挂·日内 Maker 框架盘口＞盘面＞基本面），与中线（基本面＞盘面＞盘口）分流互不干扰。", YEL, True)])
P([("⚠️ 门禁备注疲惫+心力团建收缩＝降频谨慎日：照 ≥70 必挂但只挂高质量边缘等左侧反应、不主动追价、不加码。", PUR, True)])
doc.add_paragraph()

H("② Maker 计划", 13)
P([("BTC（策略）：执行概率 62%（已执行 0%）　胜率 60%", None, True)])
P([("反弹空：62,500-63,000（破位的用户支撑 6.4（62,200-62,600）转阻力 + 1H SMA20 63,023 共振、且日内反抽高 63,259 已在此带上方被拒证明为有效供给＝最近且 ≥60% 可达高质量反抽带，现价 61,950 仅需 +0.9~1.7%）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上", None, True)])
P([("止盈：59,600（TP1·近 60,000 整数关下沿/日线低点 59,608·≈+2.5R）减仓 50% ／ 58,500（TP2·≈+3.4R）", GRN, True)])
P([("止损：站稳 64,000 上方（有效站上＝结构反转、反抽空失效）结构失效离场（R≈1,250·单笔约 2.0%，<3%）", RED, True)])
H("浮盈防守计划：", 11)
P([("第一层：价格首次触及 60,800（1.5R）以下→设 4 小时级别高点为止损且取消所有加仓", None, True)])
P([("第二层：价格触及 59,600（2.5R）以下→减仓 50%、设保本损", None, True)])
P([("注意事项：若价格优先触及 59,400（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）", PUR, True)])
P([("⚠️ 取消价(59,400·成交前撤单) ≠ 止损(64,000·成交后离场)", PUR, True)])
P([("核心：日内强反抽至 63,259（上破 1H SMA20 63,023）即被 63k 供给 + NFP 打回＝反抽失败、阻力带有效，破位支撑 6.4 转阻力+1H SMA20 63,023 共振压制＝最近高质量反抽空带；基本面 NFP 超预期宏观转鹰（降息理由推翻、加息预期 48→63%、美元走强）强化空头方向；唯缩量+日线 Delta 转正＝瀑布末段量能衰减，只挂边缘左侧、TP1 设 60,000 关上方落袋、降频谨慎不追。", None, False)])
doc.add_paragraph()

H("③ 后附（系统内部备份·不进 Notion）", 13)
P("评分：盘口 50（日内反抽至 63,259 被 63k 供给+NFP 打回＝反抽失败下跌中继；缩量+日线 Delta 转正＝量能衰减削弱确定性，但空头守住阻力对冲）+ 盘面 22（接近度7/掠夺6/SMA20 5/量价2/斐波2）= 72 ≥70 必挂（降频谨慎·只挂边缘左侧）。日内高 63,259 经 Exo H-L 2,848.2 交叉核验（早前误取 Coinglass 末根 1h 高 62,430，已订正）。")
P("持仓校准（REST·禁沿用）：主账户 6/3 低多@67,000 已止损出局（盈亏 +13·PCT3%）现空仓 0%；Maker 最新 6/4 做多 800 刀状态＝未开仓（挂单未成交·用户手写未开仓计划），当前 Maker 无实际持仓。两账户均空仓。⚠️ 系统独立判反弹空，持仓状态仅作事实校准、未参照用户判断。")

out = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-05_晚间日报.docx"
doc.save(out)
print("SAVED", out)
