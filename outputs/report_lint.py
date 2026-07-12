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
from datetime import date
from pathlib import Path

try:
    from .report_structure_gate import validate_combined_structure
except ImportError:  # pragma: no cover - script execution path
    from report_structure_gate import validate_combined_structure

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
# 2026-07-04 加固：Notion 实际持仓只能在分析锁后做操作校准，不能出现在独立报告判断中，
# 更不能改变 Maker 是否挂单/方向/入场/止盈止损/防守计划。以下命中不允许用“解耦声明”豁免。
POSITION_COUPLING = [
    (r"持仓校准", "分析锁前/正文出现持仓校准"),
    (r"(?:主账户|Maker账户|双账户).{0,18}(?:无持仓|空仓|已平仓|未开仓|已成交|持仓)", "账户实际持仓事实混入独立报告"),
    (r"(?:已有|当前|实际).{0,18}(?:持仓|空单|多单).{0,24}(?:阻断|禁止|不挂|新增|补仓|风控门|观望)", "用实际持仓改变 Maker 决策"),
    (r"方向相反.{0,12}持仓", "用实际持仓方向否决系统独立计划"),
    (r"风控门阻断新增", "用持仓风控门阻断新增 Maker 计划"),
    (r"先补齐风控", "用 Notion 持仓字段缺失改变报告决策"),
]
# 含以下任一标记的行 = 显式解耦声明，豁免（如『与用户实际持仓完全解耦·不联动』）。
# 注意：只豁免旧 COUPLING 项；POSITION_COUPLING 永不豁免。
DECOUPLE_MARK = r"解耦|不联动|与用户.{0,8}无关|不纳入.{0,6}判断|事后对照|完全独立·与"

def coupling_check(lines):
    """返回 [(行号, 描述, 命中文本, 行摘要)]。命中=系统稿混入联动用户实仓的语言。"""
    hits = []
    for i, ln in enumerate(lines, 1):
        for pat, desc in POSITION_COUPLING:
            m = re.search(pat, ln)
            if m:
                hits.append((i, desc, m.group(0), ln.strip()[:60]))
        if re.search(DECOUPLE_MARK, ln):
            continue
        for pat, desc in COUPLING:
            m = re.search(pat, ln)
            if m:
                hits.append((i, desc, m.group(0), ln.strip()[:60]))
    return hits


TOOL_WRAPPER_METADATA = re.compile(
    r"^\s*(?:Exit code:|Wall time:|Process exited with code|Final output:|"
    r"Output:|Script running with cell ID|Warning: truncated output)"
)


def tool_wrapper_leak_check(lines):
    """Reject host/tool wrapper text before it can enter Word or Notion."""
    hits = []
    for i, line in enumerate(lines, 1):
        match = TOOL_WRAPPER_METADATA.search(line)
        if match:
            hits.append(
                (
                    i,
                    "工具包装元数据泄漏",
                    match.group(0).strip(),
                    line.strip()[:60],
                )
            )
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

# ---------------- 胜率反下偏门（门②扩展·2026-06-20） ----------------
# 见 memory/winrate-anchoring-bias.md：胜率自估有系统性「贴 60 门槛下方」下偏（57-59 聚集·偏离
# 自己 rubric 15+ 点）。机械闸：凡胜率落临界带 [55,59]，③后附必须含「rubric 推导链」（锚=X→次因→
# 落值），否则视为疑似贴门槛下偏 = HARD FAIL，强制补 rubric 推导或纠回真实值。
# 设计：①只卡 [55,59]——开单日(≥60)与极低胜率均不触发，不影响 placing 稿/正常观望；
#      ②有推导链即豁免——真·<60 的观望日(如中部无可达边缘)照常过，只要写清 rubric 锚与下调理由。
_WINRATE_VAL = re.compile(r"胜率(?:自估)?\s*(?:约)?\s*(\d{2})\s*[%％]")
# rubric 推导链签名：出现 rubric/方法论引用，或「锚 ~|=|～ 两位数」(如 锚~80 / 锚=75 / 锚点80)。
_RUBRIC_CHAIN = re.compile(r"rubric|winrate_methodology|胜率方法论|锚[点]?\s*[~～=]\s*\d{2}")

def _scoring_detail_region(lines):
    """取 ③后附「评分明细」区(本份报告自己的胜率估值+推导所在)，到下一 ### / ## 边界为止。
    🟥 只看这一区＝排除「三段/双段倒推审查」里引用的【往期】报告胜率(段一/段二/段三 58/57…)，
    避免把历史引用误当本份估值(否则 placing 稿引用往期 58% 会被误判)。返回文本或 None。"""
    start = None
    for i, ln in enumerate(lines):
        if re.search(r"评分明细", ln) or re.match(r"^###\s*A[\.．、]", ln):
            start = i
            break
    if start is None:                      # 无评分明细标题 → 退化为 '## ③' 到下一个 '### '
        for i, ln in enumerate(lines):
            if re.match(r"^##\s*③", ln):
                start = i
                break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^###\s", lines[j]) or re.match(r"^##(?!#)", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])

