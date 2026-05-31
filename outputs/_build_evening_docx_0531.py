# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn

doc = Document()
st = doc.styles['Normal']
st.font.name = 'Microsoft YaHei'
st.font.size = Pt(10.5)
st._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

def H(txt, lvl=1, color=None):
    h = doc.add_heading(level=lvl)
    r = h.add_run(txt)
    r.font.name = 'Microsoft YaHei'
    r._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    if color:
        r.font.color.rgb = RGBColor(*color)

def P(txt, bold=False, color=None):
    p = doc.add_paragraph()
    r = p.add_run(txt)
    r.font.name = 'Microsoft YaHei'
    r._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    r.bold = bold
    if color:
        r.font.color.rgb = RGBColor(*color)
    return p

RED=(0xC0,0x00,0x00); ORANGE=(0xC0,0x60,0x00)

H('2026-05-31 晚间日报（链B · 周末）｜系统独立稿', 0)
P('总评分 57 / 100（盘口 45 + 盘面 12）→ 未达开仓门槛（观望）', bold=True, color=RED)
P('本稿为系统独立判断，未参照任何手写日报。')

H('一、主账户（中线仓 · 防守层状态机）', 1)
P('持仓中｜做多 BTC @均价 73,500（底仓 30%）｜5x｜$1,000｜盈亏比 1:3｜Taker 左侧', bold=True)
P('（来源：主库实际持仓校准，状态=持仓中；已纠正台账 5/29–30 误用的 short@79150 旧单）')
P('现价 ~73,910 → 浮盈约 +3%（×5，贴近成本小幅浮盈）')
P('系统建议：保持底仓 30%，不新增、不止盈 —— 总分未达门槛；价在 73.5–74k 窄区横盘，未触任何加/减仓位；卖压衰竭但反弹未确认，无理由动仓。', bold=True)
P('防守层（沿用计划）：触 75,500→日线低点止损+取消加仓｜触 76,200→保本损｜触 74,400→日线低点止损+取消加仓。')
P('止盈 78,000（TP1）减半｜止损 有效跌破 71,000（上升通道下轨）。')
P('风险：基本面偏空+价在 SMA20 下方，做多底仓逆短期结构；若 1H 破 73,222/73,000，警惕跌向 72,516/通道下轨，第三层防守（74,400）已临近。', color=ORANGE)

H('二、Maker（系统独立判断）', 1)
P('今日结论：观望，不开仓（总分 57 < 70，未达 Maker 门槛）。', bold=True, color=RED)
P('方向偏空：基本面偏空（ETF 抛压）+ 价处下降结构/SMA20 下方 + 盘口多头低量加杠杆（拥挤侧）→ 反弹做空胜率结构优于追多。')
P('若达标，高质量空头边缘 = 反弹至 74,800–75,300：叠加 4H/1H 空头流动性 74.75–75.08k + 15m 多空分界/强支撑 75,778 下方 + 日线 SMA20 压制路径，是卖压可能重新介入的共振阻力带。', bold=True)
P('现价 73,910 不在该边缘：处 15m 窄区（73,600–74,772）中下部、贴 73,600 支撑上方 —— 对做空是错误的低位一端，入场位置不优 → 即便方向对也须等反弹至边缘。')
P('失效条件：价向下先破 73,600→73,222→73,000，则反弹空逻辑作废（结构转弱，改看下沿）。')
P('不能做：（追）做多 —— 系统推导：多头短期低量加杠杆（Funding 0.0075↑/OI 升/73–74k 新增约 3 亿杠杆多头），但价未突破、基本面偏空、价在 SMA20 下方下降结构中；多头为被堆叠杠杆的拥挤侧，偏空环境追多易被挤压。', bold=True, color=ORANGE)

