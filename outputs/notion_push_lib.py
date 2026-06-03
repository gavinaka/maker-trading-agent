# -*- coding: utf-8 -*-
"""
notion_push_lib —— 「AI agent（plan）」日报归档的可复用推送库（机制层·不含任何报告内容）。
用法：`py` 运行（python3 是 Windows stub 勿用）；token 走环境变量 `$env:NOTION_TOKEN`（绝不硬编码进库）。
每天的推送脚本 import 本库后只需「定义 blocks 内容 + 调 create_page/ensure_date_page」，
plumbing（multipart 上传 / 去重 / after 插图 / 旧块迁移 / 分页>100）全在这里，不再每天重推导。

⚠️ 写 Python 字符串内的中文引号一律用全角「」，禁用半角 " （会与字符串定界符冲突→SyntaxError）。
"""
import os, json, requests

NV = "2022-06-28"
AI_AGENT_PLAN = "373fda35-a098-80be-ae2f-ddfb06b3b075"  # 唯一可写项目，其它只读
TEXT_TYPES = {"paragraph","heading_1","heading_2","heading_3","quote",
              "bulleted_list_item","numbered_list_item","callout","toggle"}

def _tok():
    t = os.environ.get("NOTION_TOKEN", "")
    assert t, "请先设置环境变量 NOTION_TOKEN"
    return t

def _h(json_ct=True):
    h = {"Authorization": f"Bearer {_tok()}", "Notion-Version": NV}
    if json_ct: h["Content-Type"] = "application/json"
    return h

# ---------- rich_text / block 构造器 ----------
def rt(content, color=None, bold=False, link=None):
    it = {"type": "text", "text": {"content": content}}
    if link: it["text"]["link"] = {"url": link}
    a = {}
    if bold: a["bold"] = True
    if color: a["color"] = color
    if a: it["annotations"] = a
    return it

def _runs(x):
    return [rt(x)] if isinstance(x, str) else x

def para(runs, color="default"): return {"type":"paragraph","paragraph":{"rich_text":_runs(runs),"color":color}}
def h2(runs): return {"type":"heading_2","heading_2":{"rich_text":_runs(runs)}}
def h3(runs): return {"type":"heading_3","heading_3":{"rich_text":_runs(runs)}}
def quote(runs): return {"type":"quote","quote":{"rich_text":_runs(runs)}}
def callout(runs, emoji="⚠️", color="orange_background"):
    return {"type":"callout","callout":{"rich_text":_runs(runs),"icon":{"emoji":emoji},"color":color}}
def divider(): return {"type":"divider","divider":{}}
def cell(content, color=None, bold=False): return [rt(content, color, bold)]
def trow(cells): return {"type":"table_row","table_row":{"cells":cells}}
def table(width, rows, header=True):
    return {"type":"table","table":{"table_width":width,"has_column_header":header,
            "has_row_header":False,"children":rows}}
def image_block(file_upload_id):
    return {"type":"image","image":{"type":"file_upload","file_upload":{"id":file_upload_id}}}

# ---------- API ----------
def get_children(bid):
    out, cur = [], None
    while True:
        u = f"https://api.notion.com/v1/blocks/{bid}/children?page_size=100"
        if cur: u += f"&start_cursor={cur}"
        r = requests.get(u, headers=_h()); r.raise_for_status(); d = r.json()
        out += d["results"]
        if d.get("has_more"): cur = d["next_cursor"]
        else: break
    return out

def find_child_page(parent, title_prefix):
    for b in get_children(parent):
        if b["type"] == "child_page" and b["child_page"]["title"].startswith(title_prefix):
            return b["id"]
    return None

def find_heading(blocks, text_prefix):
    for b in blocks:
        tp = b["type"]
        if tp.startswith("heading_"):
            txt = "".join(x.get("plain_text","") for x in b[tp]["rich_text"])
            if txt.startswith(text_prefix): return b["id"]
    return None

def create_page(parent, title, children):
    payload = {"parent":{"type":"page_id","page_id":parent},
               "properties":{"title":{"title":[{"type":"text","text":{"content":title}}]}},
               "children":children[:100]}
    r = requests.post("https://api.notion.com/v1/pages", headers=_h(), data=json.dumps(payload))
    r.raise_for_status(); pid = r.json()["id"]
    rest = children[100:]
    while rest:
        chunk, rest = rest[:100], rest[100:]
        r = requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children",
                           headers=_h(), data=json.dumps({"children":chunk})); r.raise_for_status()
    return pid

def ensure_date_page(date_str):
    """date_str 形如 '2026.6.2'，返回 AI agent plan 下日期子页 id，缺则建空页。"""
    pid = find_child_page(AI_AGENT_PLAN, date_str)
    return pid if pid else create_page(AI_AGENT_PLAN, date_str, [])

def upload_image(path, name=None):
    name = name or os.path.basename(path)
    r = requests.post("https://api.notion.com/v1/file_uploads", headers=_h(), data=json.dumps({})); r.raise_for_status()
    fu = r.json()
    with open(path, "rb") as f:
        r2 = requests.post(fu["upload_url"], headers=_h(json_ct=False),
                           files={"file":(name, f, "image/png")}); r2.raise_for_status()
    return fu["id"]

def insert_after(page, after_id, blocks):
    patch = {"children":blocks}
    if after_id: patch["after"] = after_id
    r = requests.patch(f"https://api.notion.com/v1/blocks/{page}/children",
                       headers=_h(), data=json.dumps(patch)); r.raise_for_status()

def insert_images_after_heading(page, heading_prefix, image_paths):
    hid = find_heading(get_children(page), heading_prefix)
    insert_after(page, hid, [image_block(upload_image(p)) for p in image_paths])

def copy_block(b):
    """GET 到的块 → 可 POST 的 child（剥只读字段；image 返回 None，需本地重传）。"""
    t = b["type"]
    if t == "divider": return divider()
    if t not in TEXT_TYPES: return None
    src = b[t]
    runs = []
    for x in src.get("rich_text", []):
        if x["type"] != "text": continue
        link = x["text"].get("link")
        a = x.get("annotations") or {}
        runs.append(rt(x["text"]["content"],
                       color=a.get("color") if a.get("color") not in (None,"default") else None,
                       bold=a.get("bold", False),
                       link=link["url"] if link else None))
    payload = {"rich_text": runs}
    if "color" in src: payload["color"] = src["color"]
    if t == "callout" and src.get("icon"): payload["icon"] = src["icon"]
    return {"type": t, t: payload}

def push_subpage(date_str, title, children, img_after_heading=None, img_paths=None, dedup_prefix=None):
    """一站式：定位/建日期页 → 防重复 → 建子页(写 children) → 可选在某标题后插图。返回子页 id 或 None(已存在)。"""
    date_page = ensure_date_page(date_str)
    if dedup_prefix and find_child_page(date_page, dedup_prefix):
        print(f"ABORT 已存在同名子页: {dedup_prefix}"); return None
    pid = create_page(date_page, title, children)
    if img_after_heading and img_paths:
        insert_images_after_heading(pid, img_after_heading, img_paths)
    return pid