def winrate_anchor_check(lines):
    """胜率反下偏。返回 (band_vals, has_chain, scoped)。band_vals=本份估值落[55,59]的列表(去重)。
    只扫 ③后附「评分明细」区(本份自己的估值)·不扫倒推审查的往期引用。band_vals 非空且无 rubric
    推导链 → 调用方判 HARD。scoped=False 表示无评分明细区(如纯模板)·不触发。"""
    region = _scoring_detail_region(lines)
    if region is None:
        return [], False, False
    vals = [int(m.group(1)) for m in _WINRATE_VAL.finditer(region)
            if 55 <= int(m.group(1)) <= 59]
    band_vals = sorted(set(vals))
    has_chain = bool(_RUBRIC_CHAIN.search(region))
    return band_vals, has_chain, True

# ---------------- 流动性读位门（门②扩展·2026-06-21） ----------------
# 见 scoring/chart_methodology.md §九（流动性猎杀）+ memory/precise-numbers-no-fuzzy：
# 报告提「流动性密集区/猎杀位/清算带」并带价位时，必须标明读取周期（日线/4H/1H/15m/3天/48H/24H），
# 否则=读位无尺度依据（清算热力图肉眼曾误差~200点）。价位本身的模糊位由 HARD 门已覆盖；本门只补「必带周期」。
# 只卡"带价位的流动性位"行——基本面宏观流动性(如「流动性缺失/未回归」无价位)不触发。
_LIQ_LEVEL = re.compile(r"流动性|猎杀|清算(?:带|区|位|磁吸|密集|热力)")
_HAS_PRICE5 = re.compile(r"\d{2}[,，]?\d{3}")  # 5位价位 6X,XXX / 62000 / 64,266
_PERIOD_TOK = re.compile(r"日线|周线|4\s*[Hh]|1\s*[Hh]|15\s*[Mm]|3\s*天|48\s*[Hh]|24\s*[Hh]|周期|小时级别|日内")

def liquidity_check(lines):
    """提流动性密集区/猎杀位且带价位的行，必须含周期标注。返回 [(行号, 命中词, 摘要)]。"""
    hits = []
    for i, ln in enumerate(lines, 1):
        m = _LIQ_LEVEL.search(ln)
        if m and _HAS_PRICE5.search(ln) and not _PERIOD_TOK.search(ln):
            hits.append((i, m.group(0), ln.strip()[:60]))
    return hits

# ---------------- 盘面五步·VRVP概率主判 软提醒门（门②扩展·2026-06-21·WARN-only） ----------------
# 见 chart_methodology §九：流动性猎杀概率「主判」= TV 成交量结构(VRVP/VAL/VAH/HVN/LVN/价值区)·
# 清算热力图仅「辅助印证」。防漂移＝「拿辅助源(热力图)当主判、§九五步只走③④⑤(热力图+落点)跳过①②
# (各周期摆动高低 + VRVP概率主判)」(2026-06-21 核验发现 6/21 早报 0 引用、晚报靠热力图articulate足
# 但 VRVP/POC 主判articulate不足)。WARN-only·不阻 push·只提醒每份盘面走满五步、主判用 VRVP 非热力图。
# 🟥 主判词刻意排除裸「POC」——②Exocharts 六源每份都有「POC 阶梯」会误判；§九主判用 TV-VRVP 专属词。
_MAINJUDGE = re.compile(r"VRVP|VAH|VAL|HVN|LVN|价值区|高量节点|成交量结构|量峰")
_AUXHEAT   = re.compile(r"清算热力|热力图|liqheatmap|清算带")
_PANEL     = re.compile(r"流动性掠夺|流掠|流动性猎杀|猎杀位|猎杀")

def panel_mainjudge_check(lines):
    """盘面/流动性猎杀节点应含 VRVP/VAH/VAL 概率「主判」(§九 C·步②)。WARN-only。
    只在报告确有盘面流动性猎杀内容时触发；两档：
      (a) 引清算热力图(辅助)却缺 VRVP 主判 = 疑似拿辅助当主判(强提醒·正是 2026-06-21 发现的反转)
      (b) 有流动性掠夺/猎杀内容但全篇无 VRVP 主判 = §九步①②疑未走(普通提醒)。
    返回 [(档, 提示)]。"""
    full = "\n".join(lines)
    if not _PANEL.search(full):
        return []
    if _MAINJUDGE.search(full):
        return []
    if _AUXHEAT.search(full):
        return [("a", "引清算热力图(辅助)却缺 VRVP/VAH/VAL 概率主判——疑似拿辅助源当主判"
                       "(§九 C=主判=TV成交量结构·D=热力图仅辅助)·补各周期摆动高低+VRVP概率主判走满五步")]
    return [("b", "盘面流动性掠夺/猎杀缺 VRVP/VAH/VAL 概率主判措辞——§九步①②(各周期摆动高低+VRVP概率主判)"
                   "疑未走满·补主判读法(热力图为辅助·非主判)")]