H('三、基本面（主线 + 价格兑现）', 1)
P('主线①资金面：现货 BTC ETF 本周净流出 14.2 亿（连续第 2 周大额流出），一度探 72,500。')
P('主线②地缘：美伊和平协议受阻 —— 伊朗议长强硬「保障伊朗人民权利前不批准任何协议」→ risk-off。')
P('价格兑现：已部分兑现 —— BTC 已从 76k+ 跌至 72.5–74k；70k 现货逢低买盘吸收部分抛压但不足以扭转下行。', bold=True)
P('利多侧：73–74k 新增约 3 亿杠杆多头押注反弹；订单簿买卖比转正。')
P('情绪：Polymarket「年内回 10 万」33%（5/10 为 49%）；摩根大通 CEO 警告稳定币收益模式或爆雷。')
P('聚合：偏空（利空 5 / 利多 2 / 中性 1）。', bold=True, color=RED)
P('macro/FedWatch：6/17 维持不变 99.6%；双尾收敛（去鹰去鸽）→ 中性。CME 年内加息概率回落至 48%（偏鹰远期，近月无变数）。')

H('四、盘面（日线层 + 小时层）', 1)
P('日线层：上升通道未破，但价跌破 SMA20（76,829）回踩通道中下沿，73.5–74k 企稳；footprint 卖压衰竭（Delta 连2日转正、波幅 538.6 全周最窄）。大趋势多/短期破均线+基本面偏空 → 偏空（中性偏空）', bold=True)
P('小时层：4H 价处 0.5fib（73,932）中部；1H 自 72,500 沿 SMA20 缓升至 73,900–74,200 测下降趋势线（回抽）；15m 价夹 73,600（POC支撑）与 74,772（压力）窄区，上压空头流动性 74.75–75.08k + 多空分界 75,778，下托 73,000/72,516。低量震荡、上方流动性未扫 → 中性', bold=True)

H('五、评分明细（70 + 30 = 57）', 1)
P('盘口 70 → 45：横盘微涨 / Delta +8.2M（卖压衰竭）/ CVD 日 -342k·1h 回升 / Vol 24M（全周最低）/ Funding 0.0075↑ / OI ~55K 稳 / POC 74,046 / 波幅 538.6。低量横盘+多头低量加杠杆，量能不支持趋势、方向未定 → 45。')
P('盘面 30 → 12：支撑压力接近度 4/10（窄区中下部，距做空边缘 74.8–75.3k 约1.2–1.9%）｜流动性掠夺 3/10（上方 74.75–75.08k 未扫）｜SMA20 3/5（价在日线均线下方且下行）｜量价 1/3（缩量）｜斐波趋势线 1/2（0.5fib+测下降趋势线）。')

H('六、五源支撑', 1)
P('① BlockBeats：ETF 本周净流出 14.2 亿（连2周）；73–74k 新增约 3 亿杠杆多头；伊朗拒批协议；CME 年内加息 48%；Polymarket 年内10万 33%。')
P('② Exocharts 日线：5/31 Vol 24M / Delta +8.2M / CVD -342k / POC 74,046 / 波幅 538.6（全周最窄）。')
P('③ Coinglass 1h：价 73,899（+0.03%）/ CVD 回升 -13.08K / Funding 0.0075↑ / OI 55.04K 稳。')
P('④ FedWatch：6/17 不变 99.6%；双尾收敛 → 中性。')
P('⑤ TradingView（4级）：日线 通道未破但破 SMA20 回踩；4H 价 0.5fib 中部；1h 沿 SMA20 缓升测下降趋势线；15m 价夹 73,600–74,772 窄区，上方空头流动性 74.75–75.08k + 多空分界 75,778。')

H('交易宪法对照', 1)
P('1.非系统不做 ✅（57<70 观望）  2.非 Maker 不开 ✅（今日不开仓）  3.违规即封禁 ✅')
P('4.浮盈≥+1.5R 激活防守 —— 主账户 +3% 未达 1.5R  5.亏损砍短盈利放满 ✅  6.单笔止损 3% 内 ✅')

out = r'C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-05-31_晚间日报.docx'
doc.save(out)
print('SAVED', out)
