# -*- coding: utf-8 -*-
"""
日报配色·确定性规则 + 语义配色审计器（门①b·根治"渲染不到位"）。

背景：原 verifier 只比"颜色集合"，且颜色绑死在冻结金标的当天情绪词上——当天结论词与金标不同，
机械对集合会把语义涂错（如"中性偏空"涂成红＝看着像利空）。2026-06-03 用户拍板：
配色按【情绪词→颜色】确定性映射（早晚统一一套），verifier 按本规则逐 run 校验语义配色。

唯一色规则（用户书面约定 · 长期标准 · 2026-06-12 迭代：中性偏多→绿、中性偏空→红，其余不变）：
  红 red    = 利空 / 空头趋势 / 中性偏空 / 压力 / 止损 / （追）做X（不能做拥挤侧）/ Maker 空头方向(反弹空/高空/做空)
  黄 yellow = 中性 / 震荡结构 / 基本面理由段 / 策略正文 / 解读标签(纯中性)
  绿 green  = 利多 / 利好 / 多头趋势 / 中性偏多 / 支撑 / 止盈 / 价格(已/未/部分)兑现 / Maker 多头方向(低多/反弹多)
  紫 purple = 注意事项 / 取消价

用法：
  py report_colors.py <page_id>     # 审计某 Notion 页逐 run 语义配色，[PASS]/[FAIL]
本模块也供 push 脚本 import：expected_color(text) 取某 run 的规范色。
"""
import sys, os, time, requests

TOK = os.environ.get("NOTION_TOKEN", "")
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28"}


def _get(url):
    """GET with retry — Notion 偶发 SSL UNEXPECTED_EOF，重试 3 次。"""
    for attempt in range(3):
        try:
            return requests.get(url, headers=H, timeout=30).json()
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise
            time.sleep(1.5)

# 情绪词 -> 规范色（精确匹配 run 文本，或作为前缀角色）
SENTIMENT = {
    "利空": "red", "利多": "green", "利好": "green",
    # 2026-06-12 用户迭代：中性偏多→绿、中性偏空→红（其余不变）
    "中性": "yellow", "中性偏空": "red", "中性偏多": "green", "中性偏多偏空": "yellow",
    "空头趋势": "red", "多头趋势": "green", "震荡结构": "yellow",
}
# 前缀角色 -> 规范色（run 以此开头即判定·整 run 含标签一起上色）
# 注意：日内支撑/日内压力 的"标签"run 在金标里是默认色、只有"数值"run 上色，
# 故不放进前缀（标签默认），改在 audit 里按"支撑/压力区间数值"上下文判定。
PREFIX_RED = ("止损", "反弹空", "高空", "做空", "低空")
PREFIX_GREEN = ("止盈", "低多", "反弹多", "高多")
PREFIX_PURPLE = ("注意事项", "⚠️ 取消价", "取消价")

import re
_RANGE = re.compile(r"^[\d,]{3,}\s*[-–]\s*[\d,]{3,}$")  # 价格区间数值 run，如 65,300-65,800


def expected_color(text):
    """返回某 run 文本应当的规范色；None=本规则不约束该 run（不校验）。"""
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith(PREFIX_PURPLE):
        return "purple"
    if t.startswith("（追）") or t.startswith("(追)"):
        return "red"
    # 价格兑现（短标签）
    if t.startswith("价格") and "兑现" in t and len(t) <= 12:
        return "green"
    # 精确情绪词
    if t in SENTIMENT:
        return SENTIMENT[t]
    # 前缀角色
    if t.startswith(PREFIX_GREEN):
        return "green"
    if t.startswith(PREFIX_RED):
        return "red"
    return None


def _children(page):
    out, cur = [], None
    while True:
        u = f"https://api.notion.com/v1/blocks/{page}/children?page_size=100"
        if cur:
            u += f"&start_cursor={cur}"
        d = _get(u)
        out += d["results"]
        if d.get("has_more"):
            cur = d["next_cursor"]
        else:
            break
    return out


def audit_page(page):
    """逐 run 校验语义配色。返回 (hard_violations, checked_count)。"""
    viol = []
    checked = 0
    for bi, b in enumerate(_children(page), 1):
        t = b["type"]
        node = b.get(t, {})
        if not isinstance(node, dict) or "rich_text" not in node:
            continue
        runs = node["rich_text"]
        region = None  # 日内支撑/压力 上下文：green / red
        for ri, r in enumerate(runs):
            txt = r.get("plain_text", "")
            actual = r.get("annotations", {}).get("color", "default")
            # 上下文：支撑/压力 区间数值 run 取上下文色（标签 run 本身保持默认、不校验）
            if "日内支撑" in txt:
                region = "green"
            if "日内压力" in txt:
                region = "red"
            exp = expected_color(txt)
            if exp is None and region and _RANGE.match(txt.strip()):
                exp = region
            if exp is None:
                continue
            checked += 1
            if actual != exp:
                viol.append((bi, ri, exp, actual, txt[:18]))
    return viol, checked


def fix_page(page):
    """按规范色就地 PATCH 修正所有错配 run。返回修正块数。"""
    import json
    blocks = _children(page)
    fixed = 0
    for b in blocks:
        t = b["type"]
        node = b.get(t, {})
        if not isinstance(node, dict) or "rich_text" not in node:
            continue
        runs = node["rich_text"]
        region = None
        changed = False
        for r in runs:
            txt = r.get("plain_text", "")
            if "日内支撑" in txt:
                region = "green"
            if "日内压力" in txt:
                region = "red"
            exp = expected_color(txt)
            if exp is None and region and _RANGE.match(txt.strip()):
                exp = region
            if exp is None:
                continue
            cur = r.get("annotations", {}).get("color", "default")
            if cur != exp:
                r.setdefault("annotations", {})["color"] = exp
                changed = True
        if changed:
            # 重建 rich_text（只保留 API 可写字段）
            new_rt = []
            for r in runs:
                a = r.get("annotations", {})
                new_rt.append({
                    "type": "text",
                    "text": {"content": r.get("plain_text", "")},
                    "annotations": {
                        "bold": a.get("bold", False), "italic": a.get("italic", False),
                        "strikethrough": a.get("strikethrough", False),
                        "underline": a.get("underline", False), "code": a.get("code", False),
                        "color": a.get("color", "default"),
                    },
                })
            requests.patch(f"https://api.notion.com/v1/blocks/{b['id']}",
                           headers={**H, "Content-Type": "application/json"},
                           data=json.dumps({t: {"rich_text": new_rt}})).raise_for_status()
            fixed += 1
    return fixed


def main():
    assert TOK, "请先 $env:NOTION_TOKEN"
    page = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == "--fix":
        n = fix_page(page)
        print(f"已按规范色修正 {n} 个块")
    viol, checked = audit_page(page)
    print(f"语义配色审计：校验 {checked} 个情绪/角色 run")
    if not viol:
        print("[PASS] 全部情绪词/角色 run 配色符合唯一色规则")
        return
    for bi, ri, exp, act, txt in viol:
        print(f"  [FAIL] blk{bi} run{ri}: 应={exp} 实={act}  「{txt}」")
    print(f"\n[FAIL] {len(viol)} 处语义配色错配 —— 必须改到规范色再交付")
    sys.exit(1)


if __name__ == "__main__":
    main()