# ---------------- 正文英文术语门（门②扩展·2026-06-25·用户迭代） ----------------
# 见 memory/report-chinese-only-narrative.md：日报【Notion 正文】(① 正文 + ② Maker)叙事术语一律
# 中译·不留英文；保留指标缩写(CVD/OI/SMA/POC/VAH/VAL/VRVP/Delta/VWAP/R)+模板字段(Maker/TP1/TP2/
# BTC/ETH/Binance/OKX)+专有名词(交易所/源/监管/公司名·新闻里不可预知→不入禁列)。
# 设计=禁用清单(只抓已知叙事英文·不误伤新闻专有名词与保留缩写)·仅扫 '## ①'～'## ③' 之间
# (稿首 > 自查块在 ## ① 之前=豁免·③后附保留英文=豁免)。命中即 HARD。新叙事英文按需扩列。
EN_JARGON = [
    (r"squeeze",              "逼空/挤升（squeeze-back→逼空反扑·squeeze-prone→易逼空）"),
    (r"short[\- ]?cover",     "空头回补"),
    (r"roll[\- ]?over|rollover", "见顶回落/动能反转"),
    (r"confluence",           "汇合区/共振区"),
    (r"retest",               "回踩"),
    (r"\bgrab\b",             "猎取/扫取"),
    (r"\brelief\b",           "缓解性反弹"),
    (r"exhaustion",           "衰竭"),
    (r"capitulat",            "投降"),
    (r"whipsaw",              "双向扫损"),
    (r"overshoot",            "过冲"),
    (r"continuation",         "续势/续跌"),
    (r"consolidat",           "整理"),
    (r"\bmacro\b",            "宏观"),
    (r"deep[\- ]?value",      "深度价值"),
    (r"air[\- ]?pocket",      "真空薄量区"),
    (r"risk[\- ]?on",         "风险偏好"),
    (r"risk[\- ]?off",        "避险"),
    (r"\bHTF\b",              "高周期"),
    (r"\bHVN\b",              "高量节点"),
    (r"\bLVN\b",              "低量/薄量节点"),
    (r"\bfib\b",              "斐波那契"),
    (r"premium",              "优质/溢价"),
    (r"straddle",             "骑跨"),
    (r"false[\- ]?break",     "假突破"),
    (r"mean[\- ]?reversion",  "均值回归"),
    (r"\bedge\b",             "边缘"),
    (r"\bsupply\b",           "供给"),
    (r"\bfloor\b",            "底部支撑"),
    (r"\bVIEW\b",             "研判/观点"),
    (r"\blongs\b|\bshorts\b", "多头/空头"),
    (r"violent",              "剧烈"),
    (r"breakout",             "突破"),
    (r"\bwick\b",             "插针/影线"),
    (r"\brebound\b",          "反弹"),
    (r"absorption",           "吸收"),
    (r"imbalance",            "失衡"),
]
_EN_JARGON_RE = [(re.compile(p, re.IGNORECASE), d) for p, d in EN_JARGON]

def en_jargon_check(lines):
    """扫 '## ①'～'## ③' 之间正文(=Notion 正文)，抓未中译的叙事英文。返回 [(行号,描述,命中,摘要)]。
    禁用清单式：只命中已知叙事英文·不误伤保留缩写(CVD/SMA…)与新闻专有名词(Coinbase/MiCA…)。"""
    start = end = None
    for i, ln in enumerate(lines, 1):
        if re.match(r"^##\s*①", ln):
            start = i
        elif re.match(r"^##\s*③", ln):
            end = i
            break
    if start is None:
        start = 1
    if end is None:
        end = len(lines)
    hits = []
    for i in range(start, end):
        ln = lines[i - 1]
        for rgx, desc in _EN_JARGON_RE:
            m = rgx.search(ln)
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
        # 兼容当前 combined 格式：TP1：61,850，减仓50%。/ TP2：60,920，清理剩余仓位。
        if re.match(r"^[*＊\s]*TP[12]\s*[：:]", stripped):
            for tp in ("TP1", "TP2"):
                if not re.match(r"^[*＊\s]*" + tp + r"\s*[：:]", stripped):
                    continue
                m = re.search(tp + r"\s*[：:]\s*" + _PRICE, stripped)
                if m:
                    actions.append(dict(kind=tp, price=_num(m.group(1)),
                                        cut=_parse_cut(stripped),
                                        lineno=lineno, text=stripped))
        # 浮盈防守层行（剔除【已触发…】注释避免双计）
        m = re.match(r"^[*＊\s]*第([一二三四五])层[：:]", stripped)
        if m:
            main_part = ln.split("【")[0]
            mp = re.search(r"(?:价格)?(?:首次)?触及\s*" + _PRICE, main_part)
            cut = _parse_cut(main_part)
            if mp and cut is not None:
                actions.append(dict(kind="防守第%s层" % m.group(1), price=_num(mp.group(1)),
                                    cut=cut, lineno=lineno, text=main_part.strip()))
        # 兼容段落式浮盈防守："...触发第一层防守...减仓50%。...触发第二层防守..."
        # 只在单个层级片段内解析扣减，避免把 TP1 的减仓误算到防守层。
        layer_matches = list(re.finditer(r"(?:触发)?第([一二三四五])层(?:防守)?", stripped))
        for index, layer in enumerate(layer_matches):
            start = layer.start()
            end = layer_matches[index + 1].start() if index + 1 < len(layer_matches) else len(stripped)
            segment = stripped[start:end]
            cut = _parse_cut(segment)
            if cut is None:
                continue
            prefix = stripped[max(0, start - 40):start]
            mp = (
                re.search(r"(?:价格)?(?:首次)?触及\s*" + _PRICE, segment)
                or re.search(r"(?:价格)?(?:上行|下行)?至\s*" + _PRICE, segment)
                or re.search(r"(?:价格)?(?:首次)?触及\s*" + _PRICE, prefix)
                or re.search(r"(?:价格)?(?:上行|下行)?至\s*" + _PRICE, prefix)
            )
            if mp:
                actions.append(dict(kind="防守第%s层" % layer.group(1), price=_num(mp.group(1)),
                                    cut=cut, lineno=lineno, text=segment.strip()))
    return actions

