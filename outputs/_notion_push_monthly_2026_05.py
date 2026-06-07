# -*- coding: utf-8 -*-
"""
2026-05 交易日志（月报）—— 按 templates/monthly_review.md 100% 对称渲染。
数据源：Notion（主）交易Check + （Maker）交易Check + 系统50笔（洁净样本）库，全部实际记录核实。
用户专属字段（月末余额=用户提供；小结/核心问题复盘/下月目标=用户自填，留占位）。
运行：先 $env:NOTION_TOKEN=<token>，再 `py outputs/_notion_push_monthly_2026_05.py`
"""
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, __file__.rsplit("\\", 1)[0])
import notion_push_lib as n
from notion_push_lib import rt, para, h2, h3, quote, callout, divider, table, trow, cell

R="red"; G="green"; Y="yellow"; P="purple"; B="blue"
TODO = "📝 待补写（用户自填·模板禁止 AI 生成）"

bk = []

# ===== 报头 =====
bk.append(callout([
    rt("2026-05 交易日志（月报）", bold=True),
], emoji="📅", color="blue_background"))
bk.append(quote([
    rt("周期：2026-05-01 ~ 2026-05-31　|　关键词体系："),
    rt("洁净样本打造期", bold=True),
    rt("　|　数据源：Notion（主/Maker）交易Check + 系统50笔库（实际记录核实）"),
]))
bk.append(divider())

# ===== 一、资金仓位复盘 =====
bk.append(h2([rt("一、资金仓位复盘", bold=True)]))
bk.append(table(2, [
    trow([cell("项", bold=True), cell("金额 (USD)", bold=True)]),
    trow([cell("本金"), cell("1200")]),
    trow([cell("现有资金（OKX）"), cell("208")]),
    trow([cell("现有资金（Binance）"), cell("290")]),
    trow([cell("合计"), cell("498", bold=True)]),
    trow([cell("净亏损总额"), cell("702", bold=True, color=R)]),
    trow([cell("同比上月"), cell("−2%（约 −$10）", bold=True, color=R)]),
]))
bk.append(para([rt("小结：", bold=True), rt(TODO, color=Y)]))

# ===== 二、持仓情况 =====
bk.append(h2([rt("二、持仓情况", bold=True)]))
bk.append(h3([rt("主账户（Binance）")]))
bk.append({"type":"bulleted_list_item","bulleted_list_item":{"rich_text":[
    rt("当前持仓："), rt("月末已平仓", bold=True),
    rt("（5/28 中线做多 BTCUSDT @73,500 / $1,000 / 30% 底仓 / 5x）")]}})
bk.append({"type":"bulleted_list_item","bulleted_list_item":{"rich_text":[
    rt("浮盈/浮亏："), rt("−$40", bold=True, color=R), rt("（已实现·止损出局 68,000）")]}})
bk.append({"type":"bulleted_list_item","bulleted_list_item":{"rich_text":[
    rt("防守层级：第 0 层 → "), rt("触发第 3/5 层", bold=True, color=R)]}})
bk.append({"type":"bulleted_list_item","bulleted_list_item":{"rich_text":[
    rt("月内迭代次数："), rt("1", bold=True)]}})
bk.append(h3([rt("Maker（OKX）")]))
bk.append({"type":"bulleted_list_item","bulleted_list_item":{"rich_text":[
    rt("当前持仓："), rt("无", bold=True), rt("（最后一笔 5/29 做多止损 −$9 后空仓）")]}})
bk.append({"type":"bulleted_list_item","bulleted_list_item":{"rich_text":[
    rt("月末资金："), rt("208 USD", bold=True)]}})

# ===== 三、策略复盘 =====
bk.append(h2([rt("三、策略复盘", bold=True)]))

bk.append(h3([rt("Maker 账户")]))
bk.append(table(2, [
    trow([cell("指标", bold=True), cell("本月", bold=True)]),
    trow([cell("策略笔数"), cell("9 成交 / 15 计划（含 6 未触发）")]),
    trow([cell("击中率（胜率）"), cell("22%（2/9）｜剔除保本 50%（2/4）")]),
    trow([cell("总盈亏 (USD)"), cell("−$8", bold=True, color=R)]),
    trow([cell("PCT"), cell("−2.5%（逐笔 PCT 净额）", bold=True, color=R)]),
    trow([cell("平均盈亏比"), cell("1:2.5（计划值·14/15 笔）")]),
    trow([cell("洁净样本贡献"), cell("9 笔", bold=True, color=G)]),
]))
bk.append(para([rt("小结：", bold=True), rt(TODO, color=Y)]))

