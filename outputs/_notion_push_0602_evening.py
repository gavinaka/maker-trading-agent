# -*- coding: utf-8 -*-
import requests, json, sys, os
TOK=os.environ.get("NOTION_TOKEN","")  # set: $env:NOTION_TOKEN="ntn_..." 再运行（勿硬编码进库）
assert TOK, "请先设置环境变量 NOTION_TOKEN"
H={"Authorization":f"Bearer {TOK}","Notion-Version":"2022-06-28","Content-Type":"application/json"}
DATE_PAGE="373fda35-a098-8155-ae28-c6464ac7ab08"  # 2026.6.2

def t(content, color=None, bold=False):
    item={"type":"text","text":{"content":content}}
    ann={}
    if bold: ann["bold"]=True
    if color: ann["color"]=color
    if ann: item["annotations"]=ann
    return item

def para(runs, color="default"):
    return {"type":"paragraph","paragraph":{"rich_text":runs,"color":color}}
def h2(runs):
    return {"type":"heading_2","heading_2":{"rich_text":runs}}
def h3(runs):
    return {"type":"heading_3","heading_3":{"rich_text":runs}}
def quote(runs):
    return {"type":"quote","quote":{"rich_text":runs}}
def divider():
    return {"type":"divider","divider":{}}

children=[
 quote([t("评分点 20:00 ｜ 现价 69,462（15m 最新；日线收 69,470 / -2.72%，日内低 69,324）。门禁 6/2＝可交易、心力正常无收缩。总评分 74（盘口53+盘面21）≥70 → 必挂 Maker。")]),
 h2([t("不能做："), t("（追）做空", "red", True)]),
 h3([t("基本面："), t("中性偏空", "orange", True),
     t("（机构持续向交易所转入分发：贝莱德存900BTC+17,511ETH进Coinbase、Mt.Gox转116BTC、Tether转204BTC、Hyperscale上周未购；美股AI风险偏好创新高—英伟达硅光量产/光模块普涨7~8%/软银\"AI是互联网泡沫50倍\"—但未提振币市=相对弱势；美伊地缘反复拉锯无新冲击=噪音）"),
     t("价格部分兑现", "green", True)]),
 # 3 evening images inserted after here via PATCH
 h3([t("技术面：")]),
 para([t("盘口（合约）：")]),
 para([t("CVD下降　价格下降　资金费率横盘（为正值 0.0087）　持仓下降", bold=True)]),
 h3([t("解读："), t("利空", "red", True),
     t("（日线放量233M/Delta-7M/CVD累积-45M、POC逐级下移71,430→69,354；1h CVD急跌-18.5K、OI自62K峰回落至57.88K=多头去杠杆离场+主动卖压主导破位。资金费率仍正=残余多头未完全投降→下方仍有去杠杆空间，下跌中继未竭）")]),
 para([t("盘面：")]),
 para([t("日线级别　放量跌破上升平行通道下轨+0.5fib(71,464)，POC逐级下移至69,354，测试0.618日线支撑(68,758)　"), t("利空","red",True)]),
 para([t("小时级别　价跌破多头最后防守(71,000)/大级别共振支撑(72,000)/1H SMA20(70,751)，CVD深跌、OI回落、资金费率仍正　"), t("利空","red",True)]),
 h3([t("趋势确认："), t("空头趋势","red",True), t("（中短线·单边下行）")]),
 h3([t("日内支撑：","",True), t("68,500-68,800","green",True), t("　　日内压力：","",True), t("70,000-70,400","red",True)]),
 h3([t("策略：")]),
 para([t("中线主账户多单 @73,500（30%底仓·5x·1:3·左侧Taker）— 关键止损位 71,000 已被有效跌破（现价69,462）。","red",True),
       t("按既定状态机=触及上升通道下轨止损→止损出局、中线计划终结；浮亏 -5.5%（价格口径，确切-5.49%；5x账户级-27.5%）。Notion条目状态截至校准仍记\"持仓中\"——若尚未离场：严守纪律不再下移止损、不加仓、不抱\"跌深反弹解套\"侥幸（宪法：亏损砍短 盈利放满）。第一/二/三层浮盈防守层(75,500/76,200/74,400)自始未激活。")]),
 divider(),
 h2([t("BTC（策略）：执行概率 60%（已执行 0%）　胜率 70%")]),
 para([t("反弹空：入场 70,000-70,400","red",True),
       t("（破位回踩 user支撑6.2转压力 + 1H SMA20 70,751 共振 = 最近且≥60%可达的高质量反抽空边缘）　持仓 800 刀　Binance　左侧　盈亏比 1:2.5 以上")]),
 para([t("止盈：68,700（TP1·≈0.618日线68,758下沿）减仓50% ／ TP2 67,200（下方流动性）","green",True)]),
 para([t("止损：站稳 70,800 上方（=重夺1H SMA20 70,751/破位回踩失败=结构失效）","red",True)]),
 h3([t("防守计划：")]),
 para([t("第一层：价格触及 69,300（1.5R）　设立4小时级别低点极点为止损 同时取消所有加仓策略",bold=True)]),
 para([t("第二层：价格触及 69,000（2R）　设立保本损",bold=True)]),
 para([t("注意事项：若价格（成交前）优先触及 68,700 则此策略取消（撤未成交挂单）","purple",True)]),
 para([t("⚠️ 取消价(68,700·成交前撤单) ≠ 止损(70,800·成交后离场)","purple",True)]),
 para([t("核心（开仓理由）：日线放量破位+1h CVD深跌+OI去杠杆=空头趋势中继；现价69,462距入场区70,000-70,400仅+0.8~1.4%（破位回踩+1H SMA20共振=高质量反抽空边缘，执行概率≈60%达宪法门槛）；TP1落0.618日线支撑上沿、R:R 1:2.5。挂单于边缘等待，价不触及不成交（绝不追价）。")]),
 para([t("持仓校准：Maker 6/1做多700刀（入场71,000，由防守层1.5R=72,500、2R=73,000反推R=1,000）已止损出局·亏 $11；6/2用户手写做多800刀=未开仓（独立稿不引用方向/理由）。当前Maker无实际持仓。","default")]),
]

