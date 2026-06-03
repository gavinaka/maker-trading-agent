# -*- coding: utf-8 -*-
# 🔍 晚间独立审查（倒推）-> Notion，100% 对齐 2026.6.2 审查金标（15 块）
import requests, json, sys, os
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import ensure_date_page
TOK = os.environ.get("NOTION_TOKEN", "")
assert TOK, "请先设置 NOTION_TOKEN"
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
DATE_PAGE = ensure_date_page("2026.6.3")

def t(c, color=None, bold=False):
    it = {"type": "text", "text": {"content": c}}; a = {}
    if bold: a["bold"] = True
    if color: a["color"] = color
    if a: it["annotations"] = a
    return it
def para(runs, color="default"): return {"type": "paragraph", "paragraph": {"rich_text": runs, "color": color}}
def h2(c): return {"type": "heading_2", "heading_2": {"rich_text": [t(c)]}}
def callout(runs, emoji="⚠️", color="orange_background"):
    return {"type": "callout", "callout": {"rich_text": runs, "icon": {"emoji": emoji}, "color": color}}
def cell(c, color=None, bold=False): return [t(c, color, bold)]
def row(cells): return {"type": "table_row", "table_row": {"cells": cells}}
def table(width, rows, header=True):
    return {"type": "table", "table": {"table_width": width, "has_column_header": header, "has_row_header": False, "children": rows}}

