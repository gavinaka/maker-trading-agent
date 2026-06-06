# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt, RGBColor, Inches
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

p = doc.add_paragraph()
r = p.add_run('2026-06-05 早间日报（系统独立稿）')
setfont(r, size=16, bold=True, color=RGBColor(0x00,0x00,0x00))
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

line('门禁 6/5＝可交易（身体正常·平静·节奏顺·连续止损0），但备注「工作团建（宿醉）身体比较疲惫」；心力最新 6/4＝专注0/消耗10/收缩机制（团建）→ 降频谨慎日、挂单门槛从严。总评分 72（盘口50+盘面22）≥70 → 必挂 Maker。现价 61,470（1H 61,459/15m 61,532/4H 61,414/日线 61,470/Coinglass 61,105/Exo 61,497）。', color=RGBColor(0x55,0x55,0x55), size=9)

# ===== 正文 =====
H('① 日报正文')
line('不能做：（追）做空', bold=True, color=RED)
p = doc.add_paragraph()
r1 = p.add_run('基本面：'); setfont(r1, bold=True)
r2 = p.add_run('中性偏空'); setfont(r2, bold=True, color=ORANGE)
r3 = p.add_run('（价格续破位——BTC跌破6.2万（24h-3.73%）、ETH跌破1700，过去24h全网爆仓7.92亿、多单爆仓6.11亿=多头继续被爆；ZEC因Orchard伪造漏洞24h暴跌39.5%山寨黑天鹅、BIT关联巨鲸12万ETH多头浮亏超6900万=risk-off。对冲项（企稳信号初现）=美BTC现货ETF昨日净流入320万（IBIT+4770万）终结连续13日流出、ETH现货ETF净流入1930万终结连续17日流出=机构连续撤离首次反转；24h爆仓7.92亿较前两日9.84亿/17亿明显缩量。今晚20:30非农，预期新增仅约8.5万明显低于前值=偏鸽，但通胀粘性下联储或鹰派双向）'); setfont(r3)
r4 = p.add_run('价格部分兑现'); setfont(r4, bold=True, color=GREEN)

# 基本面配图（BlockBeats 快讯卡）
for _img in ['2026-06-05_1_btc.png','2026-06-05_2_etf.png','2026-06-05_3_nfp.png']:
    _p = doc.add_paragraph(); _p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _p.add_run().add_picture(r'C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\\'+_img, width=Inches(5.2))

line('技术面：', bold=True)
line('盘口（合约）：', bold=True)
line('CVD下降　价格下降　资金费率下降（接近0值）　持仓横盘')
p = doc.add_paragraph()
ra = p.add_run('解读：'); setfont(ra, bold=True)
rb = p.add_run('中性偏空'); setfont(rb, bold=True, color=ORANGE)
rc = p.add_run('（价格与CVD同步创新低=空头趋势确认、非背离、下跌中继；但资费自0.0092大幅回落至0.0021并偶现负值=本轮单边下跌中多头首次接近投降，叠加爆仓缩量+ETF转净流入，超卖反弹/反包风险显著升；OI横盘57.2K自低点回升=多空换手未单边离场。空头单边延续但临近超卖末段）'); setfont(rc)

line('盘面：', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('日线级别　6/5缩量192M（vs 6/4 513M）巨幅下跌后卖压衰减，价61,470破上升通道下轨+0.618斐波、跌穿日线POC 67,000、SMA200 74,885远在上方、全空排列　'))
setfont(p.add_run('利空'), bold=True, color=RED)
p = doc.add_paragraph()
setfont(p.add_run('小时级别　1H/4H全空、价砸穿所有均线、SMA20（1H 63,352/4H 65,690）向下并转头顶压力，15m跌破用户手绘支撑(6.4) 62,000-62,500、贴61.5k运行　'))
setfont(p.add_run('利空'), bold=True, color=RED)

p = doc.add_paragraph()
setfont(p.add_run('趋势确认：'), bold=True)
setfont(p.add_run('空头趋势'), bold=True, color=RED)
setfont(p.add_run('（单边·瀑布破位下行·临近超卖末段）'))

