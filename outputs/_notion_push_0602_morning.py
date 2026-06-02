# -*- coding: utf-8 -*-
import requests, json, sys, os
TOK=os.environ.get("NOTION_TOKEN","")  # set: $env:NOTION_TOKEN="ntn_..." 再运行（勿硬编码进库）
assert TOK, "请先设置环境变量 NOTION_TOKEN"
H={"Authorization":f"Bearer {TOK}","Notion-Version":"2022-06-28","Content-Type":"application/json"}
DATE_PAGE="373fda35-a098-8155-ae28-c6464ac7ab08"  # 2026.6.2
TEXT_TYPES={"paragraph","heading_1","heading_2","heading_3","quote","bulleted_list_item","numbered_list_item","callout","toggle"}

def get_children(bid):
    out=[]; cur=None
    while True:
        u=f"https://api.notion.com/v1/blocks/{bid}/children?page_size=100"
        if cur: u+=f"&start_cursor={cur}"
        r=requests.get(u,headers=H); r.raise_for_status(); d=r.json()
        out+=d["results"]
        if d.get("has_more"): cur=d["next_cursor"]
        else: break
    return out

def rt_copy(rts):
    res=[]
    for rt in rts:
        if rt["type"]!="text":
            res.append({"type":"text","text":{"content":rt.get("plain_text","")}}); continue
        item={"type":"text","text":{"content":rt["text"]["content"]}}
        if rt["text"].get("link"): item["text"]["link"]=rt["text"]["link"]
        a=rt.get("annotations")
        if a: item["annotations"]={k:a[k] for k in ("bold","italic","strikethrough","underline","code","color")}
        res.append(item)
    return res

def block_copy(b):
    t=b["type"]
    if t=="divider": return {"type":"divider","divider":{}}
    if t in TEXT_TYPES:
        src=b[t]; payload={"rich_text":rt_copy(src.get("rich_text",[]))}
        if "color" in src: payload["color"]=src["color"]
        return {"type":t,t:payload}
    return None  # images handled separately

def upload_image(path,name):
    r=requests.post("https://api.notion.com/v1/file_uploads",headers=H,data=json.dumps({}))
    r.raise_for_status(); fu=r.json()
    uid=fu["id"]; url=fu["upload_url"]
    hh={"Authorization":f"Bearer {TOK}","Notion-Version":"2022-06-28"}
    with open(path,"rb") as f:
        r2=requests.post(url,headers=hh,files={"file":(name,f,"image/png")})
    r2.raise_for_status()
    return uid

# 1. fetch morning blocks
morning=get_children(DATE_PAGE)
text_children=[]; img_after_basemian=[]
for b in morning:
    if b["type"]=="image": continue
    bc=block_copy(b)
    if bc: text_children.append(bc)
print("text blocks to recreate:",len(text_children))

# 2. create 早间 child page with text children
page_payload={
    "parent":{"type":"page_id","page_id":DATE_PAGE},
    "properties":{"title":{"title":[{"type":"text","text":{"content":"🌅 2026.6.2 早间日报（11:00 评分点）"}}]}},
    "children":text_children[:100]
}
r=requests.post("https://api.notion.com/v1/pages",headers=H,data=json.dumps(page_payload))
if r.status_code>=300: print("CREATE FAIL",r.status_code,r.text); sys.exit(1)
new_page=r.json()["id"]
print("MORNING PAGE:",new_page)

# 3. find 基本面 heading id in new page, upload 3 images, insert after it
ch=get_children(new_page)
basemian=None
for b in ch:
    t=b["type"]
    if t in ("heading_3","heading_2"):
        txt="".join(x.get("plain_text","") for x in b[t]["rich_text"])
        if txt.startswith("基本面"): basemian=b["id"]; break
print("基本面 heading:",basemian)
imgs=[("2026-06-02_1_fear.png","C:\\Users\\31702\\Desktop\\Trading-System-Code\\outputs\\blockbeats\\2026-06-02_1_fear.png"),
      ("2026-06-02_2_stocks.png","C:\\Users\\31702\\Desktop\\Trading-System-Code\\outputs\\blockbeats\\2026-06-02_2_stocks.png"),
      ("2026-06-02_3_liq.png","C:\\Users\\31702\\Desktop\\Trading-System-Code\\outputs\\blockbeats\\2026-06-02_3_liq.png")]
img_blocks=[]
for name,path in imgs:
    uid=upload_image(path,name)
    img_blocks.append({"type":"image","image":{"type":"file_upload","file_upload":{"id":uid}}})
    print("uploaded",name,uid)
patch={"children":img_blocks}
if basemian: patch["after"]=basemian
r=requests.patch(f"https://api.notion.com/v1/blocks/{new_page}/children",headers=H,data=json.dumps(patch))
if r.status_code>=300: print("IMG INSERT FAIL",r.status_code,r.text); sys.exit(1)
print("MORNING IMAGES INSERTED OK")
print("DONE morning ->",new_page)