bk.append(h3([rt("主账户中线计划")]))
bk.append(table(2, [
    trow([cell("指标", bold=True), cell("本月", bold=True)]),
    trow([cell("持仓天数"), cell("~1 天（5/28 开 → 止损平）")]),
    trow([cell("防守层级演变"), cell("第 0 层 → 第 3 层（触发）")]),
    trow([cell("浮盈/浮亏（月末）"), cell("−$40（已平仓实现）", bold=True, color=R)]),
    trow([cell("PCT（持仓累计）"), cell("−8%", bold=True, color=R)]),
    trow([cell("月内是否减仓 / 加仓"), cell("否（未达 TP1·直接止损出局）")]),
]))
bk.append(para([rt("小结：", bold=True), rt(TODO, color=Y)]))

# ===== 四、ALL Review =====
bk.append(h2([rt("四、ALL Review", bold=True)]))

bk.append(h3([rt("整月核心问题复盘（≥ 3 条）")]))
bk.append(para([rt(TODO, color=Y)]))
bk.append({"type":"numbered_list_item","numbered_list_item":{"rich_text":[rt("（发现 + 影响 + 反思）")],"color":"gray"}})
bk.append({"type":"numbered_list_item","numbered_list_item":{"rich_text":[rt("……")],"color":"gray"}})
bk.append({"type":"numbered_list_item","numbered_list_item":{"rich_text":[rt("……")],"color":"gray"}})

bk.append(h3([rt("违规与洁净样本")]))
bk.append(table(2, [
    trow([cell("项", bold=True), cell("本月", bold=True)]),
    trow([cell("违规笔数"), cell("0", bold=True, color=G)]),
    trow([cell("重度违规"), cell("0")]),
    trow([cell("中度违规"), cell("0")]),
    trow([cell("轻度违规"), cell("0")]),
    trow([cell("洁净样本累计"), cell("20 / 50（40%）", bold=True, color=G)]),
    trow([cell("本月新增洁净"), cell("9", bold=True, color=G)]),
]))
bk.append(para([rt("主要违规类型与诱因：", bold=True),
                rt("无 —— 本月 0 违规（15 笔计划全部 按计划=是 / 情绪化=否 / 风控 7 项全过）", color=G)]))

bk.append(h3([rt("下月目标（≥ 3 条·具体可执行）")]))
bk.append(para([rt(TODO, color=Y)]))
bk.append({"type":"numbered_list_item","numbered_list_item":{"rich_text":[rt("（必须含数字/动作·禁空话）")],"color":"gray"}})
bk.append({"type":"numbered_list_item","numbered_list_item":{"rich_text":[rt("……")],"color":"gray"}})
bk.append({"type":"numbered_list_item","numbered_list_item":{"rich_text":[rt("……")],"color":"gray"}})

# ===== 历史财务对照（模板强制·近 4 月趋势）=====
bk.append(divider())
bk.append(h2([rt("历史财务对照（近 4 月趋势）", bold=True)]))
bk.append(table(4, [
    trow([cell("月", bold=True), cell("本金", bold=True), cell("月末资金", bold=True), cell("净亏损", bold=True)]),
    trow([cell("2026-01"), cell("1200"), cell("750"), cell("450")]),
    trow([cell("2026-03"), cell("1200"), cell("500"), cell("700")]),
    trow([cell("2026-04"), cell("1200"), cell("490"), cell("710")]),
    trow([cell("2026-05", bold=True), cell("1200", bold=True), cell("498", bold=True), cell("702", bold=True, color=R)]),
]))

# ===== 附：逐笔明细（数据可追溯·支撑上方统计）=====
bk.append(divider())
bk.append(h2([rt("附：5 月逐笔明细（数据源 · Notion 交易Check）", bold=True)]))