_SAME_ACTION = r"同一动作|同一笔|即\s*TP|[=＝]\s*TP"

def ledger_check(lines):
    """仓位帐本一致性。返回 (issues, skip_reason)；issue = (描述, [(行号, 文本), ...])。
    仓位自 100% 起按价格触发顺序逐级扣减（空单自高向低/多单自低向高，方向由 TP2 相对 TP1 推断）：
    (a) 扣减合计>100%  (b) TP2 触发时剩余仓位 0%（死条款）
    (c) 防守层与止盈层同价各扣一次且未注明同一动作
    (d) 金标口径（2026-06-11 锁死）：防守层禁带任何减仓/平仓百分比（只移损/保本损/取消加仓，
        扣减只发生在止盈档 TP1 减仓50%→TP2 清剩余）
    (e) 执行仓位账必须显式写成 TP1 50% + TP2 剩余50%，禁止 70/30 等漂移。"""
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
    if tp1 is not None and tp1.get("cut") != 50:
        issues.append((
            "(e) TP1 必须减仓50%（冻结金标仓位账）",
            refs([tp1]),
        ))
    if tp2 is not None and not re.search(
        r"(?:清|处理)[^。；;/／]*剩余(?:仓位)?\s*50\s*[%％]",
        tp2["text"],
    ):
        issues.append((
            "(e) TP2 必须显式清剩余50%（冻结金标仓位账）",
            refs([tp2]),
        ))
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


_FOUR_H = re.compile(r"4\s*[Hh]|4\s*小时|四小时")
_BAD_FIRST_LAYER_TF = re.compile(r"15\s*[mM]|15\s*分钟|十五分钟|1\s*[Hh]|1\s*小时|一小时")
_DYNAMIC_FIRST_LAYER_EXTREME = re.compile(r"(?:成交|入场|开仓)后|后续|新形成|未来")
_CONFIRMED_FIRST_LAYER_EXTREME = re.compile(r"确认|形成")


def maker_defense_check(lines):
    """Maker 浮盈防守硬门。

    第一层必须写具体触发价；移动止损目标只能是成交后后续形成并确认的
    4H K线结构性极点，禁止在报告阶段预填历史极点价格。
    第二层只设保本损。
    返回 [(行号, 描述, 命中文本, 行摘要)]。
    """
    sec = _maker_section(lines)
    if sec is None:
        return []
    sec_text = "\n".join(ln for _, ln in sec)
    if re.search(r"观望", sec_text) and re.search(r"无新增挂单|不挂新单|不挂单", sec_text):
        return []
    issues = []
    first = [
        (lineno, ln.strip())
        for lineno, ln in sec
        if re.search(r"(?:第一层[：:]|第一层防守|触发第一层)", ln)
    ]
    second = [
        (lineno, ln.strip())
        for lineno, ln in sec
        if re.search(r"(?:第二层[：:]|第二层防守|触发第二层)", ln)
    ]
    for lineno, ln in first:
        trigger = re.search(r"(?:触及|(?:上行|下行)?至)\s*" + _PRICE, ln)
        if not trigger:
            issues.append((lineno, "Maker第一层缺具体触发价格", "第一层", ln[:70]))
            operation_text = ln
        else:
            operation_text = ln[trigger.end():]
        if "极点" not in ln:
            issues.append((lineno, "Maker第一层缺“极点”", "第一层", ln[:70]))
        if not _FOUR_H.search(ln):
            issues.append((lineno, "Maker第一层必须使用4H级别K线极点", "第一层", ln[:70]))
        if not _DYNAMIC_FIRST_LAYER_EXTREME.search(ln):
            issues.append((lineno, "Maker第一层必须声明极点来自成交后后续形成", "第一层", ln[:70]))
        if not _CONFIRMED_FIRST_LAYER_EXTREME.search(ln):
            issues.append((lineno, "Maker第一层必须声明4H极点需形成/确认后使用", "第一层", ln[:70]))
        first_operation_text = re.split(
            rf"(?:第二层[：:]|第二层防守|触发第二层|(?:触及|(?:上行|下行)?至)\s*{_PRICE}\s*后[，,]?\s*触发第二层)",
            operation_text,
            maxsplit=1,
        )[0]
        preset = _HAS_PRICE5.search(first_operation_text)
        if preset:
            issues.append((lineno, "Maker第一层禁止预填4H极点止损价", preset.group(0), ln[:70]))
        bad = _BAD_FIRST_LAYER_TF.search(ln)
        if bad:
            issues.append((lineno, "Maker第一层禁止使用1H/15m级别", bad.group(0), ln[:70]))
        if "小时级别" in ln and not re.search(r"4\s*小时级别|四小时级别", ln):
            issues.append((lineno, "Maker第一层禁止笼统“小时级别”", "小时级别", ln[:70]))
    for lineno, ln in second:
        if not re.search(r"(?:触及|(?:上行|下行)?至)\s*" + _PRICE, ln):
            issues.append((lineno, "Maker第二层缺具体触发价格", "第二层", ln[:70]))
        if "保本损" not in ln:
            issues.append((lineno, "Maker第二层必须设保本损", "第二层", ln[:70]))
        if re.search(r"(?:减仓|平仓)\s*\d", ln) and "不减仓" not in ln:
            issues.append((lineno, "Maker第二层禁止仓位扣减", "减仓/平仓", ln[:70]))
    return issues


