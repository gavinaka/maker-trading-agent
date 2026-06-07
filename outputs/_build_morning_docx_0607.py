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
r = p.add_run('2026-06-07 早间日报（系统独立稿 · 观望样本日）')
setfont(r, size=16, bold=True, color=RGBColor(0x00,0x00,0x00))
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

line('门禁 6/7＝可交易（身体正常·情绪平静·节奏顺·连续止损0·结果依赖无）＝正常可交易日；心力最新6/4＝消耗10/收缩机制（团建），6/5–6/7未填，早间以当日门禁为准→6/7无收缩、正常。总评分 68（盘口50+盘面18）＜70 → 观望·不挂单。现价 61,303（15m 61,303/1H 61,283/4H 61,320/日线 61,295/Coinglass 61,245/Exo POC 61,254）。两账户均空仓。', color=RGBColor(0x55,0x55,0x55), size=9)

# ===== 正文 =====
H('① 日报正文')
p = doc.add_paragraph()
setfont(p.add_run('不能做：'), bold=True)
setfont(p.add_run('（追）做空'), bold=True, color=RED)

p = doc.add_paragraph()
setfont(p.add_run('基本面：'), bold=True)
setfont(p.add_run('中性偏空'), bold=True, color=ORANGE)
setfont(p.add_run('（Tier1 地缘＋宏观利空主导——美伊战争满100天、中东战火小规模重燃（伊朗再袭美军第五舰队、以军黎巴嫩南部2士兵阵亡、革命卫队对4艘油轮开火）、停火脆弱（Polymarket 6月底前永久和平仅16%）；degentrading预警韩股「南方两倍做多海力士」周一约200万股强制卖压、半导体极度看空＝传统市场risk-off传染；中国央行连续第19个月增持黄金＝避险延续；加密恐慌与贪婪指数12「极度恐慌」（连续）。对冲项（反弹燃料）＝某巨鲸近24h囤约1723枚BTC（约1.0558亿美元）、ETH OG巨鲸均价1563抄底35723枚ETH、BTC回升突破61,000（24h跌幅收窄至0.53%）、Tom Lee称美股牛市稳固）'))
setfont(p.add_run('价格部分兑现'), bold=True, color=GREEN)

# 基本面配图（BlockBeats 快讯卡）
for _img in ['2026-06-07_1_geo.png','2026-06-07_2_risk.png','2026-06-07_3_whale.png']:
    _p = doc.add_paragraph(); _p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _p.add_run().add_picture(r'C:\Users\31702\Desktop\Trading-System-Code\outputs\blockbeats\\'+_img, width=Inches(5.2))

line('技术面：', bold=True)
line('盘口（合约）：', bold=True)
line('CVD上升　价格横盘　资金费率横盘（接近0值·为正值）　持仓上升', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('解读：'), bold=True)
setfont(p.add_run('中性偏多'), bold=True, color=ORANGE)
setfont(p.add_run('（CVD自-40K回补至-37,008K＝本轮首次明显回升、不再续创新低；日线footprint 6/7 Delta自6/6的-29M转正+15M＝自6/1以来首次买盘边际回归；OI自57K回升至58.0K＝杠杆边际回补；POC连续上移59,778→60,798→61,254＝企稳重心抬升；叠加6/6探59,200即反包（扫6万下方止损后V反＝空头流动性掠夺）、守6万、价反抽站上61k＝卖压衰竭·买方边际回归·看涨背离自酝酿转确认中。但CVD累积仍-171M深负＝买方尚未真正接管，一日Delta转正不足确认反转，逆势企稳早期）'))

line('盘面：', bold=True)
p = doc.add_paragraph()
setfont(p.add_run('日线级别　价61,295破上升通道下轨+0.618斐波、跌穿日线POC 67,000、SMA20 71,657/SMA200远在上方、全空排列，RSI极度超卖、6/7极度缩量（Exo Vol 78M）守6万手绘支撑（下方58,000/52,800）　'))
setfont(p.add_run('中性偏空'), bold=True, color=ORANGE)
p = doc.add_paragraph()
setfont(p.add_run('小时级别　1H价61,283站上SMA20 60,854并走平微翘、4H SMA20 62,088向下转头顶近压、15m自6/6低59,200反抽后于60,000-61,700收敛横盘、刚冲61,714回落坐15m上升趋势线（≈60,800-61,000）　'))
setfont(p.add_run('中性'), bold=True, color=ORANGE)

p = doc.add_paragraph()
setfont(p.add_run('趋势确认：'), bold=True)
setfont(p.add_run('空头趋势'), bold=True, color=RED)
setfont(p.add_run('（单边·瀑布末段转底部企稳整理）'))

