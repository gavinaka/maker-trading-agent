# -*- coding: utf-8 -*-
"""
报告反幻觉 lint（机械化·出稿前必跑）。扫描 combined.md 抓「模糊位/占位/未核数字」。
用法：py report_lint.py <combined_md_path>
[FAIL] 任一硬命中 → 必须改到 0 命中再 push（见 memory/precise-numbers-no-fuzzy.md / stability-contract.md）。

新增（2026-06-11）：仓位帐本一致性检查——抓「防守层减仓50% + TP1减仓50%」双扣类计划逻辑矛盾
（见 memory/defense-layer2-vs-tp1-conflict.md，6/2 金标第二层只设保本损无减仓）。
仅对含 Maker 挂单/持仓段的稿生效，观望日（无带百分比扣减动作）自动跳过。

新增（2026-06-16）：解耦门——抓系统稿里把用户实际持仓写成系统判断/管理对象的「联动」语言
（见 memory/system-plan-decoupled-from-user-positions.md）。系统的 Maker/中线/审查均独立输出、
与用户实仓完全解耦；出现「已执行100%/走防守层管理/管理(已)持仓/中线空保持/应止损离场/持仓中·走管」
等联动短语 = HARD FAIL。含解耦声明（解耦/不联动/与用户…无关/不纳入判断/事后对照）的行豁免。
"""
import sys, re

# ---------------- 解耦门（门②扩展·2026-06-16） ----------------
# 联动红旗：把用户实际持仓当系统持仓在「管理/镜像/复述决策」。系统稿禁现，命中即 HARD。
COUPLING = [
    (r"已执行\s*100\s*[%％]?",              "系统报『已成交100%』= 镜像用户实仓"),
    (r"走防守层管理|防守层逐层管理|防守层逐层", "『走防守层管理』= 管理用户持仓·联动"),
    (r"管理(?:已|其)?持仓|管理已成交",         "『管理持仓』= 联动用户实仓"),
    (r"中线空保持|中线多保持",                "复述用户中线持仓决策 = 联动"),
    (r"应(?:执行)?止损离场",                  "对用户中线仓下『止损离场』指令 = 联动"),
    (r"持仓中[·\s]*[走管防]",                "把用户『持仓中』写成系统管理对象 = 联动"),
]
# 含以下任一标记的行 = 显式解耦声明，豁免（如『与用户实际持仓完全解耦·不联动』）。
DECOUPLE_MARK = r"解耦|不联动|与用户.{0,8}无关|不纳入.{0,6}判断|事后对照|完全独立·与"

def coupling_check(lines):
    """返回 [(行号, 描述, 命中文本, 行摘要)]。命中=系统稿混入联动用户实仓的语言。"""
    hits = []
    for i, ln in enumerate(lines, 1):
        if re.search(DECOUPLE_MARK, ln):
            continue
        for pat, desc in COUPLING:
            m = re.search(pat, ln)
            if m:
                hits.append((i, desc, m.group(0), ln.strip()[:60]))
    return hits

# ---------------- 正文禁元叙事门（门②扩展·2026-06-19） ----------------
# 见 memory/fundamentals-brief-core-priority.md：日报正文（① 正文 + ② Maker 段）禁出现
# 内部规则/方法论/评分代号/门槛判定的元叙事，只用自然语言给结论与本质；代号/方法论/分数/门槛
# 全部只进 ③ 后附。本门只扫「## ①」～「## ③」之间（稿首 > 自查块在 ## ① 之前=豁免；③ 后附=豁免）。
# 命中即 HARD（替代"靠记忆主动套用"的失败路径——2026-06-19 晚报漂移事故根因=文档层迭代无机械闸）。
META_FORBIDDEN = [
    (r"价格锚点法",                              "方法论名（价格锚点法）→ 改自然语言/移③后附"),
    (r"背离合成引擎",                            "方法论名（背离合成引擎）→ 移③后附"),
    (r"投入产出比",                              "方法论名（投入产出比）→ 移③后附"),
    (r"极端候选",                                "盘口极端代号 → 移③后附"),
    (r"判定法|统一读取法",                        "方法论名 → 移③后附"),
    (r"[Cc]\d{2}(?![\d%／/])",                   "盘口组合代号 CXX → 移③后附"),
    (r"双门槛",                                  "门槛机制叙事 → 移③后附"),
    (r"门槛\s*[①②⑴⑵12]|门槛\s*[①②]?\s*[✔✗√×]", "门槛判定叙事（门槛①/②/✔/✗）→ 移③后附"),
    (r"[≥>]\s*65", "评分门槛阈值≥65 → 移③后附"),  # 注：金标 Maker 用「≥60%可达」描述可达性·合法→不禁 ≥60%/≥50%
    (r"软参考",                                  "执行概率软参考机制叙事 → 移③后附"),
    (r"rebound-short|judgment-synthesis|orderflow-|price-anchor|[A-Za-z]+-rule", "规则/记忆引用 → 移③后附"),
    (r"参\s*[A-Za-z]",                           "规则引用（参 xxx-rule）→ 移③后附"),
    (r"总评分\s*\d|总分\s*\d",                    "评分数值 → 移③后附"),
    (r"盘口\s*\d{2}|盘面\s*\d{2}",                "评分分项数值 → 移③后附"),
    (r"胜率自估",                                "胜率自估机制叙事 → 移③后附（值进后附）"),
]
# 金标豁免：Maker 段首行「执行概率X%（已执行X%）胜率X%」是 Notion 固定字段·照写不算元叙事。
_GOLD_MAKER_LINE = r"执行概率.*胜率|BTC（策略）"