def exocharts_ohlc_check(lines):
    """Exocharts 当前价/OHLC 自洽门。

    报告若声明“当日未完成K线”并同时给出当前图面价格，则当前价必须落在该K线高低区间内。
    否则通常代表截图十字光标停在旧K线，却被误读为当日K线。
    """
    text = "\n".join(lines)
    issues = []
    pattern = re.compile(
        r"当日未完成K线[：:]\s*开\s*" + _PRICE
        + r"[、,，]\s*高\s*" + _PRICE
        + r"[、,，]\s*低\s*" + _PRICE
        + r"[、,，]\s*收\s*" + _PRICE
        + r".{0,40}?当前(?:图面)?价格\s*" + _PRICE,
        re.S,
    )
    for match in pattern.finditer(text):
        open_, high, low, close, current = (_num(value) for value in match.groups())
        if high < low:
            issues.append((0, "Exocharts OHLC 高低倒置", f"高{high:g}/低{low:g}", ""))
        if current > high or current < low:
            issues.append((
                0,
                "Exocharts 当前价不在所称当日K线高低区间内",
                f"当前{current:g} vs 高{high:g}/低{low:g}",
                "疑似十字光标停在旧K线，禁止当作当日未完成K线",
            ))
    return issues


def _third_section_text(lines):
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^##\s*③", ln):
            start = i
            break
    if start is None:
        return ""
    return "\n".join(lines[start:])


def analysis_depth_check(lines):
    """MAX 独立分析深度门。

    ③ 后附是本地报告承载完整推理的位置。若这里只剩短摘要，即使正文格式正确，
    也等于没有完成六源验真、转录、评分、胜率、风险与情景推理。
    """
    section = _third_section_text(lines)
    issues = []
    if not section:
        return [(0, "缺少③后附完整分析区", "## ③", "报告无法建立完整分析锁")]
    required_markers = [
        ("BlockBeats", "基本面源细节"),
        ("Coinglass", "盘口源细节"),
        ("Exocharts", "足迹源细节"),
        ("FedWatch", "宏观源细节"),
        ("TradingView", "盘面源细节"),
        ("胜率", "胜率推导"),
        ("风险", "风险验算"),
    ]
    if _requires_six_sources(lines):
        required_markers.insert(4, ("Farside", "BTC ETF Flow 源细节"))
    for marker, desc in required_markers:
        if marker not in section:
            issues.append((0, f"③后附缺{desc}", marker, ""))
    if not re.search(r"VRVP|VAH|VAL|POC", section):
        issues.append((0, "③后附缺 VRVP/VAH/VAL/POC 盘面主判证据", "VRVP/VAH/VAL/POC", ""))
    if not re.search(r"情景|情形|路径|反证|失效", section):
        issues.append((0, "③后附缺情景/反证/失效路径推理", "情景/反证/失效", ""))
    return issues


def numeric_anchor_dump_check(lines):
    """Reject posthoc numeric dumps used as a fake proxy for reasoning depth."""
    text = "\n".join(lines)
    matches = re.findall(r"锚点组\s*\d+\s*[:：]", text)
    if len(matches) >= 3:
        return [(
            0,
            "后附出现数值锚点组堆砌，疑似以数字列表替代承重推理",
            f"{len(matches)} groups",
            "数字必须嵌入六源、评分、胜率、风险、情景链条；不得用锚点组凑金标深度",
        )]
    return []


_GOLDEN_PRICE_REF = re.compile(r"\d{2},\d{3}|\d{5}(?:\.\d+)?")
_STRICT_SIX_SOURCE_FROM = date(2026, 7, 5)
_STRICT_REASONING_TRACE_FROM = date(2026, 7, 6)
_STRICT_REASONING_TRACE_EXEMPT_FILE = "2026-07-06_morning_"
_V3_SEMANTICS_FROM = (date(2026, 7, 12), "midday")
_BASE_GOLDEN_SOURCES = ("BlockBeats", "Exocharts", "Coinglass", "FedWatch", "TradingView")
_SIXTH_SOURCE = "Farside"


def _report_date(lines):
    head = "\n".join(lines[:12])
    match = re.search(
        r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})",
        head,
    )
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def _report_date_from_path(report_path):
    if report_path is None:
        return None
    match = re.match(r"^(20\d{2})-(\d{2})-(\d{2})_", Path(report_path).name)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def _requires_six_sources(lines):
    report_date = _report_date(lines)
    return report_date is not None and report_date >= _STRICT_SIX_SOURCE_FROM


