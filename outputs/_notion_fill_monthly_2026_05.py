# -*- coding: utf-8 -*-
"""
回填 2026.5 Agent（月报）的 4 处占位：三段小结 + 整月核心问题复盘 + 下月目标。
内容基于 Notion 实际 5 月记录（主/Maker 交易Check + 系统50笔库）撰写。
运行：先 $env:NOTION_TOKEN=<token>，再 `py outputs/_notion_fill_monthly_2026_05.py`
"""
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, __file__.rsplit("\\", 1)[0])
import notion_push_lib as n
from notion_push_lib import rt

R="red"; G="green"; Y="yellow"; P="purple"
PAGE = "377fda35-a098-8198-90c2-d88c5d7efbdd"

def num(runs, color="default"):
    return {"type":"numbered_list_item","numbered_list_item":{"rich_text":runs,"color":color}}
def update(bid, payload):
    r = requests.patch(f"https://api.notion.com/v1/blocks/{bid}", headers=n._h(),
                       data=json.dumps(payload)); r.raise_for_status()
def delete(bid):
    r = requests.delete(f"https://api.notion.com/v1/blocks/{bid}", headers=n._h()); r.raise_for_status()

# ---------- 内容 ----------
sum_capital = [
    rt("小结：", bold=True),
    rt("本月交易实现盈亏约 主账户 "), rt("−$40", color=R), rt(" ＋ Maker "), rt("−$8", color=R),
    rt(" ＝ "), rt("−$48", bold=True, color=R),
    rt("；月末合计 "), rt("498U", bold=True), rt("（OKX 208 ＋ Binance 290），净亏损累计 "),
    rt("702U", bold=True, color=R), rt("，同比上月 "), rt("−2%", bold=True, color=R),
    rt("。回撤几乎全部来自主账户唯一一笔中线止损，Maker 日内全月近乎走平、未失血；本月以控制回撤、打磨洁净样本为主，未追加本金。"),
]
sum_maker = [
    rt("小结：", bold=True),
    rt("全月 15 条计划、"),
    rt("9 笔成交，6 笔被「注意事项／评分门槛」拦截未触发", bold=True),
    rt("（拦截率 40%，门槛在起作用、没有乱开）。9 笔成交 "),
    rt("全部洁净", bold=True, color=G),
    rt("（按计划=是／情绪化=否／风控 7 项全过），"), rt("0 违规", color=G), rt("，贡献 "),
    rt("9 个洁净样本", bold=True, color=G),
    rt("（累计 11→20 / 50）。结果 2 盈（+3／+10）2 损（−12／−9）5 保本，胜率偏低（"),
    rt("22%", color=R),
    rt("），但 "), rt("保本占比 5/9", bold=True),
    rt(" 说明防守计划执行到位、把多数无效单压回保本而非亏损。短板：方向偏空（成交 7/9 为空）遇 5 月震荡、空单兑现不充分，盈利单偏小、盈亏比兑现不足。"),
]
sum_mid = [
    rt("小结：", bold=True),
    rt("全月仅 1 笔中线计划（5/28 结构性支撑反弹做多 @73,500，底仓 30%／$1000／5x）。设三层防守（75,500／76,200／74,400），实际因「流动性持续流出＋买方势能极弱、反弹力度打折」价格未上行兑现 TP1（78,000），逐层下移止损后于 "),
    rt("68,000 触发第三层止损出局", bold=True, color=R), rt("，"),
    rt("−$40 / PCT −8%", bold=True, color=R),
    rt("，月内迭代 1 次、未减仓。要点：在中短线空头趋势里做逆势反弹多是本月唯一回撤来源；防守纪律执行到位（按计划止损、无情绪化、0 违规），问题在入场时机与结构判断——支撑反弹假设未成立。"),
]

