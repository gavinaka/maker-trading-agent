# -*- coding: utf-8 -*-
# 🔍 6/6 晚间独立审查（倒推·样本日）-> Notion，对齐 2026.6.2 审查金标（15 块）
# 今日用户个人休息·无早间稿：倒推检验 6/5 晚间挂单+不能做在 6/6 的兑现 + 独立评估 6/6 观望决策
import requests, json, sys, os
sys.path.insert(0, r"C:\Users\31702\Desktop\Trading-System-Code\outputs")
from notion_push_lib import ensure_date_page
TOK = os.environ.get("NOTION_TOKEN", "")
assert TOK, "请先设置 NOTION_TOKEN"
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
DATE_PAGE = ensure_date_page("2026.6.6")

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
    # 1 callout (gray) 倒推回测说明
    callout([t("样本日（用户个人休息·无盘中交易·无早间稿）：本审查倒推检验「最近一次系统判断＝6/5 晚间」在 6/6 的兑现，并独立评估 6/6 晚间观望决策。6/6 实际路径：开 61,056 → 早 03:00 探低 "), t("59,200", "green", True),
             t(" → 反抽至约 62,000（06:00）→ 震荡收敛 → 收 "), t("60,668", "green"),
             t("（-0.63%·周末缩量横盘）。6/5 晚间反弹空挂 62,500–63,000＝"), t("6/6 反抽仅至约 62,000、未触挂单带（差约 500 点）＝未成交、止损 64,000 从未受威胁＝资金保全、无盈亏", "green", True),
             t("；不能做追空再次被验证（6/6 探 59,200 即反包）。")],
            "🔍", "gray_background"),

    # 2 heading_2
    h2("综合评分（去系统逻辑 · 独立打分）"),
    # 3 table
    table(3, [
        row([cell("维度", bold=True), cell("🌙 6/5 晚间（倒推）", bold=True), cell("🌙 6/6 晚间（观望）", bold=True)]),
        row([cell("方向判断"), cell("82", "green"), cell("83", "green")]),
        row([cell("入场/不挂结构"), cell("74", "yellow"), cell("86", "green")]),
        row([cell("风险框架"), cell("86", "green"), cell("88", "green")]),
        row([cell("数据精度"), cell("85", "green"), cell("88", "green")]),
        row([cell("内在一致性"), cell("85", "green"), cell("87", "green")]),
        row([cell("综合", bold=True), cell("82 / B", "green", True), cell("86 / B+", "green", True)]),
    ]),

    # 4 heading_2
    h2("价格阶梯 · 6/5 挂单落点 vs 6/6 实际走势（倒推）"),
    # 5 table
    table(3, [
        row([cell("价位", bold=True), cell("标记", bold=True), cell("6/6 实际", bold=True)]),
        row([cell("64,000"), cell("6/5 晚间空·止损", "green"), cell("6/6 高仅约 62,000 < 64,000＝止损从未受威胁")]),
        row([cell("62,500–63,000"), cell("6/5 晚间空·挂单带", "yellow"), cell("6/6 反抽高约 62,000 未及（差约 500）＝挂单未成交、无盈亏")]),
        row([cell("62,000–62,300"), cell("6/6 反抽高（15m·06:00）", "red"), cell("反抽于此带被拒回落＝6/5 挂价略高于实际反抽高")]),
        row([cell("61,530"), cell("6/6 日线高", "red"), cell("日内压力·未续涨")]),
        row([cell("60,668"), cell("6/6 现价/日线收", "green"), cell("周末缩量横盘、坐 15m 上升趋势线")]),
        row([cell("60,000"), cell("关键支撑（多头守住）", "green"), cell("6/6 多头守住 6 万整数关＝企稳锚点")]),
        row([cell("59,200–59,500"), cell("6/6 日内低（探低即反包）", "green"), cell("早 03:00 探 59,200 后反包至 62,000＝低位右侧追空被挤压")]),
        row([cell("58,000"), cell("下方手绘支撑（未及）", "green"), cell("橙线支撑·6/6 未下探")]),
    ]),

    # 6 callout (orange) 核心矛盾
    callout([t("核心矛盾（最该看）：", "orange", True),
             t("6/5 晚间反弹空挂 62,500–63,000＝"), t("方向对（价持续偏弱、企稳未续涨）但挂价略高于 6/6 实际反抽高约 62,000（差约 500 点）→ 未成交、资金保全、无盈亏", "green", True),
             t("。事后看：若挂价下移贴近 61,500–62,000 实际反抽带或可小幅获利，但 6/6 价先探 59,200 再反抽＝左侧风险更大，「降频谨慎·绝不追价」的保守挂法保住了资金。今日 6/6＝"), t("BTC 日线 RSI 约 15.5 创 2020 以来最低的极度超卖横盘日", "red", True),
             t("，无高质量边缘、评分 63<70＝观望不挂＝纪律正确，不在 6 万上方接飞刀左侧（延续 6/3、5/28 教训）。")], "⚠️", "orange_background"),

    # 7 heading_2
    h2("关键发现（倒推得出）"),
    # 8 green
    para([t("① 6/5 反弹空：方向对、挂价略高未成交＝资金保全", "green", True), t("：挂 62,500–63,000，6/6 反抽仅至约 62,000（差约 500）未触发、止损 64,000 从未受威胁＝未成交、无盈亏；「绝不追价」纪律避免了在价先探 59,200 的逆风中被动进场。挂价略偏保守＝错过约 62,000 的小反抽空，但风险/资金保全优先。")]),
    # 9 green
    para([t("② 「不能做（禁追空）」再次事后正确", "green", True), t("：6/6 早 03:00 探低 59,200/59,500 即反包至约 62,000＝低位右侧追空必被挤压、禁令保护到位；连续多日（6/3–6/6）禁追空均被验证＝超卖末段右侧追空是高频陷阱。")]),
    # 10 green
    para([t("③ 中性偏空·企稳 thesis 兑现", "green", True), t("：6/5 晚间判「反抽失败、企稳信号初现」，6/6 未续崩（61,950 → 60,668·仅 -2%）、缩量横盘坐 15m 上升趋势线、守 6 万＝企稳如期兑现、方向判对（既未续跌破 6 万、也未确认反转）。")]),
    # 11 green
    para([t("④ 6/6 观望决策合理＝纪律优先", "green", True), t("：极度超卖（RSI 15.5）＋守 6 万＋看涨背离酝酿但买方（CVD）未接管＋价格处区间中下部＝无 ≥60% 可达高质量边缘、评分 63<70 → 观望不挂、不预埋、不接飞刀左侧；系统选择空仓等右侧确认＝纪律优先于行情。")]),
    # 12 yellow
    para([t("⑤ 极度超卖＝临界点警示", "yellow", True), t("：BTC 日线 RSI 约 15.5 创 2020 疫情崩盘以来最低、约 530 万枚长期 BTC 浮亏（高于 FTX 时期）、情绪接近恐慌；历史此位后曾反弹约 50%/30%，守 6 万则或反弹至 20 日 EMA 约 70,650、破 6 万则下探 5 万中段＝6 万整数关是方向分水岭，右侧确认前不预判。")]),
    # 13 green
    para([t("⑥ 数据精度合格", "green", True), t("：五源齐（①BlockBeats 实抓 / ②Exo / ③Coinglass / ⑤TV 日-4H-1H-15m）；④FedWatch 表未加载、沿用 6/5 并全网核验本质未变（NFP 17.2 万、6 月维持利率约 99%、2026 全年零降息约 75%）；价格全核对（60,656/60,668/60,930/-40,341K/57.0K/0.0010/61,530/59,500），无模糊位、跨源一致。")]),
    # 14 gray
    para([t("一句话：", "gray", True), t("6/5 反弹空方向对（企稳如期兑现）但挂价略高于 6/6 实际反抽（约 62,000）＝未成交、资金保全；不能做追空再次被验证；今日 6/6 极度超卖横盘、评分 63 → 观望不挂＝纪律正确，静待 6 万上方右侧企稳或破 6 万的方向确认。", "gray")]),
    # 15 default
    para([t("备注：本审查为系统独立倒推，去除 70+30 评分、≥70 必挂、footprint 16 组合等系统逻辑，仅以事件与实际走势检验既往判断/挂单与本日观望决策的事后对错；用户今日个人休息无盘中交易，本稿为系统测试样本，不构成投资建议。")]),
]

# 归档旧 🔍 子页后重建
r = requests.get(f"https://api.notion.com/v1/blocks/{DATE_PAGE}/children?page_size=100", headers=H); r.raise_for_status()
for b in r.json()["results"]:
    if b["type"] == "child_page" and b["child_page"]["title"].startswith("🔍"):
        requests.patch(f"https://api.notion.com/v1/pages/{b['id']}", headers=H,
                       data=json.dumps({"archived": True})).raise_for_status()
        print("archived old review:", b["id"])

payload = {"parent": {"type": "page_id", "page_id": DATE_PAGE},
           "properties": {"title": {"title": [{"type": "text", "text": {"content": "🔍 2026.6.6 晚间独立审查（倒推）"}}]}},
           "children": children}
r = requests.post("https://api.notion.com/v1/pages", headers=H, data=json.dumps(payload))
if r.status_code >= 300: print("FAIL", r.status_code, r.text); sys.exit(1)
print("REVIEW PAGE OK ->", r.json()["id"])