def _requires_strict_reasoning_trace(lines, report_path=None):
    report_date = _report_date(lines) or _report_date_from_path(report_path)
    if report_date is None or report_date < _STRICT_REASONING_TRACE_FROM:
        return False
    if report_path is not None and Path(report_path).name.startswith(_STRICT_REASONING_TRACE_EXEMPT_FILE):
        return False
    return True


def _required_source_markers(lines):
    if _requires_six_sources(lines):
        return _BASE_GOLDEN_SOURCES[:4] + (_SIXTH_SOURCE,) + _BASE_GOLDEN_SOURCES[4:]
    return _BASE_GOLDEN_SOURCES


def _has_all_patterns(text, patterns):
    return all(re.search(pattern, text, re.I) for pattern in patterns)


def strict_reasoning_trace_check(lines, report_path=None):
    """Date-gated hard gate for thick reasoning traces.

    Effective from reports after 2026-07-06 morning. It checks causality
    chains, not raw length, so the report cannot pass by padding words or
    price anchors.
    """
    if not _requires_strict_reasoning_trace(lines, report_path):
        return []
    section = _third_section_text(lines)
    if not section:
        return []
    issues = []

    winrate_chain = _has_all_patterns(section, [
        r"胜率",
        r"rubric|winrate_methodology|胜率方法论",
        r"锚|anchor",
        r"次因|微调|上调|下调|[+\-]\s*\d|±",
        r"落值|落点|落到|真实值|估值",
        r"60|门槛|阈值",
    ])
    if not winrate_chain:
        issues.append((
            0,
            "严格推理留痕：缺胜率 rubric 全链",
            "胜率 rubric 锚→次因±n→落值→比60",
            "从 2026-07-06 午报起必须写清胜率锚、调整因子、真实落值与 60 门槛比较；禁止只给胜率结论",
        ))

    score_chain = _has_all_patterns(section, [
        r"总分|总评|盘口|盘面",
        r"盘口.{0,40}\d{1,2}|盘面.{0,40}\d{1,2}|总分.{0,40}\d{2}|总评.{0,40}\d{2}",
        r"CVD|OI|资金费率|Delta|VRVP|VAH|VAL|POC|SMA20|Coinglass|Exocharts|TradingView",
        r"合成|推导|落值|扣分|加分|下调|上调|因为|来自|证据",
    ])
    if not score_chain:
        issues.append((
            0,
            "严格推理留痕：缺总分/盘口/盘面合成链",
            "盘口/盘面读数→分项落值→总分",
            "必须说明分数来自哪些盘口/盘面证据，以及如何合成为总分；禁止只贴最终分",
        ))

    direction_chain = _has_all_patterns(section, [
        r"方向|多空|主判|倾向|路径",
        r"反证|失效|情景|情形",
        r"CVD|OI|资金费率|Delta|VRVP|VAH|VAL|POC|SMA20",
    ])
    if not direction_chain:
        issues.append((
            0,
            "严格推理留痕：缺方向主判与反证链",
            "方向主判→最强反证→失效/情景路径",
            "必须把多空主判、反方证据和失效条件写在③后附；禁止只给单边结论",
        ))

    critical_markers = [
        r"pivot|枢轴|摆动|趋势线|突破|未破",
        r"CVD",
        r"SMA20",
        r"VRVP|VAH|VAL|POC",
    ]
    critical_count = sum(1 for pattern in critical_markers if re.search(pattern, section, re.I))
    if critical_count < 3:
        issues.append((
            0,
            "严格推理留痕：承重点证据颗粒度不足",
            f"{critical_count}/4 markers",
            "③后附至少覆盖 pivot/结构锚、CVD、SMA20、VRVP/VAH/VAL/POC 中 3 类承重点；推理必须聚焦关键数据",
        ))

    return issues


def v3_semantics_check(lines, report_path=None):
    """Reject legacy representative-price and probability semantics after v3."""
    if report_path is None:
        return []
    name = Path(report_path).name
    match = re.match(
        r"^(20\d{2})-(\d{2})-(\d{2})_(morning|midday|evening)_", name
    )
    if not match:
        return []
    report_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    slot = match.group(4)
    slot_index = {"morning": 0, "midday": 1, "evening": 2}
    if (report_date, slot_index[slot]) < (
        _V3_SEMANTICS_FROM[0],
        slot_index[_V3_SEMANTICS_FROM[1]],
    ):
        return []
    text = "\n".join(lines)
    issues = []
    if "胜率自估（计划时置信度，非回测命中率）" not in text:
        issues.append(
            (0, "v3置信度语义缺失", "胜率自估", "必须明确非回测命中率")
        )
    for index, line in enumerate(lines, 1):
        if "代表入场" in line:
            issues.append(
                (index, "v3禁止代表价掩盖区间风险", "代表入场", line.strip()[:80])
            )
        if re.search(
            r"最高可用模型|MAX\s*推理.*(?:确认|已确认)|推理强度.*MAX"
            r"|\bMAX\b.{0,24}(?:confirmed|verified)"
            r"|宿主模型.{0,24}\bMAX\b",
            line,
            re.I,
        ):
            issues.append(
                (
                    index,
                    "v3禁止在报告正文自证宿主模型或MAX",
                    "MAX自证",
                    "模型与推理强度只能由host_capability/host_usage工件证明，不进入交易报告",
                )
            )
    has_range = bool(re.search(r"入场(?:区间)?[^\n]{0,20}\d[\d,.]*\s*[-—–~～]\s*\d", text))
    if has_range and not re.search(r"分档|条件观察区|不是可执行订单", text):
        issues.append(
            (0, "入场区间未声明订单语义", "入场区间", "必须是分档订单或条件观察区")
        )
    if not re.search(
        r"全部情景均达到1:2\.5且不高于3%|条件观察区，不是可执行订单|无可执行 Maker 计划",
        text,
    ):
        issues.append(
            (0, "v3成交情景风险证明缺失", "风险验算", "必须由canonical report contract生成")
        )
    return issues