def meta_narrative_check(lines):
    """扫 '## ①' ～ '## ③' 之间正文，抓元叙事。返回 [(行号, 描述, 命中, 摘要)]。"""
    start = end = None
    for i, ln in enumerate(lines, 1):
        if re.match(r"^##\s*①", ln):
            start = i
        elif re.match(r"^##\s*③", ln):
            end = i
            break
    if start is None:                 # 无 ① 正文标记 → 退化为全文（保守）
        start = 1
    if end is None:
        end = len(lines)
    hits = []
    for i in range(start, end):
        ln = lines[i - 1]
        if re.search(_GOLD_MAKER_LINE, ln):   # 金标固定字段行豁免
            continue
        for pat, desc in META_FORBIDDEN:
            m = re.search(pat, ln)
            if m:
                hits.append((i, desc, m.group(0), ln.strip()[:60]))
    return hits

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

# ---------------- 仓位帐本一致性（门②扩展） ----------------

_PRICE = r"([\d,]+(?:\.\d+)?)"

def _num(s):
    return float(s.replace(",", ""))

def _maker_section(lines):
    """取首个 '## ...Maker...' 段（到下一个二级标题为止）。返回 [(行号, 文本)] 或 None。"""
    start = None
    for i, ln in enumerate(lines, 1):
        if re.match(r"^##(?!#)", ln) and "Maker" in ln:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines) + 1):
        if re.match(r"^##(?!#)", lines[j - 1]):
            end = j - 1
            break
    return [(n, lines[n - 1]) for n in range(start, end + 1)]

def _split_outside_parens(line):
    """按 ／ / ；; 切分，但忽略括号内的分隔符（如 TP1 注释里的'上沿/日线低点'）。"""
    segs, buf, depth = [], [], 0
    for ch in line:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        if depth == 0 and ch in "／/；;":
            segs.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    segs.append("".join(buf))
    return segs

def _parse_cut(seg):
    """段内首个带百分比的减仓动作；'减半'按 50% 计。无则 None。"""
    m = re.search(r"(?:减仓|平仓)\s*(\d+(?:\.\d+)?)\s*[%％]", seg)
    if m:
        return float(m.group(1))
    if re.search(r"减半", seg):
        return 50.0
    return None

def _parse_actions(sec):
    """解析 Maker 段内全部仓位扣减动作（止盈 TP1/TP2 行 + 浮盈防守计划各层行）。
    action = {kind, price, cut(None=平余仓), lineno, text}"""
    actions = []
    for lineno, ln in sec:
        stripped = ln.strip()
        # 止盈行：按 ／ / ；; 分段，每段至多一个 TP；价格在 TP 前(价（TPn)或后(TPn 价)
        if re.match(r"^[*＊\s]*止盈[：:]", stripped):
            for seg in _split_outside_parens(ln):
                for tp in ("TP1", "TP2"):
                    if tp not in seg:
                        continue
                    m = (re.search(_PRICE + r"(?:\s*-\s*[\d,]+(?:\.\d+)?)?\s*[（(]\s*" + tp, seg)
                         or re.search(tp + r"[·\s：:]*" + _PRICE, seg))
                    if not m:
                        continue
                    actions.append(dict(kind=tp, price=_num(m.group(1)),
                                        cut=_parse_cut(seg),
                                        lineno=lineno, text=seg.strip()))
        # 浮盈防守层行（剔除【已触发…】注释避免双计）
        m = re.match(r"^[*＊\s]*第([一二三四五])层[：:]", stripped)
        if m:
            main_part = ln.split("【")[0]
            mp = re.search(r"(?:价格)?(?:首次)?触及\s*" + _PRICE, main_part)
            cut = _parse_cut(main_part)
            if mp and cut is not None:
                actions.append(dict(kind="防守第%s层" % m.group(1), price=_num(mp.group(1)),
                                    cut=cut, lineno=lineno, text=main_part.strip()))
    return actions

_SAME_ACTION = r"同一动作|同一笔|即\s*TP|[=＝]\s*TP"

