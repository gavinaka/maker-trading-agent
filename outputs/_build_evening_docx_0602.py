# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

doc = Document()
st = doc.styles['Normal']
st.font.name = 'Microsoft YaHei'
st.font.size = Pt(10.5)
st._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

def setfont(run, size=10.5, bold=False, color=None):
    run.font.name = 'Microsoft YaHei'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color

def H(text, size=13):
    p = doc.add_paragraph()
    r = p.add_run(text)
    setfont(r, size=size, bold=True, color=RGBColor(0x1F,0x49,0x7D))
    p.space_after = Pt(4)
    return p

def line(text, bold=False, color=None, size=10.5):
    p = doc.add_paragraph()
    r = p.add_run(text)
    setfont(r, size=size, bold=bold, color=color)
    p.paragraph_format.space_after = Pt(2)
    return p

RED = RGBColor(0xC0,0x00,0x00)
ORANGE = RGBColor(0xB0,0x60,0x00)
GREEN = RGBColor(0x1E,0x7A,0x32)

# Title
p = doc.add_paragraph()
r = p.add_run('2026-06-02 晚间日报（系统独立稿）')
setfont(r, size=16, bold=True, color=RGBColor(0x00,0x00,0x00))
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

line('评分点 20:00 ｜ 现价 69,462（15m 最新；日线收 69,470 / -2.72%，日内低 69,324）。门禁 6/2＝可交易、心力正常无收缩。总评分 74（盘口53+盘面21）≥70 → 必挂 Maker。', color=RGBColor(0x55,0x55,0x55), size=9)

# ===== 正文 =====
H('① 日报正文')
line('不能做：（追）做空', bold=True, color=RED)
p = doc.add_paragraph()
setfont(p.add_run('　'), size=9)
setfont(p.add_run('现价69,462已跌破多头最后防守(71,000)/大级别共振支撑(72,000)、逼近0.618日线支撑(68,758)，OI回落=多头去杠杆、资金费率仍正=残余多头未完全投降→最易被收割侧=69,462低位右侧追空(易被超卖反弹反包)。禁追空仅禁右侧；反弹至70,000-70,400/1H SMA20的左侧反应空(=本Maker)不禁；若0.618掠夺反包+CVD底背离，对侧左侧低多亦不禁。'), size=9, color=RGBColor(0x55,0x55,0x55))

p = doc.add_paragraph()
r1 = p.add_run('基本面：'); setfont(r1, bold=True)
r2 = p.add_run('中性偏空'); setfont(r2, bold=True, color=ORANGE)
r3 = p.add_run('（机构持续向交易所转入分发：贝莱德存900BTC+17,511ETH进Coinbase、Mt.Gox转116BTC、Tether转204BTC、Hyperscale上周未购；美股AI风险偏好创新高—英伟达硅光量产/光模块普涨7~8%/软银"AI是互联网泡沫50倍"—但未提振币市=相对弱势；美伊地缘反复拉锯无新冲击=噪音）'); setfont(r3)
r4 = p.add_run('价格部分兑现'); setfont(r4, bold=True)

line('技术面：', bold=True)
line('盘口（合约）：', bold=True)
line('CVD下降　价格下降　资金费率横盘（为正值 0.0087）　持仓下降')
p = doc.add_paragraph()
ra = p.add_run('解读：'); setfont(ra, bold=True)
rb = p.add_run('利空'); setfont(rb, bold=True, color=RED)
rc = p.add_run('（日线放量233M/Delta-7M/CVD累积-45M、POC逐级下移71,430→69,354；1h CVD急跌-18.5K、OI自62K峰回落至57.88K=多头去杠杆离场+主动卖压主导破位。资金费率仍正=残余多头未完全投降→下方仍有去杠杆空间，下跌中继未竭）'); setfont(rc)

