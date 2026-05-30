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

def add_table(headers, rows):
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
          '2026-05-30  20:00 评分点  |  Trading-System v2026.5  |  output_agent')

add_quote('数据采集：BlockBeats（Chrome MCP / JS 直取）、Exocharts（用户截图 Bybit BTCUSD 日线 Bid-Ask Profile）、Coinglass（用户截图 Bybit BTCUSDT 1h）、CME FedWatch（用户截图 17 Jun 2026 FOMC）、TradingView 15m（用户截图 入场把关）')
add_quote('数据完整度：5/5 ✅（今日仅出晚间报告，早间无 09-11 点数据，跳过）')

add_hr()

# ===== 一、主账户日报（晚间刷新）=====
add_h2('一、主账户日报（晚间刷新）')

p = doc.add_paragraph()
r = p.add_run('2026-05-30　20:00 评分点')
set_font(r, 12, True)

add_para([('不能做：', True), ('做多', False)])

add_para([
    ('基本面：', True),
    ('偏空（监管 + 合规 + 资金面 risk-off + 地缘去险叙事走弱）', True),
    ('— 欧盟评估对加密统一征税 + Circle 冻结 cUSDC + Binance 鲸鱼稳定币流入较去年 9 月减半（巨鲸 risk-off）+ 美伊协议未定美方强硬', False),
])

add_h3('重要新闻（BlockBeats 实时抓取，18:14-19:55）')
news = [
    ('[19:55]', 'Alephium 以太坊跨链桥遭攻击，损失约 81.5 万美元（安全事件，单点）→ 利空'),
    ('[19:46]', 'OpenAI 已与花旗、摩根大通讨论参与 IPO（风险偏好 / AI 叙事，间接）→ 弱利多'),
    ('[19:12]', '美国防长：特朗普希望阻止德黑兰获核武，除非协议有利否则不签署（地缘去险叙事走弱）→ 利空'),
    ('[18:53/18:19]', 'Zama 回应 Circle 冻结 cUSDC 合约，法律团队已介入（稳定币 / 合规事件）→ 利空'),
    ('[18:36]', '数据：Binance 百万级鲸鱼稳定币流入量较去年 9 月减半，巨鲸风险偏好降低 → 利空'),
    ('[18:24]', '欧盟评估对加密行业统一征税，七年周期约 200 亿欧元新收入（监管 / 税收）→ 利空'),
]
for ts, content in news:
    add_bullet([(ts + ' ', True), (content, False)])

add_para([
    ('晚间情绪聚合：', True),
    ('5 利空 / 1 利多 / 3 中性 → 利空-利多差 = 4 ≥ 2 → aggregate_sentiment = ', False),
    ('偏空', True),
    ('（较 5/29「中性偏空」进一步走弱，新增监管 + 资金面两条主线）', False),
])

add_hr()

# ===== 技术面 =====
add_h2('二、技术面')

add_h3('盘口（Bybit BTCUSDT 1h，Coinglass）')
add_table(
    ['维度', '读数', '判定'],
    [
        ['CVD（累积成交量增量）', '-15.865K（深跌后微抬）', '下降'],
        ['价格', '73,572（73k-74k 收敛箱体）', '下降 / 横盘'],
        ['资金费率（持仓加权）', '0.0048（仍较 28/29 日 0.0090 峰值明显降温）', '为正值偏冷'],
        ['持仓 OI', '54.256K（从 28 日 62K 峰值回落约 12.5%）', '下降'],
    ]
)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(8)
r = p.add_run('解读：')
set_font(r, 10.5, True)
r = p.add_run('中性偏空（趋势末期去杠杆出清）')
set_font(r, 10.5, True, RGBColor(0xC0, 0x39, 0x2B))

add_bullet([('CVD↓ + Price↓ → 卖盘主导方向一致', False)])
add_bullet([('OI 继续缩减（62K → 54.2K）= ', False), ('多头止损 / 空头止盈双向离场，去杠杆，非新空持续进场', True)])
add_bullet([('Funding 仍正但降温 = 多头杠杆被冲洗，情绪转弱未屈服', False)])
add_bullet([('16 组合判定：与 5/29 同组合（CVD↓/价↓/OI↓/Funding 正降温），非极端，手动评分 45', False)])

add_h3('FedWatch 6 月 17 日 FOMC 利率概率（CME，as of 5/30 06:52 CT）')
add_table(
    ['目标利率 (bps)', 'NOW', '1 日前', '1 周前', '1 月前'],
    [
        ['325-350 (降息)', '0.4%', '0.4%', '0.0%', '5.6%'],
        ['350-375 (当前)', '99.6%', '99.6%', '96.0%', '94.4%'],
        ['375-400 (加息)', '0.0%', '0.0%', '4.0%', '0.0%'],
    ]
)
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
r = p.add_run('FedWatch 解读：')
set_font(r, 10.5, True)
r = p.add_run('6 月 FOMC 维持现利率几成定局（99.6%）；')
set_font(r, 10.5)
r = p.add_run('较 1 周前加息概率 4% → 0%（去鹰），较 1 月前降息 5.6% → 0.4%（去鸽），双尾风险均被定价掉 → ')
set_font(r, 10.5)
r = p.add_run('macro 净中性（status quo）。')
set_font(r, 10.5, True)

