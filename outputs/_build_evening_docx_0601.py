# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn

FONT = "Microsoft YaHei"

def set_font(run, size=11, bold=False, color=None):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), FONT)

doc = Document()
doc.styles['Normal'].font.name = FONT
doc.styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), FONT)

def H(text, size=14, color=(0x1F,0x4E,0x79)):
    p = doc.add_paragraph(); set_font(p.add_run(text), size=size, bold=True, color=color); return p
def P(text, size=11, bold=False, color=None):
    p = doc.add_paragraph(); set_font(p.add_run(text), size=size, bold=bold, color=color); return p
def B(text, size=11, color=None):
    p = doc.add_paragraph(style='List Bullet'); set_font(p.add_run(text), size=size, color=color); return p

H("2026-06-01 晚间日报（系统独立稿）", size=16)
P("门禁：可交易（身体正常/情绪平静/节奏顺/连续止损0）｜心力：无异常（5/31 专注10）｜独立成稿，判断字段均系统自推。", size=9, color=(0x80,0x80,0x80))
P("格式：①日报正文 + ②Maker 计划（照用户 Notion 模板·可直接粘贴）；③后附评分/五源（系统内部备份）。", size=9, color=(0x80,0x80,0x80))

H("① 日报正文（照汇总库模板）")
P("不能做：追多", bold=True, color=(0xC0,0x00,0x00))
P("基本面：利空（地缘升级·美军拦截伊朗射向驻科威特美军基地导弹 + Strategy 首抛 32 枚 BTC 破“永不卖币”）价格部分兑现", bold=True)
P("技术面：", bold=True)
P("盘口（合约）：")
P("CVD 下降　价格 下降　资金费率 上升（为正值）　持仓 上升")
P("解读：中性偏空（空头增仓主导下跌＋多头被套抄底未投降＝拥挤多头侧被收割）")
P("盘面：")
P("日线级别 放量破 73000 震荡下沿、波幅大幅扩张、跌破 SMA20 回踩上行通道中下沿，卖压主导趋势性下行　利空")
P("小时级别 下降通道内偏下、贴大级别共振支撑 71800-72300 测试、现货卖压持续、买盘势能弱　利空")
P("趋势确认：空头趋势（短线）", bold=True)
P("日内支撑：71800-72300　　　　日内压力：74250-74750", bold=True)
P("策略：", bold=True)
P("中线计划保持不变（5/28 做多 @73,500 持仓中，5x/$1000/1:3；守关键止损 71,000＝上行通道下轨/多头最后防守；浮盈防守层 75500/76200/74400 因价在 entry 下方均未激活；未破 71,000 前持有，有效跌破止损出局）")

H("② 晚 20:30 Maker 新增计划（总分 74 ≥ 70 → 必挂）")
P("BTC（策略）：执行概率 —（系统不预判·用户定）（已执行 0%）　胜率 >60%（Maker 极强共振门槛达标）")
P("反弹空：74250-75300　持仓 700 刀　Binance　右侧　盈亏比 1:2.5 以上", bold=True)
P("止盈：71800-72000（TP1）减仓 50%")
P("止损：76000（站稳上方·多空分界翻多·结构失效；约 1.7%，在单笔 3% 上限内）")
P("浮盈防守计划：")
P("第一层：价格触及 73000（前震荡下沿转压力）设立 4 小时级别极点高点为止损　同时取消所有加仓")
P("第二层：价格触及 72200（≈2R）减仓 50%　同时设立保本损")
P("注意事项：若价格优先跌破 71000（多头最后防守失守·趋势加速下行·反弹前提消失）则此策略取消", bold=True)
P("核心（开仓理由）：偏空环境下反弹至空头流动性（信号1）边缘的高质量做空；现价 72200 在入场区下方较远 → 单挂边缘等待、价不反弹到 74250+ 不成交；⚠️ 不在 72200 现价追空（追在大级别共振支撑上方＝低质量、宪法禁追价）")

H("③ 后附（系统内部备份 · 不进 Notion 正文）")
P("评分明细（70+30 ＝ 74）", bold=True)
B("盘口 53/70：CVD↓ / 价格↓ / OI↑(54K→57.42K) / 资金费率↑且为正(0.0096)＝空头增仓主导下跌（偏强空头延续，非 C01/C02 极端）→ 手动 53")
B("盘面 21/30：接近度 8（贴大级别共振支撑 71,800-72,300＋0.618fib 71,824）+流动性掠夺 3+SMA20 5（空头排列）+量价 3（放量破位）+斐波 2")
B("总分 74 ≥ 70（连续 63/62/57 后首次达标）→ 必挂 Maker 空单于 74,250-75,300 边缘等待")
P("五源支撑", bold=True)
B("① BlockBeats（偏空·主线地缘升级·价格部分兑现）：美军拦截伊朗射向驻科威特美军基地 2 枚导弹（冲突升级）+特朗普口头缓和；Strategy 首抛 32 枚 BTC(77,135)破“永不卖币”·MSTR 盘前跌超 6%；贝莱德存 929 BTC；BTC 跌破 7.2 万(-2.56%)。利空5/利多3")
B("② 日线 footprint：Vol 112M(连续放量) / Delta -11M / CVD -9.6M(转负) / POC 72,246 / H-L 2174.2(波幅扩张)＝放量趋势性向下突破")
B("③ Coinglass 1h：价 72,214↓ / CVD -16.46K↓ / 资金费率 0.0096↑(正值) / OI 57.42K↑＝空头增仓+多头被套未投降")
B("④ FedWatch：6/17 不变 99.4%、降息 0%、无宽松 → 中性偏空")
B("⑤ TradingView 日/4H/1H/15m：价贴大级别共振支撑 71,800-72,300+0.618fib 71,824；上空头流动性 75,000/多空分界 76,000，下多头最后防守 70,500-71,000；日线破 73k+破 SMA20。把关：高质量空头边缘在 74,250-75,300/76,000，Maker 空单挂该边缘等待")

out = r"C:\Users\31702\Desktop\Trading-System-Code\outputs\2026-06-01_晚间日报.docx"
doc.save(out)
print("SAVED:", out)
