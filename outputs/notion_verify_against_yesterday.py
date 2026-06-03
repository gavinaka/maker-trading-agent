# -*- coding: utf-8 -*-
"""
Notion 出稿稳定性自检器（机械化·不靠记忆）。
对比今日页 vs 【2026.6.2 固定金标模板】的「block 类型序列 / 每块字体颜色集合 / 图片数与位置」。
2026-06-03 用户拍板：以 6/2 为冻结模板长期对照（非"昨日"，避免错误逐日传播）。

用法：
  py notion_verify_against_yesterday.py <today_page_id> [morning|evening|review]   # 默认 morning，对照 6/2 金标
  py notion_verify_against_yesterday.py <today_page_id> <任意参照page_id>          # 显式指定参照页
PASS 才算出稿完成（见 memory/notion-publish-checklist.md）。
"""
import sys, os, requests

TOK = os.environ.get("NOTION_TOKEN", "")
assert TOK, "请先 $env:NOTION_TOKEN"
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28"}

# 2026.6.2 固定金标模板（用户认可·长期对照基准）
GOLD = {
    "morning": "373fda35-a098-81dc-a674-cc236149c457",  # 🌅 2026.6.2 早间
    "evening": "373fda35-a098-816d-bd9e-d7227943e9d2",  # 🌙 2026.6.2 晚间
    "review":  "373fda35-a098-81e3-b197-c8d84f7d3e01",  # 🔍 2026.6.2 独立审查
}

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
    today = sys.argv[1]
    ref = sys.argv[2] if len(sys.argv) > 2 else "morning"
    gold = GOLD.get(ref, ref)  # 关键词->6/2金标id；否则当作显式page_id
    label = f"6/2金标:{ref}" if ref in GOLD else "参照页"
    A, B = profile(today), profile(gold)
    print(f"今日块数={len(A)}  {label}块数={len(B)}")
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
        print(f"{i+1:2} 今[{a[0]:11}|{','.join(a[1]) or '-':20}] 标[{b[0]:11}|{','.join(b[1]) or '-':20}] {ta}{ca}{flag}")
    ia = sum(1 for r in A if r[0] == "image")
    ib = sum(1 for r in B if r[0] == "image")
    img_ok = ia == ib
    print(f"\n图片数：今={ia} 标={ib} {'OK' if img_ok else '<<< MISMATCH 基本面配图缺失/多余'}")
    if bad == 0 and img_ok and len(A) == len(B):
        print("\n[PASS] ALL CHECKS PASS — 块类型/颜色/图片/块数 全对齐")
    else:
        print(f"\n[FAIL] {bad} 块类型或颜色不一致" + ("" if img_ok else " + 图片数不符") + ("" if len(A)==len(B) else " + 块数不符") + " —— 必须修复后重跑")

if __name__ == "__main__":
    main()
