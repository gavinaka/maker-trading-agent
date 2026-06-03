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

p = doc.add_paragraph()
r = p.add_run('2026-06-03 早间日报（系统独立稿）')
setfont(r, size=16, bold=True, color=RGBColor(0x00,0x00,0x00))
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

line('门禁 6/3＝可交易（身体正常/情绪平静/节奏顺/结果依赖无）；唯一警示＝连续止损数 2（逼近≥3锁定线→降频谨慎，未触发停牌）。心力正常无收缩。总评分 74（盘口52+盘面22）≥70 → 必挂 Maker 单于高质量边缘。现价 66,748。', color=RGBColor(0x55,0x55,0x55), size=9)

# ===== 正文 =====
H('① 日报正文')
line('不能做：（追）做空', bold=True, color=RED)
p = doc.add_paragraph()
r1 = p.add_run('基本面：'); setfont(r1, bold=True)
r2 = p.add_run('中性偏空'); setfont(r2, bold=True, color=ORANGE)
r3 = p.add_run('（地缘伊朗强硬延续——美国务卿"不以解除对伊制裁换霍尔木兹通航"、冲突进入第4个月，较6/2"和谈一周内达成"转回强硬；美联储主席沃什任命2名保守派顾问推改革=鹰派；降息预期月内大幅price out。行业：Garrett Jin 1268BTC 5x多单浮亏超1150万、麻吉加仓做多周亏超百万=多头被套）'); setfont(r3)
r4 = p.add_run('价格部分兑现'); setfont(r4, bold=True)
r5 = p.add_run('（BTC自~77k暴跌至66.7k）'); setfont(r5)

# 基本面配图（BlockBeats 快讯卡）
from docx.shared import Inches
for _img in ['2026-06-03_1_fed.png','2026-06-03_2_iran.png','2026-06-03_3_longs.png']:
    _p = doc.add_paragraph(); _p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _p.add_run().add_picture(r'C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\\'+_img, width=Inches(5.2))

line('技术面：', bold=True)
line('盘口（合约）：', bold=True)
line('CVD下降　价格下降　资金费率上升（为正值）　持仓横盘')
p = doc.add_paragraph()
ra = p.add_run('解读：'); setfont(ra, bold=True)
rb = p.add_run('利空'); setfont(rb, bold=True, color=RED)
rc = p.add_run('（6/2放天量678M破位+CVD累积深负持续创低+主动卖压不竭+资费仍正=残余多头未投降=下跌中继；唯6/3早盘砸至日线POC 66,666后微现正Delta，关注超卖反弹）'); setfont(rc)

line('盘面：', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('日线级别　暴跌破上升平行通道下轨+0.618斐波，SMA20/200下方空头排列，现价砸落日线POC 66,666　'))
setfont(p.add_run('利空'), bold=True, color=RED)
p = doc.add_paragraph()
setfont(p.add_run('小时级别　1H/4H全空头排列，SMA20向下并跌穿68,300/69,100，前POC 67,000转为头顶压力　'))
setfont(p.add_run('利空'), bold=True, color=RED)

p = doc.add_paragraph()
setfont(p.add_run('趋势确认：'), bold=True)
setfont(p.add_run('空头趋势'), bold=True, color=RED)
setfont(p.add_run('（单边）'))

p = doc.add_paragraph()
setfont(p.add_run('日内支撑：65,800-66,300　　日内压力：67,000-67,600'), bold=True)

line('策略：', bold=True)
line('中线主账户：5/28做多@73,500（底仓30%·5x·1:3·左侧Taker）已触发第三层防守计划、止损出局@68,000（价格口径约-7.5%、PCT 8%、亏损），中线计划本轮终结·现无持仓。状态机＝现金观望，不逆势抄底新中线仓；待基本面与盘面共振企稳、出现高质量入场信号再重建。连续止损2笔，保持纪律、严控敞口。')