def ledger_check(lines):
    """仓位帐本一致性。返回 (issues, skip_reason)；issue = (描述, [(行号, 文本), ...])。
    仓位自 100% 起按价格触发顺序逐级扣减（空单自高向低/多单自低向高，方向由 TP2 相对 TP1 推断）：
    (a) 扣减合计>100%  (b) TP2 触发时剩余仓位 0%（死条款）
    (c) 防守层与止盈层同价各扣一次且未注明同一动作
    (d) 金标口径（2026-06-11 锁死）：防守层禁带任何减仓/平仓百分比（只移损/保本损/取消加仓，
        扣减只发生在止盈档 TP1 减仓50%→TP2 清剩余）"""
    sec = _maker_section(lines)
    if sec is None:
        return [], "无 Maker 段"
    if re.search(r"观望", sec[0][1]) and re.search(r"不挂单", sec[0][1]):
        return [], "观望日（Maker 段表头标注观望·不挂单）"
    actions = _parse_actions(sec)
    cuts = [a for a in actions if a["cut"] is not None]
    if not cuts:
        return [], "Maker 段无带百分比的减仓/平仓动作（观望或无挂单）"
    issues = []
    refs = lambda acts: [(a["lineno"], a["text"]) for a in acts]
    # (d) 金标口径：防守层带任何减仓/平仓百分比即违规（不论帐是否闭合）
    layer_cuts = [a for a in cuts if a["kind"].startswith("防守")]
    if layer_cuts:
        issues.append(("(d) 防守层带仓位扣减·违 6/2 金标口径（防守层只移损/保本损/取消加仓·扣减只在止盈档）",
                       refs(layer_cuts)))
    # (a) 扣减合计超 100%
    total = sum(a["cut"] for a in cuts)
    if total > 100:
        issues.append(("(a) 减仓/平仓合计 %.0f%% 超过 100%%" % total, refs(cuts)))
    # (c) 防守层与止盈层同价各扣一次且未注明同一动作
    for d in [a for a in cuts if a["kind"].startswith("防守")]:
        for t in [a for a in cuts if a["kind"].startswith("TP")]:
            if d["price"] == t["price"] and not re.search(_SAME_ACTION, d["text"] + t["text"]):
                issues.append(("(c) %s 与 %s 同价 %s 各扣 %.0f%%+%.0f%%·未注明同一动作"
                               % (d["kind"], t["kind"], "{:,.0f}".format(d["price"]),
                                  d["cut"], t["cut"]), refs([d, t])))
    # (b) TP2 死条款：按触发顺序模拟扣减
    tp1 = next((a for a in actions if a["kind"] == "TP1"), None)
    tp2 = next((a for a in actions if a["kind"] == "TP2"), None)
    if tp2 is not None and tp1 is not None:
        descending = tp2["price"] < tp1["price"]  # 空单价格自高向低触发，多单反之
        ordered = sorted(actions, key=lambda a: (-a["price"] if descending else a["price"]))
        remaining, fired = 100.0, []
        for a in ordered:
            if a is tp2:
                if remaining <= 0:
                    issues.append(("(b) TP2 触发时剩余仓位 %.0f%%（死条款·前序已扣 %.0f%%）"
                                   % (max(remaining, 0), 100.0 - remaining), refs(fired + [tp2])))
                break
            if a["cut"]:
                remaining -= a["cut"]
                fired.append(a)
    return issues, None

def main():
    # GBK 控制台防崩：正文里的 emoji（如🔴）无法编码时替换为 ?，不让 lint 自身崩溃
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
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
    ledger_issues, ledger_skip = ledger_check(lines)
    coupling_hits = coupling_check(lines)
    meta_hits = meta_narrative_check(lines)
    for i, desc, hit, ctx in warn_hits:
        print(f"[WARN] L{i} {desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in hard_hits:
        print(f"[HARD] L{i} {desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in coupling_hits:
        print(f"[HARD] L{i} 解耦门·联动红旗 {desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in meta_hits:
        print(f"[HARD] L{i} 正文元叙事 {desc}: '{hit}'  | {ctx}")
    if not meta_hits:
        print("[OK] 正文禁元叙事门: 正文(①+②)无代号/方法论/分数/门槛元叙事")
    if ledger_skip:
        print(f"[SKIP] 仓位帐本一致性: {ledger_skip}")
    for desc, ref_lines in ledger_issues:
        print(f"[HARD] 仓位帐本矛盾 {desc}")
        for ln_no, txt in ref_lines:
            print(f"       L{ln_no} | {txt[:70]}")
    if not coupling_hits:
        print("[OK] 解耦门: 无联动用户实仓的语言")
    print()
    if hard_hits or ledger_issues or coupling_hits or meta_hits:
        msgs = []
        if hard_hits:
            msgs.append(f"{len(hard_hits)} 处模糊位/占位/臆造（用核过的确切数字替换）")
        if ledger_issues:
            msgs.append(f"{len(ledger_issues)} 处仓位帐本矛盾（对照 6/2 金标：第二层只设保本损无减仓）")
        if coupling_hits:
            msgs.append(f"{len(coupling_hits)} 处联动用户实仓（违解耦边界·system-plan-decoupled·改为系统独立判断）")
        if meta_hits:
            msgs.append(f"{len(meta_hits)} 处正文元叙事（代号/方法论/分数/门槛→改自然语言·移③后附·见 fundamentals-brief-core-priority）")
        print(f"[FAIL] " + "；".join(msgs) + " —— 修正后重跑")
        sys.exit(1)
    suffix = "" if ledger_skip else "·仓位帐本一致"
    print(f"[PASS] 无模糊位/占位/臆造{suffix}·无联动（{len(warn_hits)} 处 WARN 需人工确认是否核过）")

if __name__ == "__main__":
    main()
