# -*- coding: utf-8 -*-
"""
报告反幻觉 lint（机械化·出稿前必跑）。扫描 combined.md 抓「模糊位/占位/未核数字」。
用法：py report_lint.py <combined_md_path>
[FAIL] 任一硬命中 → 必须改到 0 命中再 push（见 memory/precise-numbers-no-fuzzy.md / stability-contract.md）。
"""
import sys, re

# 注：负向后顾 (?<![\d.]) 排除「数字~数字」区间写法(如 0.7~1.3%)，只抓独立的 ~约X 模糊位
HARD = [
    (r"\d[xX]{2,}",                  "模糊价位 (如 71,2xx / 712XX)"),
    (r"[xX]{4,}",                    "占位符 XXXX"),
    (r"(?<![\d.])~\s*\d[\d,\.]*\s*%", "臆造约数百分比 (独立 ~3%，非区间)"),
    (r"[一二三四五六七八九十]?[xX]{2}刀", "持仓量占位 (xx刀)"),
    (r"占位|待补|TODO|TBD",            "未填占位标记"),
]
WARN = [
    (r"约\s*\d",            "出现'约X'——确认是核过的数还是估值"),
    (r"(?<![\d.])~\s*\d",   "出现独立'~X'——确认非臆造模糊位(区间0.7~1.3已排除)"),
]

def main():
    path = sys.argv[1]
    txt = open(path, encoding="utf-8").read()
    lines = txt.splitlines()
    hard_hits, warn_hits = [], []
    for i, ln in enumerate(lines, 1):
        for pat, desc in HARD:
            for m in re.finditer(pat, ln):
                hard_hits.append((i, desc, m.group(0), ln.strip()[:60]))
        for pat, desc in WARN:
            for m in re.finditer(pat, ln):
                warn_hits.append((i, desc, m.group(0), ln.strip()[:60]))
    for i, desc, hit, ctx in warn_hits:
        print(f"[WARN] L{i} {desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in hard_hits:
        print(f"[HARD] L{i} {desc}: '{hit}'  | {ctx}")
    print()
    if hard_hits:
        print(f"[FAIL] {len(hard_hits)} 处模糊位/占位/臆造 —— 必须用核过的确切数字替换后重跑")
        sys.exit(1)
    print(f"[PASS] 无模糊位/占位/臆造（{len(warn_hits)} 处 WARN 需人工确认是否核过）")

if __name__ == "__main__":
    main()