problems = [
    [rt("中线「逆势抄反弹」是本月唯一实质亏损源：", bold=True, color=R),
     rt("5/28 在中短线空头趋势里做结构性支撑反弹多，TP 未及即逐层止损出局（−$40／−8%）。发现：弱势结构＋流动性持续流出时「支撑反弹」假设胜率低；影响：贡献本月几乎全部账户回撤；反思：中线逆势单需更严格的反转确认（不止支撑位，还要 CVD／买盘势能转向），否则宁可不做。")],
    [rt("Maker 胜率偏低、被防守纪律兜住：", bold=True),
     rt("9 笔成交仅 2 盈、5 保本，胜率 22%。发现：方向偏空（7/9）遇 5 月震荡、空单兑现不充分，盈利单偏小（+3／+10）盈亏比不足；影响：全月净 −$8、几乎走平、未盈利；反思：震荡市靠笔数无效，要在 TP1 兑现节奏与入场质量上提升。")],
    [rt("门槛／纪律是本月最大亮点：", bold=True, color=G),
     rt("15 计划 6 笔被注意事项／评分门槛拦截（40%），9 笔成交 0 违规、全洁净，洁净样本 11→20（+9，达 40%）。发现：「允许错过、不允许乱做」在执行；影响：在亏损月把随机性与违规压到 0；反思：保持，这是样本工程的核心资产。")],
]
goals = [
    [rt("洁净样本从 20/50 推进到 "), rt("≥ 26/50", bold=True, color=G), rt("（6 月新增 ≥ 6 笔洁净成交）。")],
    [rt("中线逆势反弹一律加挂「反转确认」前置：", bold=True),
     rt("无 CVD／买盘势能转向不入场；6 月中线最大单笔回撤 "), rt("≤ −5%", bold=True, color=R), rt("。")],
    [rt("Maker 盈亏比兑现：成交单平均实现 "), rt("R ≥ 1:1.5", bold=True, color=G),
     rt("，止损单占比 "), rt("≤ 30%", bold=True), rt("。")],
    [rt("维持 "), rt("0 违规、成交单 100% 洁净", bold=True, color=G), rt("（保持本月水平）。")],
]

# ---------- 定位 block ----------
kids = n.get_children(PAGE)
def txt(b):
    t=b["type"]
    return "".join(x.get("plain_text","") for x in b.get(t,{}).get("rich_text",[])) if "rich_text" in b.get(t,{}) else ""

last_h2=last_h3=""
cap_id=maker_id=mid_id=None
prob_para=None; prob_items=[]
goal_para=None; goal_items=[]
cur=None  # 'prob' or 'goal'
for b in kids:
    t=b["type"]; s=txt(b)
    if t=="heading_2":
        last_h2=s; last_h3=""; cur=None
    elif t=="heading_3":
        last_h3=s
        if s.startswith("整月核心问题复盘"): cur="prob"
        elif s.startswith("下月目标"): cur="goal"
        else: cur=None
    elif t=="paragraph" and s.startswith("小结："):
        if last_h2.startswith("一、资金仓位复盘") and not last_h3: cap_id=b["id"]
        elif last_h3.startswith("Maker 账户"): maker_id=b["id"]
        elif last_h3.startswith("主账户中线计划"): mid_id=b["id"]
    elif t=="paragraph" and s.startswith("📝"):
        if cur=="prob": prob_para=b["id"]
        elif cur=="goal": goal_para=b["id"]
    elif t=="numbered_list_item":
        if cur=="prob": prob_items.append(b["id"])
        elif cur=="goal": goal_items.append(b["id"])

assert cap_id and maker_id and mid_id, f"小结定位失败 cap={cap_id} maker={maker_id} mid={mid_id}"
assert len(prob_items)>=3 and len(goal_items)>=3, f"列表定位失败 prob={len(prob_items)} goal={len(goal_items)}"

# ---------- 写入 ----------
update(cap_id,   {"paragraph":{"rich_text":sum_capital}})
update(maker_id, {"paragraph":{"rich_text":sum_maker}})
update(mid_id,   {"paragraph":{"rich_text":sum_mid}})

if prob_para: delete(prob_para)
for i in range(3): update(prob_items[i], {"numbered_list_item":{"rich_text":problems[i],"color":"default"}})

if goal_para: delete(goal_para)
for i in range(3): update(goal_items[i], {"numbered_list_item":{"rich_text":goals[i],"color":"default"}})
# 第 4 条目标：在第 3 条之后插入
n.insert_after(PAGE, goal_items[2], [num(goals[3])])

print("DONE cap/maker/mid + 3 problems + 4 goals filled")
