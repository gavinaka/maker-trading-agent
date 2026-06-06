# -*- coding: utf-8 -*-
# 🔍 晚间独立审查（倒推）-> Notion，100% 对齐 2026.6.2 审查金标（15 块）
import requests, json, sys, os
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import ensure_date_page
TOK = os.environ.get("NOTION_TOKEN", "")
assert TOK, "请先设置 NOTION_TOKEN"
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
DATE_PAGE = ensure_date_page("2026.6.5")

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
    # 1 callout (gray)
    callout([t("倒推回测：11:00 @61,470 → 日内强反抽至高点 "), t("63,259", "red", True),
             t("（+2.9%·上破 1H SMA20 63,023 后于 63k 被拒）→ NFP 超预期（"), t("17.2 万 vs 8.5 万", "red", True),
             t("）20:30 打回 → 20:00 @"), t("61,950", "green"),
             t("（冲高回落）。早间反弹空挂 62,400–63,000＝"), t("价反抽至 63,259 将整带成交、止损 64,000 从未被触及、NFP 打回后现浮盈 ≈+0.6R", "green", True),
             t("＝教科书级命中；不能做追空被验证。短板＝晚间初稿误把 Coinglass 末根 1h candle 高 62,430 当日内高、漏看真实 63,259，经用户指正订正。")],
            "🔍", "gray_background"),

    # 2 heading_2
    h2("综合评分（去系统逻辑 · 独立打分）"),
    # 3 table
    table(3, [
        row([cell("维度", bold=True), cell("🌅 早间", bold=True), cell("🌙 晚间", bold=True)]),
        row([cell("方向判断"), cell("85", "green"), cell("80", "green")]),
        row([cell("入场结构"), cell("88", "green"), cell("78", "yellow")]),
        row([cell("风险框架"), cell("86", "green"), cell("86", "green")]),
        row([cell("数据精度"), cell("90", "green"), cell("80", "yellow")]),
        row([cell("内在一致性"), cell("86", "green"), cell("84", "green")]),
        row([cell("综合", bold=True), cell("87 / A−", "green", True), cell("82 / B", "yellow", True)]),
    ]),

    # 4 heading_2
    h2("价格阶梯 · 两份挂单落点（倒推）"),
    # 5 table
    table(3, [
        row([cell("价位", bold=True), cell("标记", bold=True), cell("说明", bold=True)]),
        row([cell("64,000"), cell("早间空·止损（未触）", "green"), cell("日内高 63,259 < 64,000＝早间反弹空止损从未被触及")]),
        row([cell("63,259"), cell("日内高·反抽被拒", "red"), cell("上破 1H SMA20 63,023 即遭 63k 供给 + NFP 打回＝反抽失败")]),
        row([cell("62,500–63,000"), cell("晚间空·挂单带", "yellow"), cell("破位 6.4 转阻力 + 1H SMA20 63,023，今日反抽高已在其上方被拒证明有效供给")]),
        row([cell("62,400–63,000"), cell("早间空·整带成交", "green"), cell("11:00 入场带，价反抽至 63,259 将整带成交、NFP 打回后现浮盈 ≈+0.6R＝完美 fill")]),
        row([cell("61,950"), cell("20:00 当前", "green"), cell("晚间现价（NFP 打回后）")]),
        row([cell("61,801"), cell("NFP 20:30 打回", "red"), cell("非农超预期 risk-off、美元走强、BTC 承压 −3%")]),
        row([cell("61,470"), cell("11:00 早间现价 · 起点/日内低区", "green"), cell("反抽前的低位，全天未下破")]),
        row([cell("59,600–60,000"), cell("空头 TP（未及）", "green"), cell("60,000 整数关 + 日线低点 59,608")]),
    ]),

    # 6 callout (orange)
    callout([t("核心矛盾（最该看）：", "orange", True),
             t("今天是「超卖反抽至 63k 被拒 + NFP 事件型利空」日。早间反弹空挂 62,400–63,000＝"),
             t("教科书级命中——价从 61,470 反抽至 63,259 将整带成交、止损 64,000 从未被触及（高 63,259 < 64,000）、NFP 打回后现浮盈 ≈+0.6R", "green", True),
             t("，方向 + 择时 + edge 俱佳，不能做追空亦被验证；较 6/3 震荡市挂单空挂大幅改善。结构性短板＝"),
             t("晚间初稿误把 Coinglass 末根 1h candle 高 62,430 当日内高、漏看真实反抽 63,259（差 ~830 点）", "red", True),
             t("，经用户当场指正、交叉 Exo 日线 H-L 2,848.2 核验后订正＝读盘精度硬教训：日内高低须扫全日 K 线区间 + 跨源（Exo H-L / 15m）交叉、禁止只取末根 candle。")], "⚠️", "orange_background"),

    # 7 heading_2
    h2("关键发现（倒推得出）"),
    # 8 green
    para([t("① 早间反弹空＝本周最佳命中", "green", True), t("：挂 62,400–63,000，价反抽至 63,259 将整带成交、止损 64,000 从未被触及、NFP 打回后现浮盈 ≈+0.6R＝完美 fill + 方向兑现；较 6/3 震荡市挂单越挂越高/低参与大幅改善——破位回踩阻力 edge 质量到位、价格如期反抽入带。")]),
    # 9 green
    para([t("② 「不能做（禁追空）」事后正确", "green", True), t("：早间禁 61.5k 低位右侧追空——价随即反抽至 63,259（+2.9%）、低位追空会被反包挤压；NFP 打回后于 61.8k 仍禁追空（防二次反抽），禁令保护到位。")]),
    # 10 red
    para([t("③ NFP 事件型利空主导方向", "red", True), t("：非农 17.2 万远超 8.5 万预期＝联储降息理由被推翻、12 月加息概率 48→63%、市场定价明年 1 月加息、美元 DXY +15——宏观转鹰是今日方向级 driver，反抽于 63k 被其打回、盘口偏空被强化，事后方向判对。")]),
    # 11 yellow
    para([t("④ 读盘精度教训：日内高误读已订正", "yellow", True), t("：晚间初稿误取 Coinglass 末根 1h candle 高 62,430 为日内反抽高，漏看真实 63,259（差 ~830 点），把「反抽失败被拒」误写成「near lows 横盘企稳」；经用户指正、交叉 Exo 日线 H-L 2,848.2（63,259−2,848≈60,411 低）核验订正。教训＝日内高低须扫全日 K 线 + 跨源交叉、禁止只读末根 candle。")]),
    # 12 green
    para([t("⑤ 数据精度（订正后合格）", "green", True), t("：订正后价格全核对——日内高 63,259（Exo H-L 交叉核验）/ 现价 61,962 / POC 61,897 / 1h CVD −36,246K / 资费 0.0025 / NFP 17.2 万 vs 8.5 万，跨 5–6 源一致、无模糊位。")]),
    # 13 green
    para([t("⑥ 空仓纪律到位、未接飞刀", "green", True), t("：主账户 6/3 低多@67,000 已止损出局后全天空仓、未在反抽或打回中追单亦未接飞刀左侧抄底；门禁疲惫 + 心力团建收缩＝降频谨慎日，只挂边缘左侧反应、不主动追＝纪律执行到位。")]),
    # 14 gray
    para([t("一句话：", "gray", True), t("早间反弹空教科书级命中（价反抽 63,259 整带成交、止损未触、NFP 打回现浮盈 ≈+0.6R）、方向 + edge 俱佳；但晚间初稿日内高误读（62,430 vs 真实 63,259）被用户当场抓出＝读盘精度需扫全日 K 线 + 跨源核验的硬教训，订正后稿件合格。", "gray")]),
    # 15 default
    para([t("备注：本审查为系统独立倒推，去除 70+30 评分、≥70 必挂、footprint 16 组合等系统逻辑，仅以事件与早→晚实际走势检验早晚判断与挂单事后对错；不构成投资建议。")]),
]

# 归档旧 🔍 子页后重建（订正日内高误读）
r = requests.get(f"https://api.notion.com/v1/blocks/{DATE_PAGE}/children?page_size=100", headers=H); r.raise_for_status()
for b in r.json()["results"]:
    if b["type"] == "child_page" and b["child_page"]["title"].startswith("🔍"):
        requests.patch(f"https://api.notion.com/v1/pages/{b['id']}", headers=H,
                       data=json.dumps({"archived": True})).raise_for_status()
        print("archived old review:", b["id"])

payload = {"parent": {"type": "page_id", "page_id": DATE_PAGE},
           "properties": {"title": {"title": [{"type": "text", "text": {"content": "🔍 2026.6.5 晚间独立审查（倒推）"}}]}},
           "children": children}
r = requests.post("https://api.notion.com/v1/pages", headers=H, data=json.dumps(payload))
if r.status_code >= 300: print("FAIL", r.status_code, r.text); sys.exit(1)
print("REVIEW PAGE OK ->", r.json()["id"])
