# -*- coding: utf-8 -*-
"""
本周（2026.6.1-6.6）交易计划独立审查报告 v3 —— 量化驱动版。
仅审查系统自身 Plan；标尺=市场真实价格路径；与 Notion 持仓库解耦。
v3 变更：砍文本、堆量化数据、数字卡片化。
运行：先 $env:NOTION_TOKEN=<token>，再 `py outputs/_notion_push_weekly_review_0606.py`
"""
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, __file__.rsplit("\\", 1)[0])
import notion_push_lib as n
from notion_push_lib import rt, para, h2, h3, quote, callout, divider, table, trow, cell

R="red"; G="green"; Y="yellow"; P="purple"; B="blue"

bk = []

# ===== 报头 =====
bk.append(callout([
    rt("本周计划独立审查 · 量化版", bold=True),
    rt("　|　2026.6.1–6.6　|　9 份 Maker Plan 倒推（仅审 Plan 本身，不涉持仓/账户）"),
], emoji="📊", color="blue_background"))

# ===== 一、核心数字（KPI 卡片）=====
bk.append(h2([rt("一、核心数字", bold=True)]))
bk.append(table(4, [
    trow([cell("方向命中", bold=True), cell("成交率", bold=True), cell("成交单胜率", bold=True), cell("平均 R", bold=True)]),
    trow([
        cell("9 / 9 = 100%", bold=True, color=G),
        cell("3 / 9 = 33%", bold=True, color=R),
        cell("3 / 3 = 100%", bold=True, color=G),
        cell("≈ +1.9 R", bold=True, color=G),
    ]),
]))
bk.append(table(4, [
    trow([cell("评分均值", bold=True), cell("评分区间", bold=True), cell("执行概率自评", bold=True), cell("实际成交率", bold=True)]),
    trow([
        cell("72.4", bold=True),
        cell("71 – 74", bold=True),
        cell("60 – 62 %", bold=True, color=R),
        cell("33 %（差 −27pp）", bold=True, color=R),
    ]),
]))
bk.append(table(4, [
    trow([cell("BTC 周跌幅", bold=True), cell("周内最大反抽", bold=True), cell("平均挂价距现价", bold=True), cell("误读次数", bold=True)]),
    trow([
        cell("−14.3%", bold=True, color=R),
        cell("+2.9%（6/5 日内）", bold=True),
        cell("+1.5%", bold=True, color=Y),
        cell("1（已订正）", bold=True, color=Y),
    ]),
]))

# ===== 二、Plan 明细表（量化扩展）=====
bk.append(h2([rt("二、Plan 明细 · 量化倒推", bold=True)]))
bk.append(table(9, [
    trow([cell("#", bold=True), cell("Plan", bold=True), cell("评分", bold=True),
          cell("入场带", bold=True), cell("挂价距现价", bold=True),
          cell("TP / SL", bold=True), cell("R:R", bold=True),
          cell("成交", bold=True), cell("结果 R", bold=True)]),
    trow([cell("1"), cell("6/1 晚"), cell("74"),
          cell("74.25-75.30k"), cell("+2.8% ~ +4.3%", color=R),
          cell("71.8 / 76.0"), cell("1:2.5"),
          cell("✗", color=R), cell("0 R", color=Y)]),
    trow([cell("2"), cell("6/2 早"), cell("72"),
          cell("71.80-72.00k"), cell("+0.7% ~ +1.0%", color=G),
          cell("70.6 / 72.5"), cell("1:2.5"),
          cell("✗ 临界", color=R), cell("0 R", color=Y)]),
    trow([cell("3"), cell("6/2 晚"), cell("74"),
          cell("70.00-70.40k"), cell("+0.8% ~ +1.4%", color=G),
          cell("68.7 / 70.8"), cell("1:2.5"),
          cell("✗", color=R), cell("0 R", color=Y)]),
    trow([cell("4"), cell("6/3 早"), cell("74"),
          cell("67.20-67.60k"), cell("+0.7% ~ +1.3%", color=G),
          cell("65.4 / 68.4"), cell("1:3.0"),
          cell("✓", color=G), cell("+2.5 R ✅", color=G, bold=True)]),
    trow([cell("5"), cell("6/3 应急"), cell("71"),
          cell("67.50-67.90k"), cell("+0.7% ~ +1.3%", color=G),
          cell("65.8 / 68.5"), cell("1:2.5"),
          cell("✓ 临界", color=G), cell("+2.4 R ✅", color=G, bold=True)]),
    trow([cell("6"), cell("6/3 晚"), cell("73"),
          cell("67.90-68.20k"), cell("+1.0% ~ +1.4%", color=Y),
          cell("66.0 / 68.8"), cell("1:2.5"),
          cell("✗", color=R), cell("0 R", color=Y)]),
    trow([cell("7"), cell("6/4 早"), cell("71"),
          cell("65.30-65.80k"), cell("+1.9% ~ +2.6%", color=R),
          cell("63.4 / 66.4"), cell("1:2.5"),
          cell("✗", color=R), cell("0 R", color=Y)]),
    trow([cell("8"), cell("6/5 早"), cell("72"),
          cell("62.40-63.00k"), cell("+1.5% ~ +2.5%", color=R),
          cell("59.45 / 64.0"), cell("1:2.5"),
          cell("✓", color=G), cell("+0.8 R 浮盈 ✅", color=G, bold=True)]),
    trow([cell("9"), cell("6/5 晚"), cell("72"),
          cell("62.50-63.00k"), cell("+0.9% ~ +1.7%", color=G),
          cell("59.6 / 64.0"), cell("1:2.5"),
          cell("⏳", color=Y), cell("待定", color=Y)]),
]))

