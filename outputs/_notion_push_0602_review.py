# -*- coding: utf-8 -*-
import requests, json, sys, os
TOK=os.environ.get("NOTION_TOKEN","")  # set: $env:NOTION_TOKEN="ntn_..." 再运行
assert TOK, "请先设置环境变量 NOTION_TOKEN"
H={"Authorization":f"Bearer {TOK}","Notion-Version":"2022-06-28","Content-Type":"application/json"}
DATE_PAGE="373fda35-a098-8155-ae28-c6464ac7ab08"  # 2026.6.2

def t(c,color=None,bold=False):
    it={"type":"text","text":{"content":c}}; a={}
    if bold:a["bold"]=True
    if color:a["color"]=color
    if a:it["annotations"]=a
    return it
def para(runs,color="default"): return {"type":"paragraph","paragraph":{"rich_text":runs,"color":color}}
def h2(c): return {"type":"heading_2","heading_2":{"rich_text":[t(c)]}}
def callout(runs,emoji="⚠️",color="orange_background"):
    return {"type":"callout","callout":{"rich_text":runs,"icon":{"emoji":emoji},"color":color}}
def cell(c,color=None,bold=False): return [t(c,color,bold)]
def row(cells): return {"type":"table_row","table_row":{"cells":cells}}
def table(width,rows,header=True):
    return {"type":"table","table":{"table_width":width,"has_column_header":header,"has_row_header":False,"children":rows}}

children=[
 callout([t("倒推回测：11:00 @71,285 → 20:00 @"),t("69,462","green"),t("（"),t("−2.56%","red",True),
          t("，单边下行、几乎收最低）。方向（看空）被走势证实"),t("正确","green",True),
          t("；但早间反弹空挂 71,800-72,000 等反弹，价格反向下走、"),t("从未成交＝0 参与","red",True),t("。")],
         "🔍","gray_background"),

 h2("综合评分（去系统逻辑 · 独立打分）"),
 table(3,[
   row([cell("维度",bold=True),cell("🌅 早间",bold=True),cell("🌙 晚间",bold=True)]),
   row([cell("方向判断"),cell("90","green"),cell("92","green")]),
   row([cell("入场结构"),cell("60","orange"),cell("85","green")]),
   row([cell("风险框架"),cell("72","yellow"),cell("88","green")]),
   row([cell("数据精度"),cell("92","green"),cell("93","green")]),
   row([cell("内在一致性"),cell("70","yellow"),cell("88","green")]),
   row([cell("综合",bold=True),cell("77 / B","yellow",True),cell("89 / A−","green",True)]),
 ]),

 h2("价格阶梯 · 两份挂单落点（倒推）"),
 table(3,[
   row([cell("价位",bold=True),cell("标记",bold=True),cell("说明",bold=True)]),
   row([cell("71,800–72,000"),cell("早间空·未成交","red"),cell("挂现价上方等反弹→价格反向走，估60%可达、实际0%")]),
   row([cell("71,285"),cell("11:00 起点","blue"),cell("早间现价")]),
   row([cell("71,000"),cell("跌穿","red"),cell("多头最后防守 + 主账户多单止损位 双双击穿")]),
   row([cell("70,000–70,400"),cell("晚间空·挂单中","yellow"),cell("破位回踩带，距现价+0.8~1.4%，比早间更易成交")]),
   row([cell("69,462"),cell("20:00 当前","green"),cell("晚间现价")]),
   row([cell("68,758"),cell("晚间 TP1","green"),cell("0.618 日线，R:R 1:2.5 落点合理")]),
 ]),

 callout([t("核心矛盾（最该看）：","orange",True),
   t("今天是干净的单边下跌日——奖励「破位顺势空」、惩罚「等完美反弹」。两份方向都对，但唯一被允许的交易（反弹空）"),
   t("早间根本没触发","red",True),
   t("，价格直接往下走。真正吃到这波的是 71,000 跌穿顺势追空（被定义为「不能做·右侧追空」而禁止）。结构性代价＝"),
   t("高胜率/安全成交 ⇄ 强趋势日错过主跌段","orange",True),
   t("。今天它让「判断对、却没赚到」成为现实。")],"⚠️","orange_background"),

 h2("关键发现（倒推得出）"),
 para([t("① 方向全程稳","green",True),t("：CVD↓+OI↓+资金费率仍正(多头未投降)+放量破位，早间即指向下方仍有去杠杆空间，被−2.6%续跌验证；两份方向都合格，晚间表述更锐利。")]),
 para([t("② 早间入场结构是最大短板","orange",True),t("：预期续跌却把空单挂在现价上方+0.7~1.0%等反弹，逻辑自相矛盾→never fill，−2.6%一分没参与；「执行概率~60%」在强趋势里高估。")]),
 para([t("③ 主账户多单是真正失血点，且与自家看空判断打架","red",True),t("：全天看空却扛5x多单(@73,500)，早间−3.0%→晚间−5.5%(账户级约−27.5%)、止损71,000被击穿。「死守71,000」让一张方向已被自己证伪的多单又多亏2.5%。当5/5源看空时，持多本身就是该红色警告的最大风险，而非「守纪律」。")]),
 para([t("④ 早间「日内支撑70,600-71,000」被秒穿","yellow",True),t("：把71,000当强支撑，但同份报告的盘口信号(多头未投降)其实预示守不住=支撑判断与动能读数没对齐。晚间下修到68,500-68,800(0.618日线)更稳。")]),
 para([t("⑤ 晚间是明显进步","green",True),t("：空单下移70,000-70,400(仅+0.8~1.4%、可成交性远高)，TP1锚0.618日线、R:R 1:2.5干净，执行概率诚实压到60%，并第一时间点名「主账户止损已破·应止损出局」。")]),
 para([t("⑥ 数据精度合格","green",True),t("：价格/百分比皆核过确切值(69,462/−5.49%/POC69,354)，跨5~6源交叉一致、POC与现价吻合，无模糊位。")]),

 para([t("一句话：","gray",True),t("看得对、却没赚到、还亏在不该扛的多单上。分析质量(方向+数据)A级，交易转化(早间入场结构)和对自相矛盾持仓的处理力度是短板；晚间已修好入场，唯一没解决的是那张逆向多单。","gray")]),
]

# 防重复
r=requests.get(f"https://api.notion.com/v1/blocks/{DATE_PAGE}/children?page_size=100",headers=H); r.raise_for_status()
for b in r.json()["results"]:
    if b["type"]=="child_page" and b["child_page"]["title"].startswith("🔍"):
        print("ABORT: 审查子页已存在 ->",b["id"]); sys.exit(0)

payload={"parent":{"type":"page_id","page_id":DATE_PAGE},
  "properties":{"title":{"title":[{"type":"text","text":{"content":"🔍 2026.6.2 晚间独立审查（倒推）"}}]}},
  "children":children}
r=requests.post("https://api.notion.com/v1/pages",headers=H,data=json.dumps(payload))
if r.status_code>=300: print("FAIL",r.status_code,r.text); sys.exit(1)
print("REVIEW PAGE OK ->",r.json()["id"])