add_h3('盘面（Bybit BTCUSD 日线 / Exocharts Bid-Ask Profile，近 7 日）')
add_table(
    ['日期', 'POC', 'Delta', 'CVD', '日波幅'],
    [
        ['5/24', '76,890', '+32M', '-1.9M', '1,437.5'],
        ['5/25', '77,214', '-9.8M', '-12M', '1,011.8'],
        ['5/26', '76,314', '-8.3M', '-20M', '2,471.0'],
        ['5/27', '75,318', '-6.3M', '-26M', '1,934.9'],
        ['5/28', '72,882', '-19M', '-45M', '2,010.9（破位）'],
        ['5/29', '73,494', '-16M', '-61M', '1,832.8'],
        ['5/30', '73,422', '+4.7M', '-56M', '593.9（极度收敛）'],
    ]
)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(8)
r = p.add_run('日线级别：')
set_font(r, 10.5, True)
r = p.add_run('POC 自 5/24 的 76,890 一路下移至 5/28 的 72,882（加速破位），近 3 日在 72.9k-73.5k 筑底。今日 Delta 翻正 +4.7M + 日波幅骤降至 593.9（全周最窄）+ CVD 由 -61M 收敛至 -56M = 卖压衰竭、横盘筑底特征明显。空头趋势仍确认，下行动能阶段性枯竭。')
set_font(r, 10.5)

p = doc.add_paragraph()
r = p.add_run('小时级别：')
set_font(r, 10.5, True)
r = p.add_run('1h 图自 5/28 触 72,500 后高位下移转横盘，短期阻力 73,700-74,150，短期支撑 72,950-73,000。')
set_font(r, 10.5)

add_hr()

# ===== 趋势 + 支撑压力 =====
add_h2('三、趋势确认与支撑压力')
add_para([('趋势确认：', True), ('空头趋势（中短线）— 周 / 日线一致空头；1h + 日线均现末期去杠杆 + 横盘筑底迹象，未现反转，亦未现新空动能', False)])
add_para([
    ('日内支撑：', True), ('72,950 - 73,000（次级 72,000）　　', False),
    ('日内压力：', True), ('74,000 - 74,150（次级 74,400）', False),
])

add_hr()

# ===== 策略 =====
add_h2('四、策略')
add_para([('持中线做空', True), ('（5 层防守，已激活保本损 + 动态止损）', False)])
add_bullet([('持仓：', True), ('BTCUSDT short / 均价 79,150 / 仓位 $500 / 5x / 50%', False)])
add_bullet([('当前浮盈：', True), ('约 +5,550 点 / +7.0% 价格 / +35% 仓位（5x 杠杆）', False)])
add_bullet([('中线计划：', True), ('保持不变（active_plan = true，layer 5/5）', False)])
add_bullet([('防守建议：', True), ('保本损上移至 79,150；动态止损建议设在 74,200（箱体上沿 74,150 + 缓冲）', False)])
add_bullet([('日内：', True), ('维持原计划，', False), ('不新增仓位', True), ('（OI 缩减 + Delta 翻正 + 波幅收敛 = 末期信号，新空盈亏比差）', False)])
add_bullet([('风控：', True), ('单笔止损 ≤ 3%、5 项状态门禁全绿', False)])

add_hr()

# ===== 20:00 评分点 =====
add_h2('五、20:00 评分点')

add_table(
    ['维度', '满分', '实得', '备注'],
    [
        ['盘口', '70', '45', '16 组合非极端，趋势末期去杠杆出清（与 5/29 同组合）'],
        ['盘面', '30', '17', '详见下表'],
        ['总评分', '100', '62', '< 70 门槛 → Maker 观望'],
    ]
)

add_h3('盘面 30 细分')
add_table(
    ['项', '满分', '实得', '理由'],
    [
        ['支撑/压力接近度', '10', '5', '73,600 处 73k-74.2k 箱体中部，距任一关键位 > 0.5%，无贴边'],
        ['多空流动性掠夺', '10', '5', '72,500 下方止损已扫，箱体上下双侧蓄势，方向未定'],
        ['SMA20 突破/回踩', '5', '4', '仍处 SMA20 下方，趋势未修复；无回踩信号'],
        ['量价关系', '3', '2', '日波幅 593.9 + 量能收缩，横盘乏力，无放量突破'],
        ['斐波/趋势线接近度', '2', '1', '仅大体下行趋势线，无明确斐波位'],
    ]
)

add_hr()

# ===== 盘面执行 Check（TradingView 15min）=====
add_h2('六、盘面执行 Check（TradingView 15min · 最终/最重要）')

add_quote('来源：用户 TradingView BTCUSDT 15min（Binance）截图，20:07 时点 | 开仓前入场位置精度的最终把关')

add_para([
    ('K 线：', True),
    ('开 73,602.01 / 高 73,610.59 / 低 73,600.01 / 收 73,600.02（-0.00%）', False),
])

