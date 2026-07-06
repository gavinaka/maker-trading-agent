# -*- coding: utf-8 -*-
"""
Notion 出稿稳定性自检器（机械化·不靠记忆）。
对比今日页 vs 【2026.6.2 固定金标模板】的「block 类型序列 / 每块字体颜色集合 / 图片数与位置」。
2026-06-03 用户拍板：以 6/2 为冻结模板长期对照（非"昨日"，避免错误逐日传播）。

用法：
  py notion_verify_against_yesterday.py <today_page_id> [morning|midday|evening|review]   # 默认 morning，对照 6/2 金标(midday 复用早间金标)
  py notion_verify_against_yesterday.py <today_page_id> <任意参照page_id>          # 显式指定参照页
PASS 才算出稿完成（见 memory/notion-publish-checklist.md）。
"""
import sys, os, re, time, requests

TOK = os.environ.get("NOTION_TOKEN", "")
assert TOK, "请先 $env:NOTION_TOKEN"
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28"}


def _get(url):
    """GET with retry — Notion 偶发 SSL UNEXPECTED_EOF，重试 3 次（对齐 report_colors）。"""
    for attempt in range(3):
        try:
            response = requests.get(url, headers=H, timeout=30)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise
            time.sleep(1.5)


def title_of(pid):
    p = _get(f"https://api.notion.com/v1/pages/{pid}").json()
    for v in p.get("properties", {}).values():
        if v.get("type") == "title":
            return "".join(x.get("plain_text", "") for x in v["title"])
    return ""


def _norm_title(s):
    # 抹掉日期 token（2026.6.3 / 2026.06.03）后比标题格式
    return re.sub(r"\d{4}\.\d{1,2}\.\d{1,2}", "<DATE>", s).strip()


def _disp(s):
    # 显示安全：剔除 emoji 等 GBK 不可编码字符（PS 控制台 GBK 会崩）
    return s.encode("gbk", "ignore").decode("gbk")

# 2026.6.2 固定金标模板（用户认可·长期对照基准）
GOLD = {
    "morning": "373fda35-a098-81dc-a674-cc236149c457",  # 🌅 2026.6.2 早间
    "midday":  "373fda35-a098-81dc-a674-cc236149c457",  # 🌇 午间(2026-06-20 新增节点·全骨架同早间→复用早间28块金标)
    "evening": "373fda35-a098-816d-bd9e-d7227943e9d2",  # 🌙 2026.6.2 晚间
    "review":  "373fda35-a098-81e3-b197-c8d84f7d3e01",  # 🔍 2026.6.2 独立审查
}
TEXT_TYPES = {
    "quote",
    "heading_1",
    "heading_2",
    "heading_3",
    "paragraph",
    "callout",
    "bulleted_list_item",
    "numbered_list_item",
}
FINAL_TEXT_PREFIXES = ("独立边界", "持仓校准")

def children(pid):
    out, cur = [], None
    while True:
        u = f"https://api.notion.com/v1/blocks/{pid}/children?page_size=100"
        if cur: u += f"&start_cursor={cur}"
        d = _get(u).json()
        out += d["results"]
        if d.get("has_more"): cur = d["next_cursor"]
        else: break
    return out


def _with_table_children(blocks):
    enriched = []
    for block in blocks:
        if block.get("type") != "table" or not block.get("id"):
            enriched.append(block)
            continue
        copy = dict(block)
        table = dict(copy.get("table") or {})
        table["children"] = children(block["id"])
        copy["table"] = table
        enriched.append(copy)
    return enriched


def _plain_block(block):
    t = block.get("type")
    body = block.get(t)
    if not isinstance(body, dict):
        return ""
    parts = []
    for item in body.get("rich_text", []):
        if item.get("plain_text") is not None:
            parts.append(str(item.get("plain_text", "")))
        else:
            text = item.get("text")
            if isinstance(text, dict):
                parts.append(str(text.get("content", "")))
    return "".join(parts).strip()


def daily_semantic_scan(pid):
    """Check semantic slots that type/color gates cannot prove."""
    blocks = children(pid)
    issues = []
    text_blocks = []
    for index, block in enumerate(blocks, 1):
        block_type = block.get("type")
        if block_type not in TEXT_TYPES:
            continue
        text = _plain_block(block)
        text_blocks.append((index, block_type, text))
        if not text:
            issues.append((index, "empty_text_block", text))
        if "??" in text:
            issues.append((index, "encoding_corruption", text))
    if len(blocks) >= 2:
        cannot_do = _plain_block(blocks[1])
        if not cannot_do.startswith("不能做：") or cannot_do == "不能做：":
            issues.append((2, "cannot_do_incomplete", cannot_do))
    if text_blocks:
        last_index, _, last_text = text_blocks[-1]
        if not last_text.startswith(FINAL_TEXT_PREFIXES):
            issues.append((last_index, "final_boundary_drift", last_text))
    return issues