p = doc.add_paragraph()
setfont(p.add_run('日内支撑：59,600-60,100　　日内压力：62,400-63,000'), bold=True)

line('策略：', bold=True)
line('中线主账户：6/3接飞刀低多@67,000已止损出局、本轮中线计划再度终结，现金观望、0%仓。状态机＝不新增防守层；空头单边砸至61.5k、ETF虽现单日小额转流入但未确认持续、今晚非农未落地＝企稳证据不足，禁左侧接飞刀（连环左侧抄底教训），待ETF持续净流入+CVD背离+资费转负capitulation共振企稳再评估重建。')

doc.add_paragraph()
# ===== Maker =====
H('② Maker 计划（≥70 必挂 · 反弹空 · 降频谨慎）')
line('BTC（策略）：执行概率 60%（已执行 0%）　胜率 60%', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('反弹空：62,400-63,000'), bold=True, color=RED)
setfont(p.add_run('（跌破的用户支撑(6.4) 62,000-62,500转阻力 + 逼近1H SMA20 63,352 = 最近且≥60%可达的高质量反抽阻力带，现价61,470需+1.5~2.5%）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上'))
line('止盈：59,450（TP1·+2.5R）减仓50%　/　58,300（TP2·+3.4R）')
line('止损：站稳 64,000 上方（回补破位+站上1H SMA20 63,352并进压力(6.4)=反抽空失效；单笔约1.6%，<3%）')
line('浮盈防守计划：', bold=True)
line('　第一层：价格首次触及 60,750（+1.5R）　设立4小时级别K线极点为止损、取消所有加仓')
line('　第二层：价格触及 59,450（+2.5R）　减仓50% 同时设保本损')
p = doc.add_paragraph()
setfont(p.add_run('注意事项：'), bold=True, color=ORANGE)
setfont(p.add_run('若价格优先触及 59,400（下行目标自行兑现、未反抽至入场区）则此策略取消（撤未成交挂单）'))
line('核心（开仓理由）：空头单边延续、价与CVD同步创新低=趋势确认，价反抽至62,400-63,000（跌破的支撑6.4转阻力/逼近1H SMA20 63,352）遇压顺势做空。⚠️降频谨慎日（团建宿醉疲惫+昨日收缩机制）+资费接近0/爆仓缩量/ETF转流入=超卖反弹风险升，严格只挂边缘左侧反应、不主动追空。单挂边缘等待、价不到不成交（绝不追价）。')
p = doc.add_paragraph()
setfont(p.add_run('⚠️ 执行概率＝价格击中挂单区间的概率（限价单成交概率）·宪法≥60%。'), bold=True, color=ORANGE, size=9)
setfont(p.add_run('现价61,470距入场下沿62,400约+1.5%、距上沿63,000约+2.5%，破位支撑flip+SMA20共振有反抽燃料→可达≈60%。取消价(59,400·成交前撤单)≠止损(64,000·成交后离场)。'), color=RGBColor(0x55,0x55,0x55), size=9)
line('持仓事实校准：主账户6/3中线低多@67,000已止损出局（无持仓）；Maker 最新6/4做多800刀挂单未开仓（属用户手写未开仓计划、独立稿不引用），当前 Maker 无实际持仓。两账户均空仓。', color=RGBColor(0x55,0x55,0x55), size=9)