add_h3('结构判定')
add_bullet([('价格夹在 ', False), ('73k-74.2k 横盘收敛箱体', True), ('（处更大下跌趋势中，去杠杆后的横向消化）', False)])
add_bullet([('当前价 73,600 位于 ', False), ('箱体正中部', True), (' + VRVP 价值区 72,950-74,150，POC 居中', False)])

add_h3('关键水平（用户手绘 支撑/压力）')
add_table(
    ['类型', '价位', '说明'],
    [
        ['压力 5.29（箱体上沿）', '74,000 - 74,150', '反弹空目标区 / 上方流动性'],
        ['当前价', '73,600', '箱体中部 / VRVP POC'],
        ['箱体下沿', '72,950 - 73,000', '短期支撑'],
        ['支撑 5.29', '72,000', '破位则趋势空延续'],
    ]
)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(8)
r = p.add_run('盘面执行结论：')
set_font(r, 10.5, True)
r = p.add_run('价格处箱体 ')
set_font(r, 10.5)
r = p.add_run('中部 = 入场位置不优 → 印证观望')
set_font(r, 10.5, True, RGBColor(0xC0, 0x39, 0x2B))
r = p.add_run('。只有上探箱体上沿 74,000-74,150（压力 5.29）被拒，才是反弹空高质量入场点（止损置于 74,150 上方）。')
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
r = p.add_run('【晚20:30新增计划】2026-05-30')
set_font(r, 12, True)

add_para([('不能做：', True), ('做多（同主账户 cannot_do，晚间未变）', False)])

p = doc.add_paragraph()
r = p.add_run('BTC（策略）：')
set_font(r, 11, True)
r = p.add_run('[观望]')
set_font(r, 12, True, RGBColor(0xC0, 0x39, 0x2B))

add_h3('理由')
add_bullet([('20:00 重评分总分 ', False), ('62', True), ('，未达 70 开仓门槛', False)])
add_bullet([('盘口 45 分（CVD/价格一致下行，但 OI 缩减 + Funding 降温 + 今日 Delta 翻正 = 趋势末期去杠杆，非新空环境）', False)])
add_bullet([('盘面 17 分（价处箱体中部入场不优、量价收敛乏力）', False)])
add_bullet([('主账户已持中线空 @ 79,150 浮盈 +35%（5x），Maker 不应在末期 + 筑底信号下追空', False)])

add_para([('执行概率：', True), ('0%', True)])

add_h3('注意事项')
add_bullet([('保持观望至次日早间 11:00 重评分', False)])
add_bullet([('反弹空触发位（盘面 Check 锁定）：', True), ('上探箱体上沿 74,000-74,150（压力 5.29）被拒 + Funding 重新冲高 + CVD 恢复下行，三者共振才入场', False)])
add_bullet([('当前价 73,600 处箱体中部，', False), ('入场位置不优，不在边缘不开（宪法：入场位置要求极高）', True)])
add_bullet([('若跌破 72,950（箱体下沿）→ 主账户防守动作（不新增 Maker 空，避免与主账户头寸重叠）', False)])

add_hr()

# ===== 数据完整度 =====
add_h2('八、数据完整度')

add_table(
    ['数据源', '状态', '来源'],
    [
        ['BlockBeats', '✅ 实时抓取', 'Chrome MCP / JS 直取（页面轮询致 get_page_text 超时，改 javascript_tool）'],
        ['Exocharts BTC 日线', '✅ 用户截图', 'Bybit BTCUSD D Bid-Ask Profile（footprint 统计）'],
        ['Coinglass BTC 1h', '✅ 用户截图', 'Bybit BTCUSDT 1h（CVD/Funding/OI 三指标）'],
        ['CME FedWatch', '✅ 用户截图', '17 Jun 2026 FOMC：维持 99.6% / 周比加息 4%→0% 去鹰 / 月比降息 5.6%→0.4% 去鸽'],
        ['TradingView 15min 盘面', '✅ 用户截图', 'BTCUSDT 15m Binance（箱体 + 支撑压力 + VRVP，入场中部）'],
    ]
)

add_h3('链 B 闭环检查')
for item in [
    '情绪门禁（5 项全绿，按 main_account_state.json）',
    '数据采集（5/5 源全完成 ✅）',
    'BlockBeats 抓取（Chrome MCP / JS 直取）',
    '盘口 16 组合判定（非极端，手动 45）',
    '总评分计算（62）',
    '盘面执行 Check（TradingView 15min：箱体中部，入场位置不优）',
    '7 Gate 预检（总分 < 70，不进入开仓流程）',
    '输出 Maker 晚间观望',
]:
    add_bullet([('[x] ', True), (item, False)])

# Footer
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(12)
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('Generated by output_agent (chain B)  |  2026-05-30 20:00  |  Trading-System v2026.5')
set_font(r, 9, False, RGBColor(0x99, 0x99, 0x99), italic=True)

out_path = r'C:\Users\31702\Desktop\Trading-System\outputs\2026-05-30_晚间日报.docx'
doc.save(out_path)
print('SAVED:', out_path)