def meta_narrative_scan(pid):
    """元叙事门（2026-06-19·根因修复）：扫【实际已发布 Notion 页】全部块的完整 plain_text，
    抓代号/方法论/分数/门槛判定元叙事。Notion 正文不含 ③后附 → 正文块都应无元叙事；
    豁免＝① quote 块（评分点/门禁/总评分自查摘要头·同 lint 的稿首 > 块·6/2 金标即此口径）
         ② Maker 金标首行「执行概率X%…胜率X%」。命中即 FAIL（morning/midday/evening 调用）。
    复用 report_lint.META_FORBIDDEN 作单一权威清单，防两处规则漂移。"""
    from report_lint import META_FORBIDDEN, _GOLD_MAKER_LINE
    hits = []
    for bi, b in enumerate(children(pid), 1):
        t = b["type"]
        if t == "quote":          # 评分点/门禁/总评分 自查摘要头·豁免（同 lint 稿首 > 块）
            continue
        if not (isinstance(b.get(t), dict) and b[t].get("rich_text")):
            continue
        txt = "".join(x.get("plain_text", "") for x in b[t]["rich_text"])
        if re.search(_GOLD_MAKER_LINE, txt):   # Maker 金标固定字段行豁免
            continue
        for pat, desc in META_FORBIDDEN:
            m = re.search(pat, txt)
            if m:
                hits.append((bi, desc, m.group(0), txt[:48]))
    return hits