children = [
    # 1 callout (green,red,green,red)
    callout([t("倒推回测：08:33 @66,748 → 先探日内低 "), t("65,975", "green"), t("（"), t("−1.2%", "red", True),
             t("）后反抽 → 20:00 @"), t("67,250", "green"), t("，全天 66,000–67,550 "), t("横盘震荡", "red", True),
             t("（非单边续跌）。中线偏空方向未证伪，但市场给的是震荡 + 65k 超卖反弹；三连反弹空在区间上沿低参与，真正吃到反弹的是用户左侧低多。")],
            "🔍", "gray_background"),

    # 2 heading_2
    h2("综合评分（去系统逻辑 · 独立打分）"),
    # 3 table
    table(3, [
        row([cell("维度", bold=True), cell("🌅 早间", bold=True), cell("🌙 晚间", bold=True)]),
        row([cell("方向判断"), cell("75", "yellow"), cell("72", "yellow")]),
        row([cell("入场结构"), cell("72", "yellow"), cell("70", "orange")]),
        row([cell("风险框架"), cell("85", "green"), cell("86", "green")]),
        row([cell("数据精度"), cell("88", "green"), cell("92", "green")]),
        row([cell("内在一致性"), cell("82", "green"), cell("84", "green")]),
        row([cell("综合", bold=True), cell("80 / B", "yellow", True), cell("79 / B", "yellow", True)]),
    ]),

    # 4 heading_2
    h2("价格阶梯 · 两份挂单落点（倒推）"),
    # 5 table
    table(3, [
        row([cell("价位", bold=True), cell("标记", bold=True), cell("说明", bold=True)]),
        row([cell("67,900–68,800"), cell("晚间空·挂单带", "yellow"), cell("压力 6.3 + 4H POC 67,972，现价上方 +0.6~2.3%（震荡上沿·未充分触及）")]),
        row([cell("67,250"), cell("20:00 当前", "green"), cell("晚间现价")]),
        row([cell("67,200–67,600"), cell("早间空·下沿勉强触", "red"), cell("08:33 入场带，下沿被触及、未到 67,600 充分区")]),
        row([cell("67,000"), cell("用户主账户低多", "green"), cell("左侧接飞刀（中午新开·持仓中·现浮盈微正）")]),
        row([cell("66,700"), cell("Maker 多·TP1 止盈", "green"), cell("击中 50%→触防守→TP1 出局 +$10")]),
        row([cell("65,975"), cell("日内低·扫后反抽", "red"), cell("扫支撑 6.3 上沿流动性即反弹＝超卖支撑显现")]),
        row([cell("65,300–65,800"), cell("空头 TP（未及）", "green"), cell("用户支撑 6.3，全天未下破")]),
    ]),

    # 6 callout (orange,red,orange)
    callout([t("核心矛盾（最该看）：", "orange", True),
             t("今天不是单边趋势日、而是震荡 + 65k 超卖反弹日——奖励「左侧低位接飞刀」、惩罚「等更高位挂反弹空」。系统中线偏空方向没有错（基本面利空 + 日线破位 + CVD 深负），但日内三连反弹空把空单越挂越高（67,200→67,500→67,900），价在 66,000–67,550 横盘、"),
             t("挂单带低参与几乎没吃到", "red", True),
             t("；真正赚钱的是用户左侧低多（接 65–66.7k 飞刀吃反弹、Maker TP1 +$10）。结构性代价＝"),
             t("单向看空框架 ⇄ 震荡/超卖反弹日的双向机会", "orange", True),
             t("。今天反弹属超卖修复非反转——中线方向无错，错在日内择时与单向性。")], "⚠️", "orange_background"),

    # 7 heading_2
    h2("关键发现（倒推得出）"),
    # 8 green
    para([t("① 「不能做（禁追空）」事后正确", "green", True), t("：早间禁 65,975 低位右侧追空——价扫低即反抽至 67,250、低位追空会被反包，禁令保护到位；晚间顺势改「禁追做多」，贴合反抽诱多结构。")]),
    # 9 orange
    para([t("② 反弹空入场结构＝震荡市最大短板", "orange", True), t("：三连反弹空入场带越挂越高（67,200-67,600→67,500-67,900→67,900-68,200），价在 66-67.5k 震荡、挂单落区间上沿＝低参与/被反复磨，全天反弹空难获利；执行概率 60%+ 在震荡上沿仍偏乐观。")]),
    # 10 red
    para([t("③ 用户左侧低多吃到反弹、与系统判向相反", "red", True), t("：用户主账户低多 @67,000 + Maker 做多 800（击中 50%→触防守 66,700→TP1 止盈 +$10），左侧接飞刀吃到 65k 超卖反弹；系统全天判反弹空（相反），事后用户低多更优——震荡/超卖反弹日单向看空错过双向机会。")]),
    # 11 yellow
    para([t("④ 偏空方向短期兑现、全天净震荡", "yellow", True), t("：早间 @66,748 判偏空，价先探 65,975（−1.2%）兑现短空、后反抽回 67,250＝全天 66–67.5k 横盘、非续跌单边；中线偏空成立，但日内「偏空」在震荡市偏保守。")]),
    # 12 green
    para([t("⑤ 数据精度合格", "green", True), t("：价格/百分比皆核过确切值（现价 67,253 / POC 66,774 / 1h CVD −27,475 / 资费 0.0039），跨 5–6 源交叉一致（15m/1H/4H/日线 + Coinglass + Exo），POC 与现价吻合、无模糊位。")]),
    # 13 green
    para([t("⑥ 中线偏空大框架未证伪", "green", True), t("：基本面利空（Strategy 四年首卖 + ETF 连续 11 日流出 35 亿 + 联储鹰派）+ 日线破位 + CVD 累积深负未改；今日反弹属超卖修复非反转——反弹空中线方向无错，错在日内震荡择时与单向性。")]),
    # 14 gray,gray
    para([t("一句话：", "gray", True), t("判偏空、中线方向没错，但今天市场给的是震荡 + 超卖反弹——安全的反弹空挂在区间上沿低参与，真正赚钱的是用户左侧低多。分析质量（数据 + 中线框架）合格，短板是日内震荡市仍机械单向挂反弹空、漏掉双向机会。", "gray")]),
    # 15 default
    para([t("备注：本审查为系统独立倒推，去除 70+30 评分、≥70 必挂、footprint 16 组合等系统逻辑，仅以事件与早→晚实际走势检验早晚判断与挂单事后对错；不构成投资建议。")]),
]

# 防重复
r = requests.get(f"https://api.notion.com/v1/blocks/{DATE_PAGE}/children?page_size=100", headers=H); r.raise_for_status()
for b in r.json()["results"]:
    if b["type"] == "child_page" and b["child_page"]["title"].startswith("🔍"):
        print("ABORT: 审查子页已存在 ->", b["id"]); sys.exit(0)

payload = {"parent": {"type": "page_id", "page_id": DATE_PAGE},
           "properties": {"title": {"title": [{"type": "text", "text": {"content": "🔍 2026.6.3 晚间独立审查（倒推）"}}]}},
           "children": children}
r = requests.post("https://api.notion.com/v1/pages", headers=H, data=json.dumps(payload))
if r.status_code >= 300: print("FAIL", r.status_code, r.text); sys.exit(1)
print("REVIEW PAGE OK ->", r.json()["id"])