def golden_surface_proxy_check(lines):
    """Legacy surface proxy for thin reports.

    These checks are WARN-only. Golden alignment is a pre-write reasoning
    contract, not a posthoc length/price/rubric-count target.
    """
    section = _third_section_text(lines)
    issues = []
    required_sources = _required_source_markers(lines)
    missing_sources = [source for source in required_sources if source not in section]
    if missing_sources:
        source_label = "六源" if _requires_six_sources(lines) else "五源"
        issues.append((
            0,
            f"golden-surface-proxy：③后附未承载完整{source_label}逐项证据",
            ",".join(missing_sources),
            f"WARN only；{source_label}缺失仍会由分析深度门/源覆盖门硬拦",
        ))
    rubric_refs = section.lower().count("rubric")
    if rubric_refs < 2:
        issues.append((
            0,
            "golden-surface-proxy：评分/胜率推导链留痕不足",
            f"rubric={rubric_refs}",
            "WARN only；真实胜率推导按 winrate rubric 绝对估算",
        ))
    return issues


def golden_quality_check(lines):
    """Backward-compatible wrapper for old guardrail tests/callers.

    Golden alignment is now enforced by the pre-write reasoning manifest and
    hard depth checks. The old public helper name is kept so stale tests fail
    on real quality regressions instead of failing with AttributeError.
    """
    hits = []
    for line, desc, hit, ctx in golden_surface_proxy_check(lines):
        hits.append((line, desc.replace("golden-surface-proxy", "golden-quality"), hit, ctx))
    return hits