def review_semantic_scan(pid, title):
    """Review-specific semantic contract gate for the actual published page."""
    try:
        from review_contract import validate_review_blocks, validate_review_payload_colors

        blocks = _with_table_children(children(pid))
        validate_review_blocks(blocks, title=title)
        validate_review_payload_colors({"verifier_mode": "review", "children": blocks})
        return []
    except Exception as exc:
        return [str(exc)]


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
    if len(sys.argv) < 2:
        print(
            "用法: py notion_verify_against_yesterday.py "
            "<today_page_id> [morning|midday|evening|review|reference_page_id]"
        )
        return 2

    today = sys.argv[1]
    ref = sys.argv[2] if len(sys.argv) > 2 else "morning"
    gold = GOLD.get(ref, ref)  # 关键词->6/2金标id；否则当作显式page_id
    label = f"6/2金标:{ref}" if ref in GOLD else "参照页"
    # ⓪ 标题门：子页标题格式须对齐金标（抹日期后逐字比，防"漏（20:00 评分点）"类漂移）
    #   midday 复用早间 28 块金标做【结构】对照，但标题是午间专属格式（🌇/午间日报/15:30 评分点），
    #   不与早间金标标题逐字比（否则 🌇午间 vs 🌅早间 永远 MISMATCH）；改校验午间专属格式。
    ta = title_of(today)
    if ref == "midday":
        nt = _norm_title(ta)
        title_ok = ("🌇" in nt and "午间日报（15:30 评分点）" in nt and "<DATE>" in nt)
        print(f"标题门：今「{_disp(ta)}」 期望「[午间] <DATE> 午间日报（15:30 评分点）」 {'OK' if title_ok else '<<< MISMATCH 标题格式不对齐午间格式'}")
    else:
        tb = title_of(gold)
        title_ok = _norm_title(ta) == _norm_title(tb)
        print(f"标题门：今「{_disp(ta)}」 标「{_disp(tb)}」 {'OK' if title_ok else '<<< MISMATCH 标题格式不对齐金标'}")

    A, B = profile(today), profile(gold)
    print(f"今日块数={len(A)}  {label}块数={len(B)}")
    # ① 结构门：块类型序列对照金标（颜色不再硬比金标——金标自身配色不一致，
    #    配色权威改由 report_colors 按【情绪词→颜色唯一规则】逐 run 校验，见门①b）
    n = max(len(A), len(B)); bad = 0
    for i in range(n):
        a = A[i] if i < len(A) else ("<缺>", [], "")
        b = B[i] if i < len(B) else ("<缺>", [], "")
        type_ok = a[0] == b[0]
        col_note = "" if set(a[1]) == set(b[1]) else "  (色差·交规则门校验)"
        flag = "  <<< MISMATCH" if not type_ok else ""
        if not type_ok: bad += 1
        print(f"{i+1:2} 今[{a[0]:11}|{','.join(a[1]) or '-':20}] 标[{b[0]:11}|{','.join(b[1]) or '-':20}] {'type!=' if not type_ok else ''}{flag}{col_note}")
    ia = sum(1 for r in A if r[0] == "image")
    ib = sum(1 for r in B if r[0] == "image")
    img_ok = ia == ib
    print(f"\n图片数：今={ia} 标={ib} {'OK' if img_ok else '<<< MISMATCH 基本面配图缺失/多余'}")
    struct_ok = (bad == 0 and img_ok and len(A) == len(B))

    semantic_ok = True
    if ref in ("morning", "midday", "evening"):
        semantic_issues = daily_semantic_scan(today)
        print("\n语义槽位门：检查 不能做/空文本/尾部边界/编码污染", end="")
        if semantic_issues:
            semantic_ok = False
            print("  <<< 槽位漂移")
            for bi, reason, txt in semantic_issues[:8]:
                print(f"   blk{bi}: {reason} 「{_disp(txt[:120])}」")
            if len(semantic_issues) > 8:
                print(f"   ... 另 {len(semantic_issues) - 8} 处")
        else:
            print("  OK")
    elif ref == "review":
        review_issues = review_semantic_scan(today, ta)
        print("\nReview contract gate: independent dimensions / three segments / no system terms", end="")
        if review_issues:
            semantic_ok = False
            print("  <<< REVIEW CONTRACT DRIFT")
            for issue in review_issues[:8]:
                print(f"   {_disp(issue[:180])}")
            if len(review_issues) > 8:
                print(f"   ... plus {len(review_issues) - 8} more")
        else:
            print("  OK")

    # ① b 配色门：morning/midday/evening 按情绪词唯一规则逐 run 校验语义配色（review 用分析配色·跳过）
    color_ok = True
    if ref in ("morning", "midday", "evening"):
        try:
            from report_colors import audit_page
            viol, checked = audit_page(today)
            print(f"\n语义配色门：校验 {checked} 个情绪/角色 run", end="")
            if viol:
                color_ok = False
                print("  <<< 配色错配")
                for bi, ri, exp, act, txt in viol:
                    print(f"   blk{bi} run{ri}: 应={exp} 实={act}  「{txt}」")
            else:
                print("  OK")
        except Exception as e:
            color_ok = False
            print(f"\n语义配色门：执行失败 {e}")

        try:
            from daily_color_template import audit_daily_blocks
            template_viol, template_summary = audit_daily_blocks(children(today))
            checked = template_summary.get("checked_blocks", 0)
            print(f"\n金标run级配色门：校验 {checked} 个模板块", end="")
            if template_viol:
                color_ok = False
                print("  <<< run级配色分布漂移")
                for item in template_viol[:8]:
                    print(
                        f"   blk{item.get('block')}: {_disp(str(item.get('text_prefix', '')))} "
                        f"期望={_disp(str(item.get('expected', ''))[:160])} "
                        f"实际={_disp(str(item.get('actual', ''))[:160])}"
                    )
                if len(template_viol) > 8:
                    print(f"   ... 另 {len(template_viol) - 8} 处")
            else:
                print("  OK")
        except Exception as e:
            color_ok = False
            print(f"\n金标run级配色门：执行失败 {e}")

    # ① c 元叙事门：morning/midday/evening 扫实际已发布页全文·禁代号/方法论/分数/门槛（review 用分析配色·豁免）
    meta_ok = True
    if ref in ("morning", "midday", "evening"):
        try:
            mh = meta_narrative_scan(today)
            print(f"\n元叙事门：扫已发布页正文（禁代号/方法论/分数/门槛）", end="")
            if mh:
                meta_ok = False
                print("  <<< 命中元叙事（应改自然语言·细节移 ③后附）")
                for bi, desc, hit, txt in mh:
                    print(f"   blk{bi}: '{_disp(hit)}' [{_disp(desc)}]  「{_disp(txt)}」")
            else:
                print("  OK")
        except Exception as e:
            meta_ok = False
            print(f"\n元叙事门：执行失败 {e}")

    if title_ok and struct_ok and semantic_ok and color_ok and meta_ok:
        print("\n[PASS] ALL CHECKS PASS — 标题 + 块类型/块数/图片 + 语义槽位 对齐金标 + 配色符合唯一规则 + 正文无元叙事")
        return 0
    else:
        msg = []
        if not title_ok: msg.append("标题格式不对齐金标")
        if not struct_ok: msg.append(f"{bad} 块类型不一致" + ("" if img_ok else "+图片数不符") + ("" if len(A)==len(B) else "+块数不符"))
        if not semantic_ok:
            if ref == "review":
                msg.append("review contract drift (dimensions/segments/system terms)")
            else:
                msg.append("语义槽位漂移（不能做/空文本/尾部边界/编码）")
        if not color_ok: msg.append("语义配色错配")
        if not meta_ok: msg.append("正文含元叙事（代号/方法论/分数/门槛→改自然语言·移③后附）")
        print(f"\n[FAIL] " + " / ".join(msg) + " —— 必须修复后重跑")
        return 1

if __name__ == "__main__":
    sys.exit(main())