doc.add_paragraph()
# ===== Maker =====
H('② Maker 计划（≥70 必挂 · 反弹空）')
line('BTC（策略）：执行概率 60%（已执行 0%）　胜率 65%', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('反弹空：67,200-67,600'), bold=True, color=RED)
setfont(p.add_run('（破位的前POC 67,000 + 1H SMA20 下沿 = 最近的高质量反抽阻力带，现价仅需+0.7~1.3%、≥60%可达）　持仓 700 刀　Binance　左侧　盈亏比 1:2.5 以上'))
line('止盈：65,400（TP1·+2R）减仓50%　/　64,400（TP2·+3R）')
line('止损：站稳 68,400 上方（有效突破1H SMA20+前结构=反抽空失效；单笔约1.5%，<3%）')
line('浮盈防守计划：', bold=True)
line('　第一层：价格首次触及 65,900（+1.5R）　设立4小时级别低点为止损、取消所有加仓')
line('　第二层：价格触及 65,400（+2R）　减仓50% 同时设保本损')
p = doc.add_paragraph()
setfont(p.add_run('注意事项：'), bold=True, color=ORANGE)
setfont(p.add_run('若价格优先触及 65,400（下行目标自行兑现、反抽空机会失效）则此策略取消（撤未成交挂单）'))
line('核心（开仓理由）：4日瀑布式破位后砸至日线POC 66,666，下跌中继未竭（CVD深跌+多头被套未投降+资费仍正）；价反抽至67,200-67,600（破位前POC/1H SMA20下沿）遇压顺势做空。单挂边缘等待、价不到不成交（绝不追价）。')
p = doc.add_paragraph()
setfont(p.add_run('⚠️ 执行概率＝价格击中挂单区间的概率（限价单成交概率）·宪法≥60%。'), bold=True, color=ORANGE, size=9)
setfont(p.add_run('现价66,748距入场下沿67,200仅+0.7%、距上沿67,600约+1.3%，且砸至日线POC后超卖、反抽有燃料→可达≈60%。取消价(65,400·成交前撤单)≠止损(68,400·成交后离场)。'), color=RGBColor(0x55,0x55,0x55), size=9)
line('持仓事实校准：主账户中线多单已止损出局@68,000（无持仓）；Maker 6/1做多700刀已平仓、6/2手写做多800刀挂单(取消价71,400)随暴跌至66.7k已失效，当前 Maker 无实际持仓。', color=RGBColor(0x55,0x55,0x55), size=9)

doc.add_paragraph()
# ===== 后附 =====
H('③ 后附（系统内部备份·不进 Notion 正文）')
line('评分明细（总分 74 = 盘口52 + 盘面22）', bold=True)
line('盘口 52/70：四维=CVD↓/价↓/资费上升(正)/OI横盘=放量破位+主动卖压持续+残余多头未投降的「下跌中继」组合(强空)；6/2放全周天量678M+最大波幅5228.7=抛售高潮。仅因现价砸至日线POC 66,666、6/3早盘微现正Delta(量极小)略减分→52。')
line('盘面 22/30：接近度6（现处日线POC、距上方67k压力极近）+流动性掠夺7（6/2天量破位扫下方止损）+SMA20 5（日/4H/1H全在下方且向下,满分）+量价3（放量下跌配合,满分）+斐波趋势线1（破通道下轨+0.618）。')
line('总分 74 ≥70 → 必挂 Maker（方向=空，挂价=高质量空头边缘且≥60%可达=67,200-67,600首压反抽带）。', bold=True)
line('五源支撑', bold=True)
line('① BlockBeats：Tier1地缘伊朗转强硬(不以制裁换通航/冲突第4月)+美联储沃什鹰派改革(取消双重使命仅控通胀+缩表)+降息预期消退；Tier2 Garrett Jin/麻吉等多头巨鲸普遍被套，ShapeShift巨鲸增持6688ETH/Loracle 2x多HYPE。中性偏空、部分兑现。')
line('② 日线footprint：POC逐级下移76314→71430(6/1)→69354(6/2)→66666(6/3)；CVD累积-70M→-85M→-79M；6/2放天量678M/Delta-15M/H-L5228.7=趋势性放量破位/抛售高潮；6/3早盘Vol11M/Delta+5.8M弱反抽迹象。强空延续。')
line('③ Coinglass 1h(Bybit)：价66,727↓/CVD-25.649K↓创低/资金费率0.0065(正·由0.003升向0.01区间)/OI57.939K(自62K峰回落后横盘略升=新仓进场)=主动卖压持续+残余多头未投降=下跌中继。')
line('④ FedWatch：6/17不变98.6%、降息1.4%、加息0%；降息概率1月前6.7%→现1.4%(月内大幅price out)，近1日0.4%→1.4%微升(暴跌后小幅避险)→macro中性偏紧。')
line('⑤ TradingView 日/4H/1H/15m：日线收66,779破通道下轨+0.618砸至日线POC 66,666；4H/1H全空排列、SMA20向下、跌穿68,300/69,100，前POC 67,000转压力；15m手绘压力(6.2)71,600-72,000、支撑(6.2)70,200-70,600均远在现价上方(全转头顶供给)。最近高质量反抽空边缘=67,200-67,600。两层收口利空。')
line('不能做推导', bold=True)
line('空头单边+价砸至日线POC 66,666低位→最易被收割侧=66,666低位右侧追空(4日瀑布后超卖,易遭短挤/反弹反包)。禁「追做空」(仅禁右侧)；反抽至67,200-67,600的左侧反应空(=本Maker)、POC企稳的左侧低多反包均不禁。')

out = r'C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-03_早间日报.docx'
doc.save(out)
print('SAVED', out)