def main():
    # GBK 控制台防崩：正文里的 emoji（如🔴）无法编码时替换为 ?，不让 lint 自身崩溃
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    path = sys.argv[1]
    txt = open(path, encoding="utf-8").read()
    lines = txt.splitlines()
    structure_hits = []
    report_match = re.match(
        r"^(20\d{2}-\d{2}-\d{2})_(morning|midday|evening)_",
        Path(path).name,
    )
    if report_match:
        _, structure_issues = validate_combined_structure(
            lines,
            report_match.group(1),
            report_match.group(2),
        )
        structure_hits = [
            (issue.line, issue.code, issue.message, "")
            for issue in structure_issues
        ]
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
    tool_wrapper_hits = tool_wrapper_leak_check(lines)
    meta_hits = meta_narrative_check(lines)
    wr_band, wr_chain, wr_scoped = winrate_anchor_check(lines)
    wr_fail = bool(wr_band) and not wr_chain
    liq_hits = liquidity_check(lines)
    en_hits = en_jargon_check(lines)
    panel_hits = panel_mainjudge_check(lines)  # 软提醒·WARN-only·不进 FAIL
    defense_hits = maker_defense_check(lines)
    exo_hits = exocharts_ohlc_check(lines)
    depth_hits = analysis_depth_check(lines)
    anchor_dump_hits = numeric_anchor_dump_check(lines)
    strict_trace_hits = strict_reasoning_trace_check(lines, path)
    v3_hits = v3_semantics_check(lines, path)
    golden_hits = golden_surface_proxy_check(lines)
    for i, desc, hit, ctx in warn_hits:
        print(f"[WARN] L{i} {desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in hard_hits:
        print(f"[HARD] L{i} {desc}: '{hit}'  | {ctx}")
    for i, code, message, ctx in structure_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[HARD] {loc} report-structure·{code}: {message}")
    for i, desc, hit, ctx in coupling_hits:
        print(f"[HARD] L{i} 解耦门·联动红旗 {desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in tool_wrapper_hits:
        print(f"[HARD] L{i} 输出纯净门·{desc}: '{hit}'  | {ctx}")
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
    for i, desc, hit, ctx in defense_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[HARD] {loc} Maker防守层门·{desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in exo_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[HARD] {loc} Exocharts自洽门·{desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in depth_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[HARD] {loc} 分析深度门·{desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in anchor_dump_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[HARD] {loc} 金标推理门·{desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in strict_trace_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[HARD] {loc} 严格推理留痕门·{desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in v3_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[HARD] {loc} v3语义门·{desc}: '{hit}'  | {ctx}")
    for i, desc, hit, ctx in golden_hits:
        loc = f"L{i}" if i else "全文"
        print(f"[WARN] {loc} 旧金标表面代理·{desc}: '{hit}'  | {ctx}")
    if not golden_hits:
        print("[OK] 旧金标表面代理: 未发现明显变薄警示；真实金标以 pre-write reasoning manifest 为准")
    if not coupling_hits:
        print("[OK] 解耦门: 无联动用户实仓的语言")
    for i, hit, ctx in liq_hits:
        print(f"[HARD] L{i} 流动性读位门·缺周期标注 '{hit}': {ctx}")
    if not liq_hits:
        print("[OK] 流动性读位门: 流动性/猎杀价位均带周期标注(或无带价位的流动性位)")
    for i, desc, hit, ctx in en_hits:
        print(f"[HARD] L{i} 正文英文术语门·未中译 '{hit}'(→{desc}): {ctx}")
    if not en_hits:
        print("[OK] 正文英文术语门: Notion 正文(①+②)无未中译叙事英文(保留缩写/模板/专有名词除外)")
    for kind, msg in panel_hits:
        print(f"[WARN] 盘面五步·VRVP主判门: {msg}")
    if not panel_hits:
        print("[OK] 盘面五步·VRVP主判门: 含 VRVP/VAH/VAL 概率主判(或无盘面流动性猎杀节点)")
    if wr_fail:
        print(f"[HARD] 胜率反下偏门: 胜率落临界带{wr_band}(贴60门槛下方)·③后附无 rubric 推导链"
              f"(锚=X→次因→落值)→疑似贴门槛下偏·补 rubric 推导或纠真实值(见 winrate-anchoring-bias)")
    elif wr_band:
        print(f"[OK] 胜率反下偏门: 胜率{wr_band}落临界带但③后附含 rubric 推导链(已显式说明锚与下调理由)")
    else:
        print("[OK] 胜率反下偏门: 胜率未落临界带[55,59](无贴门槛下偏嫌疑)")
    print()
    if structure_hits or hard_hits or ledger_issues or coupling_hits or tool_wrapper_hits or meta_hits or wr_fail or liq_hits or en_hits or defense_hits or exo_hits or depth_hits or anchor_dump_hits or strict_trace_hits or v3_hits:
        msgs = []
        if structure_hits:
            msgs.append(f"{len(structure_hits)} 处底稿结构/六源契约错误（修正 combined 骨架、日期展示或六源证据）")
        if hard_hits:
            msgs.append(f"{len(hard_hits)} 处模糊位/占位/臆造（用核过的确切数字替换）")
        if ledger_issues:
            msgs.append(f"{len(ledger_issues)} 处仓位帐本矛盾（对照 6/2 金标：第二层只设保本损无减仓）")
        if coupling_hits:
            msgs.append(f"{len(coupling_hits)} 处联动用户实仓（违解耦边界·system-plan-decoupled·改为系统独立判断）")
        if tool_wrapper_hits:
            msgs.append(f"{len(tool_wrapper_hits)} 处工具包装元数据泄漏（删除 Exit code/Wall time/Output 等宿主文本）")
        if meta_hits:
            msgs.append(f"{len(meta_hits)} 处正文元叙事（代号/方法论/分数/门槛→改自然语言·移③后附·见 fundamentals-brief-core-priority）")
        if wr_fail:
            msgs.append(f"胜率临界带{wr_band}无 rubric 推导链（补「锚=X→次因→落值」或纠真实值·见 winrate-anchoring-bias）")
        if liq_hits:
            msgs.append(f"{len(liq_hits)} 处流动性/猎杀价位缺周期标注（必带 日线/4H/1H/15m/3天/48H/24H·见 chart_methodology §九）")
        if en_hits:
            msgs.append(f"{len(en_hits)} 处正文未中译叙事英文（→中文·保留缩写/模板/专有名词除外·见 report-chinese-only-narrative）")
        if defense_hits:
            msgs.append(f"{len(defense_hits)} 处 Maker 防守层违规（第一层只能写触发价+成交后确认4H极点规则，禁预填极点价；第二层只保本损）")
        if exo_hits:
            msgs.append(f"{len(exo_hits)} 处 Exocharts OHLC/当前价不自洽（重读截图或重采）")
        if depth_hits:
            msgs.append(f"{len(depth_hits)} 处分析深度不足（③后附必须承载完整六源/评分/胜率/风险/情景）")
        if anchor_dump_hits:
            msgs.append(f"{len(anchor_dump_hits)} 处数值锚点组堆砌（数字必须嵌入推理链而非列表凑数）")
        if strict_trace_hits:
            msgs.append(f"{len(strict_trace_hits)} 处严格推理留痕不足（胜率rubric/总分合成/方向反证/承重点颗粒度必须写清）")
        if v3_hits:
            msgs.append(f"{len(v3_hits)} 处v3语义违规（禁止代表价、伪概率或未枚举区间成交风险）")
        print(f"[FAIL] " + "；".join(msgs) + " —— 修正后重跑")
        sys.exit(1)
    suffix = "" if ledger_skip else "·仓位帐本一致"
    warn_count = len(warn_hits) + len(golden_hits) + len(panel_hits)
    print(f"[PASS] 无模糊位/占位/臆造{suffix}·无联动（{warn_count} 处 WARN 需人工确认是否核过）")

if __name__ == "__main__":
    main()