p = doc.add_paragraph()
setfont(p.add_run('日内支撑：'), bold=True)
setfont(p.add_run('60,000-60,400'), bold=True, color=GREEN)
setfont(p.add_run('　　日内压力：'), bold=True)
setfont(p.add_run('61,700-62,200'), bold=True, color=RED)

line('策略：', bold=True)
line('中线主账户：6/3接飞刀低多@67,000已止损出局、本轮中线计划已终结，现金观望、0%仓。状态机＝不新增防守层；盘口企稳信号增强（Delta转正＋CVD回补＋OI回升＋POC上移＋守6万反包）但大结构仍强空、极度超卖、CVD累积深负＝企稳证据不足以确认反转，禁左侧接飞刀（连环左侧抄底教训）；待价站稳62k＋CVD转正＋日线放量企稳共振，再评估中线重建。')

doc.add_paragraph()
# ===== Maker =====
H('② Maker 计划（总评分 68 ＜ 70 · 观望 · 不挂单）')
line('BTC（策略）：总评分 68（盘口50+盘面18）＜70 门槛　观望·不挂单（执行概率 — / 已执行 0% / 胜率 —）', bold=True)
line('触发门槛：总分≥70才挂Maker单。当前68，且无「既高质量又≥60%可达」的最近边缘 → 观望。')
p = doc.add_paragraph()
setfont(p.add_run('假设性方向倾向（仅记录·不挂单）：'), bold=True)
line('偏多（低多/反弹做多）：若价回踩60,000-60,400高质量支撑（6万整数关＋15m区间下沿＋上升趋势线）并伴CVD持续回补、Delta维持转正→企稳反弹做多。当前现价61,303距该支撑约-1.5%（可达概率<60%）＋逆势接飞刀风险（CVD累积仍深负）→不挂。')
line('偏空（反弹空）已弱化：守6万＋CVD回补＋Delta转正使「反抽空」thesis减弱，仅在价反抽至61,700-62,200／62,200-62,800（6/4破位支撑转阻力带）遇明确遇阻＋CVD重新走弱时才考虑左侧反应空，当前不成立。')
line('升级条件：', bold=True)
line('第一档：价站稳62k上方＋CVD转正＋OI放量回补→升级低多确认（届时重评分挂单）；或价反抽至62,200-62,800遇阻＋CVD转弱→反弹空重新成立。')
line('第二档：在≥70基础上，挂价须为≥60%可达的高质量边缘（执行概率达宪法门槛），R:R≥1:2.5、胜率≥70%。')
p = doc.add_paragraph()
setfont(p.add_run('注意事项：'), bold=True, color=RGBColor(0x6A,0x00,0x99))
setfont(p.add_run('极度超卖（恐慌指数12）＋守6万＋6/6探59,200即反包＝右侧追空最易被反弹反包，严格不在6万-61k区右侧追空。'))
p = doc.add_paragraph()
setfont(p.add_run('⚠️ 今日为纯评分未达70门槛的观望'), bold=True, color=RGBColor(0x6A,0x00,0x99))
setfont(p.add_run('（门禁开启正常·非门禁阻断、非风控阻断、非连续止损降频）；仅因盘面无高质量机会，不臆造挂单凑门槛（准确性优先）。'))
line('持仓校准：主账户6/3低多@67,000已止损出局现空仓0%（6/4-6/7无新仓）；Maker最新6/4做多800刀状态＝未开仓（挂单未成交·用户手写未开仓计划），当前Maker无实际持仓。两账户均空仓。系统独立判观望，持仓状态仅作事实校准、未参照用户判断。', color=RGBColor(0x55,0x55,0x55), size=9)

