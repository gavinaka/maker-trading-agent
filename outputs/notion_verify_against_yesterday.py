# -*- coding: utf-8 -*-
"""
Notion 出稿稳定性自检器（机械化·不靠记忆）。
用法：py notion_verify_against_yesterday.py <today_page_id> <yesterday_page_id>
对比两页的「block 类型序列 / 每块所用字体颜色集合 / 图片数量与位置」，
任一不一致即打印 [MISMATCH]，全绿打印 ALL CHECKS PASS。
出稿 push 后必须跑此脚本，PASS 才算完成（见 memory/notion-publish-checklist.md）。
"""
import sys, os, requests

TOK = os.environ.get("NOTION_TOKEN", "")
assert TOK, "请先 $env:NOTION_TOKEN"
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28"}

def children(pid):
    out, cur = [], None
    while True:
        u = f"https://api.notion.com/v1/blocks/{pid}/children?page_size=100"
        if cur: u += f"&start_cursor={cur}"
        d = requests.get(u, headers=H).json()
        out += d["results"]
        if d.get("has_more"): cur = d["next_cursor"]
        else: break
    return out

def profile(pid):
    """每块 -> (type, 颜色集合, 是否有内容前缀)。"""
    rows = []
    for b in children(pid):
        t = b["type"]
        colors = []
        if t in b and isinstance(b[t], dict) and "rich_text" in b[t]:
            for rt in b[t]["rich_text"]:
                c = rt.get("annotations", {}).get("color", "default")
                if c != "default":
                    colors.append(c)
        txt = ""
        if t in b and isinstance(b[t], dict) and b[t].get("rich_text"):
            txt = "".join(x.get("plain_text", "") for x in b[t]["rich_text"])[:14]
        rows.append((t, colors, txt))
    return rows

def main():
    today, yest = sys.argv[1], sys.argv[2]
    A, B = profile(today), profile(yest)
    print(f"今日块数={len(A)}  昨日块数={len(B)}")
    n = max(len(A), len(B)); bad = 0
    for i in range(n):
        a = A[i] if i < len(A) else ("<缺>", [], "")
        b = B[i] if i < len(B) else ("<缺>", [], "")
        type_ok = a[0] == b[0]
        # 颜色集合（忽略重复次数差异，比对所用颜色种类是否一致）
        col_ok = set(a[1]) == set(b[1])
        flag = "" if (type_ok and col_ok) else "  <<< MISMATCH"
        if flag: bad += 1
        ta = "type!=" if not type_ok else ""
        ca = "color!=" if not col_ok else ""
        print(f"{i+1:2} 今[{a[0]:11}|{','.join(a[1]) or '-':20}] 昨[{b[0]:11}|{','.join(b[1]) or '-':20}] {ta}{ca}{flag}")
    ia = sum(1 for r in A if r[0] == "image")
    ib = sum(1 for r in B if r[0] == "image")
    img_ok = ia == ib
    print(f"\n图片数：今={ia} 昨={ib} {'OK' if img_ok else '<<< MISMATCH 基本面配图缺失/多余'}")
    if bad == 0 and img_ok and len(A) == len(B):
        print("\n[PASS] ALL CHECKS PASS — 块类型/颜色/图片/块数 全对齐")
    else:
        print(f"\n[FAIL] {bad} 块类型或颜色不一致" + ("" if img_ok else " + 图片数不符") + ("" if len(A)==len(B) else " + 块数不符") + " —— 必须修复后重跑")

if __name__ == "__main__":
    main()