doc.add_paragraph()
# ===== 后附 =====
H('③ 后附（系统内部备份·不进 Notion 正文）')
line('评分明细（总分 72 = 盘口50 + 盘面22）', bold=True)
line('盘口 50/70：四维=CVD↓(创新低-36.376K)/价↓(创新低61,105)/资费下降接近0值(0.0021自0.0092大幅回落·偶现负)/OI横盘(57.2K自低点回升)=价与CVD同步创新低的「空头趋势确认」组合(非背离·强空中继)。未给更高分因资费本轮单边首次接近0/偶负=多头首次接近投降，叠加24h多单爆仓6.11亿、爆仓规模较前两日缩小、ETF转净流入→超卖反弹/反包概率显著升、追空动能衰减→50。')
line('盘面 22/30：接近度6（价刚破支撑6.4 62,000-62,500、距下一支撑60,000/59,608约-2.4%、距反抽阻力62,400-63,000约+1.5~2.5%）+流动性掠夺7（破62k扫多单止损、24h多单爆6.11亿）+SMA20 5（1H/4H/日全在下方且向下,满分）+量价2（6/5缩量192M下跌、卖压衰减,2/3）+斐波趋势线2（破上升通道下轨+0.618,满分）。')
line('总分 72 ≥70 → 必挂 Maker（方向=空，挂价=高质量空头边缘且≥60%可达=62,400-63,000反抽带；降频谨慎只挂边缘左侧反应）。', bold=True)
line('五源支撑', bold=True)
line('① BlockBeats：利空主导(价格层)=BTC破6.2万(现报61,470·24h-3.73%)/ETH破1700(24h-5.2%)/24h全网爆仓7.92亿(多单6.11亿/空单1.81亿·18.5万人·最大单笔Binance BTCUSDT 1181万)/ZEC因Orchard伪造漏洞24h暴跌39.5%报369(山寨黑天鹅risk-off)/BIT关联巨鲸12万ETH多头浮亏超6900万。企稳信号(对冲)=美BTC现货ETF昨日净流入320万(IBIT+4770万)终结连续13日流出、ETH现货ETF净流入1930万终结连续17日流出=机构撤离首次反转；24h爆仓7.92亿较6/4的9.84亿/6/3的17亿明显缩量。macro=今晚20:30非农预期新增仅约8.5万(高盛6万/安永5万/先锋2万)明显低于前值=偏鸽但通胀粘性鹰派双向；美伊下一轮会谈临近。噪音=AI链上攻击频率升2.8倍、黄仁勋谈韩国机器人。中性偏空、部分兑现。')
line('② 日线footprint(Exo)：6/5(进行中)Vol192M(缩量vs6/4 513M)/Delta-24M(负)/CVD-161M(深负·自-137M续创低)/POC62,682(自63,522逐级下移)/H-L2,891.4；现价61,497破当日POC下方。卖方仍主导、POC逐级下移、CVD累积深负，但6/5量能显著收缩=强空延续但卖压边际衰减。')
line('③ Coinglass 1h(Bybit)：价61,105↓创新低/CVD-36,376K↓创新低/资金费率0.0021(自0.0092大幅回落·接近0值·6/4附近偶现负柱=多头首次接近投降)/OI57.185K(横盘·自低点回升)=价与CVD同步创新低=趋势确认(非背离)·下跌中继，但资费接近0=超卖末段信号初现。')
line('④ FedWatch：6/17不变96.4%、降息(ease)3.6%、加息0%；降息概率1周前0.4%→现3.6%(边际大幅升温)，1日前2.7%→3.6%→macro中性微偏鸽(随弱就业预期回暖)，今晚非农为关键变量。')
line('⑤ TradingView 日/4H/1H/15m：日线61,470破通道下轨+0.618+POC67,000，SMA200 74,885远上·6/5缩量；4H61,414全空·SMA20 65,690向下·POC67,000头顶；1H61,459砸穿所有均线·SMA20 63,352转阻力；15m61,532跌破用户支撑(6.4)62,000-62,500，压力(6.4)64,000-65,000、支撑(6.3)65,300-65,800、压力(6.3)67,500-68,500全在上方，下方60,000整数关+59,608日线低点线。最近高质量反抽空边缘=62,400-63,000。两层收口利空。')
line('不能做推导', bold=True)
line('空头单边+价砸至新低约61,500→最易被收割侧=61k新低区右侧追空(资费本轮首次接近0/偶负、24h多单已爆6.11亿、ETF转净流入=临近超卖capitulation，再创新低后追空易遭短挤/反弹反包)。禁「追做空」(仅禁右侧)；反抽至62,400-63,000的左侧反应空(=本Maker)、企稳后的左侧低多反包均不禁。')

out = r'C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-05_早间日报.docx'
doc.save(out)
print('SAVED', out)