doc.add_paragraph()
# ===== 后附 =====
H('③ 后附（系统内部备份·不进 Notion 正文）')
line('评分明细（总分 68 = 盘口50 + 盘面18）→ ＜70 观望不挂', bold=True)
line('盘口 50/70：四维=CVD上升(自-40K回补至-37,008K·首次明显回升)/价格横盘(低位企稳·小幅反抽站上61k)/资金费率横盘接近0值(0.0002·为正值·极低)/持仓上升(58.0K自57K回补)=「CVD回补+价企稳+OI回升」卖压衰竭·买方边际回归组合(看涨背离自酝酿转确认中)。较6/6(45)上调5：Delta自-29M转正+15M、CVD首次回补、OI回升、POC连续上移=企稳信号增强。未给更高：CVD累积仍-171M深负(买方未接管)、一日Delta转正不足确认反转、逆势大结构强空、极度超卖。非C01/C02极端。')
line('盘面 18/30：接近度5（价61,303距日内支撑60,000-60,400约-1.5%、距日内压力61,700-62,200约+0.7~1.5%·处区间中上部）+流动性掠夺7（6/6探59,200反包=扫6万下方空头止损后V反·偏多）+SMA20 2（站1H SMA20 60,854上方但日线71,657/4H 62,088仍在上方·混合）+量价2（6/7极度缩量78M+价稳=下跌动能枯竭·健康企稳）+斐波趋势线2（坐15m上升趋势线+守6万整数关）。')
line('总分 68 ＜70 → 观望不挂（企稳信号增强但逆势early-stage、无≥60%可达高质量边缘，不臆造挂单凑门槛）。', bold=True)
line('五源支撑', bold=True)
line('① BlockBeats：Tier1利空主导（地缘+宏观）=美伊战争满100天、中东战火重燃（伊朗再袭美军第五舰队、以军黎巴嫩2士兵阵亡、革命卫队对4艘油轮开火、特朗普设60天和谈期限）、停火脆弱（Polymarket 6月底前永久和平16%/7月底28%）；degentrading预警韩股南方两倍做多海力士周一约200万股强制卖压（当日正常量40%·gamma越跌越卖）、EWY或175→145=半导体极度看空·风险传染；中国央行连续第19个月增持黄金（5月末2331.52吨）=避险；恐慌贪婪指数12极度恐慌（昨日亦12）。对冲（反弹燃料）=某巨鲸24h囤约1723枚BTC（约1.0558亿美元）、ETH OG巨鲸均价1563抄底35723枚ETH、BTC回升破61,000（24h-0.53%）、Tom Lee称美股牛市稳固。噪音=玻璃基板供应链、HyperionDeFi解押50万HYPE、智利破8800万美元加密洗钱网。中性偏空、部分兑现（BTC本轮已-30%·破61k回升企稳）。')
line('② 日线footprint(Exo·Bybit BTCUSD)：6/7(进行中·周日~10:30)Vol78M(极度缩量·才上午)/Delta+15M(自6/1以来首次转正·买盘边际回归)/CVD-171M(深负但自6/6 -186M首次回补+15M)/POC61,254(自59,778→60,798→61,254连续上移·企稳重心抬升)/H-L914.0(振幅极度收窄·横盘)。对比6/6(Vol272M/Delta-29M/CVD-186M/POC60,798/H-L2,047.8)=卖压衰竭·买方边际回归·企稳整理；唯CVD累积仍深负、买方尚未接管。')
line('③ Coinglass 1h(Bybit BTCUSDT)：价61,245(低位企稳·小幅反抽)/CVD-37,008K↑(自约-40K回补·首次明显回升)/资金费率0.0002(正·极低·接近0值)/OI58.002K(自约57K回升·杠杆边际回补)=价企稳+CVD回补+OI回升=买方边际回归，但CVD仍深负。')
line('④ FedWatch：6/17 FOMC维持利率(350-375)95.4%、降息(ease 325-350)4.6%、加息0.0%；降息概率NOW 4.6%(1日前2.8%/1周前0.4%/1月前5.4%·边际回升但仍压倒性维持)(数据截至6/6 09:01 CT)。距FOMC 6/17仅10天。macro中性偏空(高利率维持约95%·近期无加息·降息预期边际微升)。')
line('⑤ TradingView 日/4H/1H/15m：日线61,295破上升通道下轨+0.618斐波+POC67,000，SMA20 71,657远上、6/7极度缩量、RSI极度超卖、下方手绘支撑58,000/52,800；4H61,320全空·SMA20 62,088向下转头顶近压·POC66,774·下方手绘支撑58,957；1H61,283站上SMA20 60,854并走平微翘·上方POC67,000；15m61,303自6/6低59,200反抽后于60,000-61,700收敛横盘·刚冲61,714回落坐15m上升趋势线(≈60,800-61,000)，用户手绘6/4压力区64,800-65,400(远上)、支撑区62,200-62,800(已下破·转阻力带)，下方6万整数关+59,200(6/6低)+58,000。两层收口：日线中性偏空、小时中性(破位结构未反转但缩量企稳+15m上升趋势线托底=瀑布末段转底部整理)。')
line('不能做推导（回填）', bold=True)
line('盘口企稳偏多、价反抽站上61k、极度超卖(恐慌12)守6万、6/6探59,200即反包→最易被收割侧=6万-61k区右侧追空(再砸即遭反弹反包/短挤)。故不能做=（追）做空：仅禁右侧追空；反抽至61,700-62,800遇阻+CVD转弱的左侧反应空、企稳回踩6万的左侧低多反包均不禁。延续6/3/5/6不能做追空，今日企稳信号增强使追空更危险。')

out = r'C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-07_早间日报.docx'
doc.save(out)
print('SAVED', out)