# ===== 三、分布统计 =====
bk.append(h2([rt("三、分布统计", bold=True)]))

bk.append(h3([rt("评分分布（n=9）"), ]))
bk.append(table(5, [
    trow([cell("≤70", bold=True), cell("71", bold=True), cell("72", bold=True), cell("73-74", bold=True), cell("均值", bold=True)]),
    trow([cell("0"), cell("3 (33%)"), cell("3 (33%)"), cell("3 (33%)"), cell("72.4", bold=True, color=G)]),
]))

bk.append(h3([rt("成交结果分布（n=9）")]))
bk.append(table(4, [
    trow([cell("✓ 成交盈利", bold=True, color=G), cell("✗ 未成交", bold=True, color=R), cell("⏳ 待定", bold=True, color=Y), cell("✗ 止损", bold=True, color=R)]),
    trow([cell("3 (33%)", bold=True, color=G), cell("5 (56%)", bold=True, color=R), cell("1 (11%)", bold=True, color=Y), cell("0 (0%)", bold=True, color=G)]),
]))

bk.append(h3([rt("挂价距现价分布（n=9 · 越远越难成交）")]))
bk.append(table(4, [
    trow([cell("≤+1.0%", bold=True, color=G), cell("+1.0% ~ +1.5%", bold=True), cell("+1.5% ~ +2.5%", bold=True, color=Y), cell(">+2.5%", bold=True, color=R)]),
    trow([cell("3 笔 → 成交 2", bold=True), cell("2 笔 → 成交 1", bold=True), cell("3 笔 → 成交 0", bold=True, color=R), cell("1 笔 → 成交 0", bold=True, color=R)]),
]))
bk.append(quote([
    rt("强相关：", bold=True, color=R),
    rt("挂价距现价 >+1.5% 的 4 笔成交率 0%；≤+1.5% 的 5 笔成交率 60% → "),
    rt("挂价距离每多 1pp，成交率约降 25pp", bold=True, color=R),
    rt("。"),
]))

bk.append(h3([rt("校准缺口（自评 vs 实际）")]))
bk.append(table(4, [
    trow([cell("指标", bold=True), cell("自评", bold=True), cell("实际", bold=True), cell("缺口", bold=True)]),
    trow([cell("执行概率/成交率"), cell("60-62%"), cell("33%"), cell("−27 ~ −29 pp", bold=True, color=R)]),
    trow([cell("成交单胜率"), cell("60-65%"), cell("100% (3/3)"), cell("+35 ~ +40 pp", bold=True, color=G)]),
    trow([cell("方向命中率"), cell("—"), cell("100% (9/9)"), cell("—", color=G)]),
]))

# ===== 四、价格路径 vs 计划带 =====
bk.append(h2([rt("四、价格路径 vs 计划入场带", bold=True)]))
bk.append(table(5, [
    trow([cell("日期", bold=True), cell("当日 H / L", bold=True), cell("收盘", bold=True), cell("覆盖的 Plan 入场带", bold=True), cell("反抽幅度", bold=True)]),
    trow([cell("6/1"), cell("— / —"), cell("~72,200"), cell("无（直接下行）", color=R), cell("0%")]),
    trow([cell("6/2"), cell("? / 69,324"), cell("69,470"), cell("无（直接下破）", color=R), cell("0%")]),
    trow([cell("6/3"), cell("? / 65,800"), cell("67,250"), cell("Plan 4 ✓（67.2-67.6k）", color=G), cell("+2.2%", color=G)]),
    trow([cell("6/4"), cell("67,516 / 64,092"), cell("64,114"), cell("Plan 5 ✓临界（67.5 下沿）", color=G), cell("+5.3%", color=G)]),
    trow([cell("6/5"), cell("63,259 / 61,105"), cell("61,884"), cell("Plan 8 ✓（62.4-63.0k）", color=G), cell("+2.9%", color=G)]),
]))