line('盘面：', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('日线级别　放量跌破上升平行通道下轨+0.5fib(71,464)，POC逐级下移至69,354，测试0.618日线支撑(68,758)　'))
setfont(p.add_run('利空'), bold=True, color=RED)
p = doc.add_paragraph()
setfont(p.add_run('小时级别　价跌破多头最后防守(71,000)/大级别共振支撑(72,000)/1H SMA20(70,751)，CVD深跌、OI回落、资金费率仍正　'))
setfont(p.add_run('利空'), bold=True, color=RED)

p = doc.add_paragraph()
setfont(p.add_run('趋势确认：'), bold=True)
setfont(p.add_run('空头趋势'), bold=True, color=RED)
setfont(p.add_run('（中短线·单边下行）'))

p = doc.add_paragraph()
setfont(p.add_run('日内支撑：68,500-68,800　　日内压力：70,000-70,400'), bold=True)
setfont(p.add_run('（下方延伸65,300-65,700；上方延伸71,400-71,800/4H 0.618=71,824）'), size=9, color=RGBColor(0x55,0x55,0x55))

line('策略：', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('中线主账户多单 @73,500（30%底仓·5x·1:3·左侧Taker）— 关键止损位 71,000 已被有效跌破（现价69,462）。'), bold=True, color=RED)
setfont(p.add_run('按既定状态机=触及上升通道下轨止损→止损出局，中线计划终结；浮亏 -5.5%（价格口径，确切-5.49%；5x账户级-27.5%）。Notion条目状态截至校准仍记"持仓中"——若尚未离场：严守纪律不再下移止损、不加仓、不抱"跌深反弹解套"侥幸（宪法：亏损砍短 盈利放满）。第一/二/三层浮盈防守层(75,500/76,200/74,400)自始未激活。'))

doc.add_paragraph()
# ===== Maker =====
H('② Maker 计划（≥70 必挂 · 总评分 74）')
line('BTC（策略）：执行概率 60%（已执行 0%）　胜率 70%', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('反弹空：入场 70,000-70,400'), bold=True, color=RED)
setfont(p.add_run('（破位回踩 user支撑6.2转压力 + 1H SMA20 70,751 共振 = 最近且≥60%可达的高质量反抽空边缘）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上'))
line('止盈：68,700（TP1·≈0.618日线68,758下沿）减仓50%　/　TP2 67,200（下方流动性）')
line('止损：站稳 70,800 上方（=重夺1H SMA20 70,751/破位回踩失败=结构失效）')
line('浮盈防守计划：', bold=True)
line('　第一层：价格触及 69,300（1.5R）　设立4小时级别低点极点为止损 同时取消所有加仓策略')
line('　第二层：价格触及 69,000（2R）　设立保本损')
p = doc.add_paragraph()
setfont(p.add_run('注意事项：'), bold=True, color=ORANGE)
setfont(p.add_run('若价格（成交前）优先触及 68,700 则此策略取消（撤未成交挂单）'))
line('核心（开仓理由）：日线放量破位+1h CVD深跌+OI去杠杆=空头趋势中继；现价69,462距入场区70,000-70,400仅+0.8~1.4%（破位回踩user支撑6.2转压力+1H SMA20 70,751共振=高质量反抽空边缘，执行概率≈60%达宪法门槛）；TP1落0.618日线支撑上沿、R:R 1:2.5。挂单于边缘等待，价不触及不成交（绝不追价）。')
p = doc.add_paragraph()
setfont(p.add_run('取消价(68,700·成交前撤单)≠止损(70,800·成交后离场)。挂价取最近高质量且≥60%可达边缘70,000-70,400，而非更高71,400-71,800（后者距现价+2.8~3.4%可达<60%不达门槛）。'), color=RGBColor(0x55,0x55,0x55), size=9)
line('持仓事实校准：Maker 6/1做多700刀（入场71,000，由防守层1.5R=72,500、2R=73,000反推R=1,000）已止损出局·亏$11；6/2用户手写做多800刀=未开仓（独立稿不引用方向/理由）。当前Maker无实际持仓。', color=RGBColor(0x55,0x55,0x55), size=9)