page_payload={
    "parent":{"type":"page_id","page_id":DATE_PAGE},
    "properties":{"title":{"title":[{"type":"text","text":{"content":"🌙 2026.6.2 晚间日报（20:00 评分点）"}}]}},
    "children":children
}
r=requests.post("https://api.notion.com/v1/pages",headers=H,data=json.dumps(page_payload))
if r.status_code>=300: print("CREATE FAIL",r.status_code,r.text); sys.exit(1)
new_page=r.json()["id"]
print("EVENING PAGE:",new_page)

# find 基本面 heading, upload 3 evening images, insert after
def get_children(bid):
    r=requests.get(f"https://api.notion.com/v1/blocks/{bid}/children?page_size=100",headers=H); r.raise_for_status()
    return r.json()["results"]
ch=get_children(new_page); basemian=None
for b in ch:
    tp=b["type"]
    if tp in ("heading_3","heading_2"):
        txt="".join(x.get("plain_text","") for x in b[tp]["rich_text"])
        if txt.startswith("基本面"): basemian=b["id"]; break
print("基本面:",basemian)

def upload_image(path,name):
    r=requests.post("https://api.notion.com/v1/file_uploads",headers=H,data=json.dumps({})); r.raise_for_status()
    fu=r.json(); hh={"Authorization":f"Bearer {TOK}","Notion-Version":"2022-06-28"}
    with open(path,"rb") as f:
        r2=requests.post(fu["upload_url"],headers=hh,files={"file":(name,f,"image/png")}); r2.raise_for_status()
    return fu["id"]

base="C:\\Users\\31702\\Desktop\\Trading-System-Code\\outputs\\blockbeats\\"
imgs=["2026-06-02_eve_1_blackrock.png","2026-06-02_eve_2_mtgox.png","2026-06-02_eve_3_hyperscale.png"]
img_blocks=[]
for n in imgs:
    uid=upload_image(base+n,n)
    img_blocks.append({"type":"image","image":{"type":"file_upload","file_upload":{"id":uid}}})
    print("uploaded",n,uid)
patch={"children":img_blocks}
if basemian: patch["after"]=basemian
r=requests.patch(f"https://api.notion.com/v1/blocks/{new_page}/children",headers=H,data=json.dumps(patch))
if r.status_code>=300: print("IMG FAIL",r.status_code,r.text); sys.exit(1)
print("EVENING IMAGES INSERTED OK ->",new_page)