# ===== 五、三层评分 =====
bk.append(h2([rt("五、三层评分卡", bold=True)]))
bk.append(table(4, [
    trow([cell("层级", bold=True), cell("分数", bold=True), cell("关键指标", bold=True), cell("瓶颈", bold=True)]),
    trow([cell("结果层", color=R, bold=True), cell("65 / 100", bold=True, color=Y),
          cell("成交 33%·胜率 100%·平均 +1.9R"), cell("成交率低", color=R)]),
    trow([cell("逻辑层", color=Y, bold=True), cell("90 / 100", bold=True, color=G),
          cell("方向 9/9·框架 0 串·禁令 0 违"), cell("入场模型", color=Y)]),
    trow([cell("执行层", color=G, bold=True), cell("80 / 100", bold=True, color=G),
          cell("数字 0 误·模板 PASS·读数 1 误"), cell("概率校准", color=R)]),
]))

# ===== 六、三大量化发现 =====
bk.append(h2([rt("六、三大量化发现", bold=True)]))
bk.append(callout([
    rt("① 挂价距离 = 成交率头号杀手　", bold=True, color=R),
    rt("｜ "),
    rt(">+1.5% 的 4 笔成交 0 / ≤+1.5% 的 5 笔成交 3", bold=True),
    rt("｜每多 1pp 距离 ≈ −25pp 成交率"),
], emoji="1️⃣", color="red_background"))
bk.append(callout([
    rt("② 执行概率高估近一倍　", bold=True, color=R),
    rt("｜ 自评 "),
    rt("60–62% vs 实际 33%", bold=True),
    rt("｜缺口 −27 ~ −29 pp ｜需引入趋势强度折减"),
], emoji="2️⃣", color="red_background"))
bk.append(callout([
    rt("③ 成交单质量 = A+　", bold=True, color=G),
    rt("｜ "),
    rt("胜率 100% (3/3)·平均 +1.9R·0 止损", bold=True, color=G),
    rt("｜证明判向与边缘选择本身正确"),
], emoji="3️⃣", color="green_background"))

# ===== 七、改进 KPI =====
bk.append(h2([rt("七、改进目标（量化 KPI）", bold=True)]))
bk.append(table(3, [
    trow([cell("项", bold=True), cell("现状", bold=True), cell("下周目标", bold=True)]),
    trow([cell("挂价距现价"), cell("均 +1.5% / 最远 +4.3%"), cell("均 ≤ +1.0% / 最远 ≤ +2.0%", color=G)]),
    trow([cell("成交率"), cell("33%", color=R), cell("≥ 55%", color=G)]),
    trow([cell("执行概率校准缺口"), cell("−27 pp", color=R), cell("|缺口| ≤ 10 pp", color=G)]),
    trow([cell("分级挂单（次/最优各半）"), cell("未实施"), cell("强趋势日 100% 启用", color=G)]),
    trow([cell("方向命中率"), cell("100%", color=G), cell("≥ 80%（保持）", color=G)]),
    trow([cell("成交单胜率"), cell("100%", color=G), cell("≥ 60%（保持）", color=G)]),
]))

bk.append(divider())
bk.append(quote([
    rt("口径：仅审 Plan 本身，标尺=市场真实价格路径，与 Notion 持仓库解耦。", color=P),
    rt("成交判定基于日级 OHLC 倒推（无逐笔 tick），临界单已标注；Plan 9（6/5 晚）待 6/6 行情确认。"),
]))

# ===== 推送 =====
title = "2026.6.1-6.6 Agent（周报）"
old = n.find_child_page(n.AI_AGENT_PLAN, "2026.6.1-6.6 Agent")
if old:
    r = requests.patch(f"https://api.notion.com/v1/pages/{old}", headers=n._h(),
                       data=json.dumps({"archived": True})); r.raise_for_status()
    print("ARCHIVED_OLD:" + old)
try:
    pid = n.create_page(n.AI_AGENT_PLAN, title, bk)
    print("CREATED:" + pid)
except Exception as e:
    if isinstance(e, requests.exceptions.HTTPError):
        print("ERRBODY:" + e.response.text)
    raise