doc.add_paragraph()
# ===== 后附 =====
H('③ 后附（系统内部备份·不进 Notion 正文）')
line('评分明细（总分 74 = 盘口 53 + 盘面 21）', bold=True)
line('盘口 53/70：价↓+量增(日线233-261M)+Delta负+CVD深负(-45M/-18.5K)=主动卖压趋势性下跌；OI↓(57.88K自62K峰)=多头去杠杆；资金费率仍正(0.0087)=多头未完全投降→下跌中继（非极端C01/C02，手动高位）。')
line('盘面 21/30：接近度6（破多头最后防守/共振、临0.618日线支撑对空位置偏低）+流动性掠夺8（扫破71,000多头防守流动性+放量破位）+SMA20 5（全周期空头排列）+量价3（放量下跌齐确认）+斐波趋势线2（破上升通道+0.5fib、测0.618）。')
line('总分 74 ≥70 → 必挂 Maker（方向偏空·盘口定，挂价=最近高质量且≥60%可达边缘70,000-70,400）。', bold=True)
line('五源支撑', bold=True)
line('① BlockBeats(19:15)：分发延续—贝莱德存900BTC+17,511ETH进Coinbase、Mt.Gox转116BTC、Tether转204BTC、Hyperscale上周未购；risk-on（英伟达硅光量产、光模块AAOI/LITE+7~8%、软银50倍论、HYPE创新高）未传导币市；地缘反复拉锯=噪音；老虎国际6/12停境内新开仓(券商监管非crypto)。中性偏空·部分兑现。')
line('② 日线footprint(Exo)：现价69,354。6/02 Vol233M/Delta-7M/CVD-45M/POC69,354/H-L2094；6/01 Vol261M/Delta-17M/CVD-38M/POC71,430/H-L3394.9。POC逐级下移、CVD累积深负、连续放量=趋势性向下突破延续。')
line('③ Coinglass 1h(Bybit)：价69,428↓/CVD-18.5K↓(右沿急跌)/资金费率0.0087(正)/OI57.88K↓(自62K峰回落)=多头去杠杆离场+主动卖压加剧、残余多头未投降。')
line('④ FedWatch：6/17不变98.4%（1日前99.6%/1周前98.7%/1月前93.3%）、降息1.6%微升、加息0%→macro中性（无宽松预期）。')
line('⑤ TradingView 日/4H/1H/15m：日线-2.72%收69,470、低69,324，破上升通道下轨+0.5fib(71,464)、测0.618(68,758)。4H/1H价已跌穿多头最后防守(71,000)/大级别共振支撑(72,000)/0.618(71,824)/SMA20(70,751)，全空头排列。15m手绘：压力6.2 71,400-71,700、支撑6.2 70,000-70,400(已破→回踩转压力)。两层收口利空。把关：追空在69,462低位非高质量→挂价上移至70,000-70,400破位回踩反抽带。')
line('晚间复盘（review）', bold=True)
line('主账户：中线多单@73,500关键止损71,000今被有效跌破→按系统应止损出局；浮亏-5.5%（价格口径）。教训：5/28左侧Taker抄底底仓，价自entry持续下行、浮盈防守层从未激活=一笔"位置判断与趋势背离"的中线亏损单，复盘核对是否符合"非系统不做/入场位置要求极高"。')
line('Maker：6/1做多700刀已止损出局·亏$11（昨台账误记"持仓中"今订正）；6/2用户手写做多800刀=未开仓（独立稿不引用）。系统独立今晚=反弹空（与用户手写做多方向相反，未对照引用）。自控/心力/50笔结晶=用户自填模块（系统不臆造）。')

out = r'C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-02_晚间日报.docx'
doc.save(out)
print('SAVED', out)