bk.append(h3([rt("Maker（OKX）· 15 条")]))
bk.append(table(7, [
    trow([cell("日期", bold=True), cell("方向/侧", bold=True), cell("量", bold=True),
          cell("状态", bold=True), cell("结果", bold=True), cell("盈亏", bold=True), cell("洁净", bold=True)]),
    trow([cell("5/06"), cell("空/左"), cell("800"), cell("已平"), cell("保本出局"), cell("$0", color=Y), cell("✓", color=G)]),
    trow([cell("5/06"), cell("空/左"), cell("1000"), cell("已平"), cell("止损"), cell("−$12", color=R), cell("✓", color=G)]),
    trow([cell("5/08"), cell("空/左"), cell("700"), cell("未触发", color=Y), cell("注意事项取消"), cell("—"), cell("—")]),
    trow([cell("5/10"), cell("空/左"), cell("800"), cell("已平"), cell("保本出局"), cell("$0", color=Y), cell("✓", color=G)]),
    trow([cell("5/11"), cell("空/左"), cell("800"), cell("已平"), cell("保本出局"), cell("$0", color=Y), cell("✓", color=G)]),
    trow([cell("5/12"), cell("空/左"), cell("700"), cell("已平"), cell("保本出局"), cell("$0", color=Y), cell("✓", color=G)]),
    trow([cell("5/15"), cell("空/左"), cell("800"), cell("未触发", color=Y), cell("注意事项取消"), cell("—"), cell("—")]),
    trow([cell("5/18"), cell("多/左"), cell("800"), cell("已平"), cell("止盈 TP1"), cell("+$3", color=G), cell("✓", color=G)]),
    trow([cell("5/18"), cell("空/右"), cell("800"), cell("已平"), cell("止盈离场"), cell("+$10", color=G), cell("✓", color=G)]),
    trow([cell("5/24"), cell("空/右"), cell("750"), cell("已平"), cell("保本出局"), cell("$0", color=Y), cell("✓", color=G)]),
    trow([cell("5/24"), cell("多/左"), cell("800"), cell("未触发", color=Y), cell("注意事项取消"), cell("—"), cell("—")]),
    trow([cell("5/27"), cell("多/左"), cell("800"), cell("未触发", color=Y), cell("取消(评分未达)"), cell("—"), cell("—")]),
    trow([cell("5/28"), cell("空/右"), cell("800"), cell("未触发", color=Y), cell("注意事项取消"), cell("—"), cell("—")]),
    trow([cell("5/29"), cell("多/左"), cell("800"), cell("已平"), cell("止损"), cell("−$9", color=R), cell("✓", color=G)]),
    trow([cell("5/31"), cell("空/右"), cell("800"), cell("未触发", color=Y), cell("注意事项取消"), cell("—"), cell("—")]),
]))
bk.append(quote([
    rt("汇总：", bold=True),
    rt("成交 9（空 7 / 多 2）· 盈利 2 / 止损 2 / 保本 5 · 净 "),
    rt("−$8", bold=True, color=R),
    rt("；未触发 6（注意事项/评分门槛拦截）。9 笔成交全洁净 → 洁净样本 +9。"),
]))

bk.append(h3([rt("主账户（Binance）· 1 条")]))
bk.append(table(7, [
    trow([cell("日期", bold=True), cell("方向/侧", bold=True), cell("量/杠杆", bold=True),
          cell("状态", bold=True), cell("结果", bold=True), cell("盈亏/PCT", bold=True), cell("洁净", bold=True)]),
    trow([cell("5/28"), cell("多/左 Taker"), cell("$1000 / 5x"), cell("已平"),
          cell("第3层防守·止损 68,000"), cell("−$40 / −8%", color=R), cell("✓", color=G)]),
]))

bk.append(divider())
bk.append(quote([
    rt("口径说明：", bold=True, color=P),
    rt("月末余额为用户提供（OKX 208 + Binance 290 = 498）；同比上月 −2% 按用户口径（与历史表 4 月末 $490 略有出入，待订正）。"
       "小结 / 核心问题复盘 / 下月目标 模板禁止 AI 生成，留占位待用户自填。其余量化数据全部源自 Notion 实际交易记录核实。"),
]))

# ===== 推送（AI agent plan 顶层子页·与周报同级）=====
title = "2026.5 Agent（月报）"
old = n.find_child_page(n.AI_AGENT_PLAN, "2026.5 Agent（月报）")
if old:
    r = requests.patch(f"https://api.notion.com/v1/pages/{old}", headers=n._h(),
                       data=json.dumps({"archived": True})); r.raise_for_status()
    print("ARCHIVED_OLD:" + old)
try:
    pid = n.create_page(n.AI_AGENT_PLAN, title, bk)
    print("CREATED:" + pid)
    print("BLOCKS:" + str(len(bk)))
except Exception as e:
    if isinstance(e, requests.exceptions.HTTPError):
        print("ERRBODY:" + e.response.text)
    raise
