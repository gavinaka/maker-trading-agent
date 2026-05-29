# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

doc = Document()
style = doc.styles['Normal']
style.font.name = 'Microsoft YaHei'
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

for section in doc.sections:
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

def set_font(run, size=10.5, bold=False, color=None, italic=False):
    run.font.name = 'Microsoft YaHei'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = color

def add_title(text, sub=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    set_font(r, 18, True, RGBColor(0x1F, 0x3A, 0x5F))
    if sub:
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r2 = p2.add_run(sub)
        set_font(r2, 10, False, RGBColor(0x88, 0x88, 0x88))

def add_h2(text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    set_font(r, 14, True, RGBColor(0x1F, 0x3A, 0x5F))
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)

def add_h3(text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    set_font(r, 11.5, True, RGBColor(0x2C, 0x5A, 0x8C))
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)

def add_para(segs):
    p = doc.add_paragraph()
    for text, bold in segs:
        r = p.add_run(text)
        set_font(r, 10.5, bold)
    return p

def add_quote(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    r = p.add_run(text)
    set_font(r, 9.5, False, RGBColor(0x66, 0x66, 0x66), italic=True)

def add_bullet(segs):
    p = doc.add_paragraph(style='List Bullet')
    for text, bold in segs:
        r = p.add_run(text)
        set_font(r, 10.5, bold)

def add_hr():
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = pPr.makeelement(qn('w:pBdr'), {})
    bottom = pBdr.makeelement(qn('w:bottom'), {
        qn('w:val'): 'single', qn('w:sz'): '6',
        qn('w:space'): '1', qn('w:color'): 'BFBFBF'
    })
    pBdr.append(bottom)
    pPr.append(pBdr)

def add_table(headers, rows, highlight_last_col=False):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = 'Light Grid Accent 1'
    hdr = table.rows[0].cells
    for i, t in enumerate(headers):
        hdr[i].text = ''
        p = hdr[i].paragraphs[0]
        r = p.add_run(t)
        set_font(r, 10.5, True, RGBColor(0xFF, 0xFF, 0xFF))
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ''
            p = cells[i].paragraphs[0]
            r = p.add_run(str(val))
            set_font(r, 10)

# ===== 标题 =====
add_title('交易系统晚间日报（链 B 产出）',
          '2026-05-29  20:00 评分点  |  Trading-System v2026.5  |  output_agent')

add_quote('数据采集：BlockBeats（Chrome MCP 实时）、Exocharts（用户截图 Bybit BTCUSD 日线 Bid-Ask Profile）、Coinglass（用户截图 Bybit BTCUSDT 1h）、CME FedWatch（用户截图 17 Jun 2026 FOMC 利率概率）')
add_quote('数据完整度：4/4 ✅')

add_hr()

# ===== 一、主账户日报（晚间刷新）=====
add_h2('一、主账户日报（晚间刷新）')

p = doc.add_paragraph()
r = p.add_run('2026-05-29　20:00 评分点')
set_font(r, 12, True)

add_para([('不能做：', True), ('做多', False)])

add_para([
    ('基本面：', True),
    ('中性偏空（施密德 18:58 鹰派表态 + FedWatch 6 月加息概率近一日 0.6% → 1.1% 重定价 + Strategy 优先股股息压力 + 贝莱德 19:12 向 Coinbase 存入 2,448 BTC / 28,683 ETH）', False),
    ('价格已兑现部分', False),
])

add_h3('重要新闻（BlockBeats 实时抓取）')
news = [
    ('[19:36]', 'Raoul Pal：比特币等加密资产价值被低估（长期看多观点）'),
    ('[19:35]', 'Arca CIO：Strategy 每年付 15 亿美元优先股股息，最终可能被迫出售 BTC（Polymarket 给 90% 概率年底前抛售）'),
    ('[19:12]', '贝莱德向 Coinbase 存入 2,448 BTC（1.8 亿美元）+ 28,683 ETH（5,762 万美元）'),
    ('[19:05]', 'Tom Lee：标普 500 有望升至 7,700 点后调整，10 月前震荡消化沃什上任 + IPO 流动性压力'),
    ('[18:58]', '美联储施密德："可能需要考虑使货币政策更加紧缩"（鹰派 / 替代 FedWatch）'),
    ('[10:11 早]', 'Strategy 已向 Coinbase Prime 存入 411.48 BTC → 与晚间贝莱德形成机构连续抛售信号'),
]
for ts, content in news:
    add_bullet([(ts + ' ', True), (content, False)])

add_para([
    ('晚间情绪聚合：', True),
    ('4 利空 / 1 利多 / 1 中性 → aggregate_sentiment = ', False),
    ('中性偏空', True),
    ('（已较早间"中性"恶化）', False),
])

add_hr()

# ===== 技术面 =====
add_h2('二、技术面')

add_h3('盘口（Bybit BTCUSDT 1h，Coinglass）')
add_table(
    ['维度', '读数', '判定'],
    [
        ['CVD（累积成交量增量）', '-15.664K（从 5/16 -4K 持续下行）', '下降'],
        ['价格', '73,474.80（-0.17%）', '下降'],
        ['资金费率（持仓加权）', '0.0036（已从 28/29 日 0.0090 峰值降温）', '为正值偏冷'],
        ['持仓 OI', '56.015K（从 28 日 62K 峰值回落 9.6%）', '下降'],
    ]
)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(8)
r = p.add_run('解读：')
set_font(r, 10.5, True)
r = p.add_run('中性偏空（趋势末期出货特征）')
set_font(r, 10.5, True, RGBColor(0xC0, 0x39, 0x2B))

add_bullet([('CVD↓ + Price↓ → 卖盘主导趋势一致', False)])
add_bullet([('OI 缩减（62K → 56K）= ', False), ('空头止盈平仓，不是新空持续进场', True)])
add_bullet([('Funding 仍正但降温 = 多头未屈服但情绪转弱', False)])
add_bullet([('16 组合判定：非极端组合（不属 C01/C02 自动 70），手动评分 45', False)])

add_h3('FedWatch 6 月 17 日 FOMC 利率概率（CME，as of 5/29 06:36 CT）')
add_table(
    ['目标利率 (bps)', 'NOW', '1 日前', '1 周前', '1 月前'],
    [
        ['325-350 (降息)', '0.0%', '0.0%', '0.0%', '1.0%'],
        ['350-375 (当前)', '98.9%', '99.4%', '96.0%', '99.0%'],
        ['375-400 (加息)', '1.1%', '0.6%', '4.0%', '0.0%'],
    ]
)
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
r = p.add_run('FedWatch 解读：')
set_font(r, 10.5, True)
r = p.add_run('6 月 FOMC 维持现利率铁定占主导（98.9%），降息预期已完全归零；')
set_font(r, 10.5)
r = p.add_run('加息概率近一日从 0.6% 反弹至 1.1%（市场吸收施密德鹰派表态），')
set_font(r, 10.5, True, RGBColor(0xC0, 0x39, 0x2B))
r = p.add_run('macro 由"被动中性"转为"被动中性偏鹰" → 对 BTC 边际利空。')
set_font(r, 10.5)

add_h3('盘面（Bybit BTCUSD 日线 / Exocharts Bid-Ask Profile，过去 10 日）')
add_table(
    ['日期', 'POC', 'Delta', 'CVD', '日波幅'],
    [
        ['5/20', '77,442', '+549k', '+549k', '1,328'],
        ['5/21', '77,790', '-30M', '-29M', '1,483'],
        ['5/22', '75,618', '-26M', '-55M', '2,570'],
        ['5/23', '75,114', '+22M', '-33M', '3,154（高波动）'],
        ['5/24', '76,890', '+32M', '-1.4M', '1,438'],
        ['5/25', '77,214', '-9.8M', '-11M', '1,012'],
        ['5/26', '76,314', '-8.3M', '-19M', '2,471'],
        ['5/27', '75,318', '-6.3M', '-26M', '1,935'],
        ['5/28', '72,882', '-19M', '-44M', '2,011（破位）'],
        ['5/29', '73,590', '-2M', '-46M', '794（窄幅）'],
    ]
)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(8)
r = p.add_run('日线级别：')
set_font(r, 10.5, True)
r = p.add_run('5/22 跌破 77,000 后多次失败回补，5/28 加速破位至 72,500 区域，今日缩量微反弹至 73,500。空头趋势确认，但今日 Delta 仅 -2M 已近平衡 → 短线可能筑底反弹。')
set_font(r, 10.5)

p = doc.add_paragraph()
r = p.add_run('小时级别：')
set_font(r, 10.5, True)
r = p.add_run('1h 图显示 5/28 触 72,500 后窄幅震荡 + 高位下移，短期阻力 73,700-74,000，短期支撑 72,500-73,000。')
set_font(r, 10.5)

add_hr()

# ===== 趋势 + 支撑压力 =====
add_h2('三、趋势确认与支撑压力')
add_para([('趋势确认：', True), ('空头趋势（中短线）— 周线/日线一致空头；1h 出现末期出货迹象，未现反转', False)])
add_para([
    ('日内支撑：', True), ('72,500 - 73,000　　', False),
    ('日内压力：', True), ('73,700 - 74,000（次级 74,500）', False),
])

add_hr()

# ===== 策略 =====
add_h2('四、策略')
add_para([('持中线做空', True), ('（5 层防守，已激活保本损 + 动态止损）', False)])
add_bullet([('持仓：', True), ('BTCUSDT short / 均价 79,150 / 仓位 $500 / 5x / 50%', False)])
add_bullet([('当前浮盈：', True), ('约 +5,675 点 / +7.2% 价格 / +36% 仓位（5x 杠杆）', False)])
add_bullet([('中线计划：', True), ('保持不变（active_plan = true，layer 5/5）', False)])
add_bullet([('防守建议：', True), ('保本损应已上移至 79,150；动态止损建议设在 74,500（今日 H+1% 缓冲）', False)])
add_bullet([('日内：', True), ('维持原计划，', False), ('不新增仓位', True), ('（OI 缩减信号警示趋势末期，新空风险加大）', False)])
add_bullet([('风控：', True), ('单笔止损 ≤ 3%、5 项状态门禁全绿', False)])

add_hr()

# ===== 20:00 评分点 =====
add_h2('五、20:00 评分点')

add_table(
    ['维度', '满分', '实得', '备注'],
    [
        ['盘口', '70', '45', '16 组合非极端，趋势末期出货'],
        ['盘面', '30', '18', '详见下表'],
        ['总评分', '100', '63', '< 70 门槛 → Maker 观望'],
    ]
)

add_h3('盘面 30 细分')
add_table(
    ['项', '满分', '实得', '理由'],
    [
        ['支撑/压力接近度', '10', '6', '73,475 距 28 日低 72,500 约 1.3%，接近但未触'],
        ['多空流动性掠夺', '10', '5', '72,500 下方止损已扫，可能反扫上方 74,000'],
        ['SMA20 突破/回踩', '5', '4', '已破 SMA20 向下，无回踩，趋势确认'],
        ['量价关系', '3', '2', '今日 169M vs 27/28 日 234M/270M，缩量回升 = 反弹乏力'],
        ['斐波/趋势线接近度', '2', '1', '仅有大体下行趋势线，无明确斐波位'],
    ]
)

add_hr()

# ===== 盘面执行 Check（TradingView 15min）=====
add_h2('六、盘面执行 Check（TradingView 15min · 最终/最重要）')

add_quote('来源：用户 TradingView BTCUSDT 15min（Binance）截图 | 这是开仓前入场位置精度的最终把关')

add_para([
    ('K 线：', True),
    ('开 73,491.63 / 高 73,526.21 / 低 73,341.85 / 收 73,464.00（-0.04%）', False),
])

add_h3('结构判定')
add_bullet([('自 5/28 ~12:00 低点（~72,800）以来走出 ', False), ('白色上升通道', True), ('（处于更大下跌趋势中 → 熊旗 / 上升楔形，counter-trend 反弹）', False)])
add_bullet([('当前价 73,464 位于 ', False), ('通道中部', True), (' + VRVP POC 黄线密集成交区（73,200-73,600）', False)])

add_h3('关键水平（用户手绘 支撑/压力）')
add_table(
    ['类型', '价位', '说明'],
    [
        ['压力 5.29（通道上沿）', '74,000 - 74,400', 'teal 横线 + 上升通道上轨，反弹空目标区'],
        ['当前价', '73,464', '通道中部 / VRVP POC'],
        ['通道下沿', '72,800 - 73,000', '短期支撑'],
        ['支撑 5.27 / 5.29', '72,400', '橙线，破位则趋势空延续'],
    ]
)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(8)
r = p.add_run('盘面执行结论：')
set_font(r, 10.5, True)
r = p.add_run('价格处上升通道 ')
set_font(r, 10.5)
r = p.add_run('中部 = 入场位置不优 → 印证观望')
set_font(r, 10.5, True, RGBColor(0xC0, 0x39, 0x2B))
r = p.add_run('。只有触及通道上沿 74,000-74,400（压力 5.29）被拒，才是反弹空高质量入场点（止损置于 74,400 上方）。')
set_font(r, 10.5)

p = doc.add_paragraph()
r = p.add_run('交易宪法对照（图右）：')
set_font(r, 10.5, True)
for item in [
    '非系统不做 / 非 Maker 不开 / 违规即封禁交易资格',
    '浮盈首次 ≥ +1.5R 时浮盈防守层方可激活',
    '亏损砍短 盈利放满；单笔止损 3% 以内',
    '入场位置要求极高 → 当前中部位置不满足，故观望',
]:
    add_bullet([(item, False)])

add_hr()

# ===== Maker 晚间 =====
add_h2('七、【晚 20:30 新增计划】Maker 晚间')

p = doc.add_paragraph()
r = p.add_run('【晚20:30新增计划】2026-05-29')
set_font(r, 12, True)

add_para([('不能做：', True), ('做多（同主账户 cannot_do，晚间未变）', False)])

p = doc.add_paragraph()
r = p.add_run('BTC（策略）：')
set_font(r, 11, True)
r = p.add_run('[观望]')
set_font(r, 12, True, RGBColor(0xC0, 0x39, 0x2B))

add_h3('理由')
add_bullet([('20:00 重评分总分 ', False), ('63', True), ('，未达 70 开仓门槛', False)])
add_bullet([('盘口 45 分（CVD/Price 一致下，但 OI 缩减 + Funding 降温 = 趋势末期出货）', False)])
add_bullet([('盘面 18 分（支撑近、缩量反弹乏力）', False)])
add_bullet([('主账户已持中线空 @ 79,150 浮盈 +36%（5x），Maker 不应在末期信号下追空', False)])

add_para([('执行概率：', True), ('0%', True)])

add_h3('注意事项')
add_bullet([('保持观望至次日早间 11:00 重评分', False)])
add_bullet([('反弹空触发位（盘面 Check 锁定）：', True), ('价格上探通道上沿 74,000-74,400（压力 5.29）+ Funding 重新冲高 + CVD 恢复下行，三者共振才入场', False)])
add_bullet([('当前价 73,464 处通道中部，', False), ('入场位置不优，不在边缘不开（宪法：入场位置要求极高）', True)])
add_bullet([('若价格跌破 72,500（通道下沿 + 支撑 5.27）→ 主账户防守动作（不新增 Maker 空，避免与主账户头寸重叠）', False)])

add_hr()

# ===== 数据完整度 =====
add_h2('八、数据完整度')

add_table(
    ['数据源', '状态', '来源'],
    [
        ['BlockBeats', '✅ 实时抓取', 'Chrome MCP tabId 1271080758'],
        ['Exocharts BTC 日线', '✅ 用户截图', 'Bybit BTCUSD D Bid-Ask Profile（10 K 线）'],
        ['Coinglass BTC 1h', '✅ 用户截图', 'Bybit BTCUSDT 1h（CVD/Funding/OI 三指标）'],
        ['CME FedWatch', '✅ 用户截图', '17 Jun 2026 FOMC：维持 98.9% / 加息 1.1%（1日反弹 +0.5pp）'],
        ['TradingView 15min 盘面', '✅ 用户截图', 'BTCUSDT 15m Binance（上升通道 + 支撑压力 + VRVP）'],
    ]
)

add_h3('链 B 闭环检查')
for item in [
    '情绪门禁（5 项全绿，按 main_account_state.json）',
    '数据采集（4/4 源完成 ✅）',
    'BlockBeats 截图（Chrome MCP 已完成）',
    '盘口 16 组合判定（非极端，手动 45）',
    '总评分计算（63）',
    '盘面执行 Check（TradingView 15min：通道中部，入场位置不优）',
    '7 Gate 预检（总分 < 70，不进入开仓流程）',
    '输出 Maker 晚间观望',
]:
    add_bullet([('[x] ', True), (item, False)])

# Footer
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(12)
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('Generated by output_agent (chain B)  |  2026-05-29 20:00  |  Trading-System v2026.5')
set_font(r, 9, False, RGBColor(0x99, 0x99, 0x99), italic=True)

out_path = r'C:\Users\31702\Desktop\Trading-System\outputs\2026-05-29_晚间日报_v3.docx'
doc.save(out_path)
print('SAVED:', out_path)
