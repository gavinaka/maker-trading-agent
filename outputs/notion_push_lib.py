# -*- coding: utf-8 -*-
"""
notion_push_lib —— 「AI agent（plan）」日报归档的可复用推送库（机制层·不含任何报告内容）。
用法：`py` 运行（python3 是 Windows stub 勿用）；token 走环境变量 `$env:NOTION_TOKEN`（绝不硬编码进库）。
每天的推送脚本 import 本库后只需「定义 blocks 内容 + 调 create_page/ensure_date_page」，
plumbing（multipart 上传 / 去重 / after 插图 / 旧块迁移 / 分页>100）全在这里，不再每天重推导。

⚠️ 写 Python 字符串内的中文引号一律用全角「」，禁用半角 " （会与字符串定界符冲突→SyntaxError）。
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid

import requests

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

def _get(url, **kw):
    """GET with retry — Notion 偶发 SSL UNEXPECTED_EOF / 网络抖动，重试 3 次。
    仅用于幂等读取；写操作(POST/PATCH)不在此自动重试，以防重复建页/重复插块。"""
    kw.setdefault("timeout", 30)
    for attempt in range(3):
        try:
            r = requests.get(url, headers=_h(), **kw); r.raise_for_status()
            return r
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise
            time.sleep(1.5)

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
        d = _get(u).json()
        out += d["results"]
        if d.get("has_more"): cur = d["next_cursor"]
        else: break
    return out

def find_child_page(parent, title_prefix):
    for b in get_children(parent):
        if b["type"] == "child_page" and b["child_page"]["title"].startswith(title_prefix):
            return b["id"]
    return None

def find_child_pages(parent, title_prefix):
    """Return every live child page whose title starts with ``title_prefix``."""
    return [
        b["id"]
        for b in get_children(parent)
        if b["type"] == "child_page"
        and b["child_page"]["title"].startswith(title_prefix)
    ]

_ISO_DATE_TITLE = re.compile(r"^(20\d{2})-(\d{1,2})-(\d{1,2})$")
_DOTTED_DATE_TITLE = re.compile(r"^(20\d{2})\.(\d{1,2})\.(\d{1,2})$")

def _date_page_title(date_str):
    """Normalize report date-page titles to the historical ``YYYY.M.D`` form."""
    value = str(date_str).strip()
    match = _ISO_DATE_TITLE.match(value) or _DOTTED_DATE_TITLE.match(value)
    if not match:
        return value
    year, month, day = match.groups()
    return f"{int(year):04d}.{int(month)}.{int(day)}"

def find_heading(blocks, text_prefix):
    for b in blocks:
        tp = b["type"]
        if tp.startswith("heading_"):
            txt = "".join(x.get("plain_text","") for x in b[tp]["rich_text"])
            if txt.startswith(text_prefix): return b["id"]
    return None

# 无人值守容错（2026-06-10 加固）：写操作【不盲重试】——SSL EOF 多发生在响应阶段，
# 请求可能已在服务端成功；盲重发 POST/PATCH 会重复建页/重复插块（6/9 实际事故的防范对象）。
# 改为「核查式恢复」：失败后先 GET 核实服务端实际落地状态，已落地则续用、未落地才重发。
_NET_ERRS = (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
             requests.exceptions.Timeout)

def _find_exact_child_page(parent, title):
    """恢复用：POST 响应丢失时核查 parent 下是否已建出同名子页（成功≠收到响应）。"""
    for b in get_children(parent):
        if b["type"] == "child_page" and b["child_page"]["title"] == title:
            return b["id"]
    return None

EXPECT_BOT = "359fda35-a098-81e0-97b8-0027dab06092"  # Slow（Claude）·用户真库 Slow丶（rotate token 不改 bot id）
EXPECT_WS = "Slow丶"
_ws_ok = False
def assert_workspace():
    """🔴 push 前置硬门（治『推到错误 workspace』）：确认 token 指向用户真库(Slow丶/359)，否则 abort，绝不推送。"""
    global _ws_ok
    if _ws_ok:
        return
    me = _get("https://api.notion.com/v1/users/me").json()
    bot = me.get("id", "")
    ws = (me.get("bot") or {}).get("workspace_name", "")
    if bot != EXPECT_BOT:
        raise SystemExit(
            f"🔴ABORT 推送前置门：token 指向错误集成 bot={bot} ws={ws!r}·"
            f"应为 {EXPECT_BOT}（Slow（Claude）/{EXPECT_WS}）·拒绝推送（防推到用户看不到的 workspace）。"
            f"请修正 NOTION_TOKEN 后重试。")
    _ws_ok = True
    print(f"[preflight] workspace OK: {ws} bot={bot[:8]}")

def verify_published(page_id, parent_id, expect_images=None):
    """🔴 push 后置硬门（治『只信 API 返回·不验地面真值』）：确认页真在 parent 下、archived=False、
    （可选）image 数达标。返回 (ok, msg)；失败＝没真正落库，调用方绝不可报成功。"""
    p = _get(f"https://api.notion.com/v1/pages/{page_id}").json()
    if p.get("archived"):
        return False, f"页 {page_id} archived=True（未存活）"
    ap = (p.get("parent") or {}).get("page_id", "")
    if ap != parent_id:
        return False, f"parent={ap} != 期望 {parent_id}（落错位置）"
    if not any(b.get("id") == page_id for b in get_children(parent_id)):
        return False, "页不在 parent 的 children 中（用户看不到）"
    if expect_images is not None:
        imgs = sum(1 for b in get_children(page_id) if b.get("type") == "image")
        if imgs != expect_images:
            return False, f"image={imgs} != 期望 {expect_images}（快讯卡缺失）"
    return True, "落库验证通过（在 parent 下·archived=False）"

def _page_title(page):
    for value in (page.get("properties") or {}).values():
        if value.get("type") == "title":
            return "".join(x.get("plain_text", "") for x in value.get("title", []))
    return ""

def archive_page(page_id):
    """Archive a page with response-loss recovery; safe to call repeatedly."""
    for attempt in range(4):
        try:
            response = requests.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=_h(),
                data=json.dumps({"archived": True}),
                timeout=30,
            )
            response.raise_for_status()
            return
        except _NET_ERRS:
            time.sleep(1.5 * (2 ** attempt))
            if _get(f"https://api.notion.com/v1/pages/{page_id}").json().get("archived"):
                return
            if attempt == 3:
                raise

def set_page_title(page_id, title):
    """Rename a page with response-loss recovery."""
    payload = {
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        }
    }
    for attempt in range(4):
        try:
            response = requests.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=_h(),
                data=json.dumps(payload),
                timeout=30,
            )
            response.raise_for_status()
            return
        except _NET_ERRS:
            time.sleep(1.5 * (2 ** attempt))
            page = _get(f"https://api.notion.com/v1/pages/{page_id}").json()
            if _page_title(page) == title:
                return
            if attempt == 3:
                raise

def verify_single_live_child(parent_id, title_prefix, expected_page_id):
    """Require exactly one live matching child and require it to be the new page."""
    matches = find_child_pages(parent_id, title_prefix)
    if matches != [expected_page_id]:
        return (
            False,
            f"live_matches={matches}，期望仅 [{expected_page_id}]",
        )
    return True, "同前缀仅一个存活页"

def assert_source_freshness(source_specs, now_ts=None):
    """Hard-stop stale/missing source files before any Notion write.

    ``source_specs`` maps a source label to either a path or a dict:
    ``{"path": ..., "max_age_minutes": 240, "same_local_day": False}``.
    Scoring sources use the four-hour hard limit from
    ``data_sources/freshness_rules.md``.  News and FedWatch may use their own
    explicit limits, but callers must not omit the four core scoring files.
    """
    now_ts = time.time() if now_ts is None else float(now_ts)
    failures = []
    ages = {}
    for label, raw_spec in source_specs.items():
        spec = {"path": raw_spec} if isinstance(raw_spec, str) else dict(raw_spec)
        path = os.path.abspath(spec["path"])
        max_age = float(spec.get("max_age_minutes", 240))
        if not os.path.isfile(path):
            failures.append(f"{label}: 缺文件 {path}")
            continue
        modified = os.path.getmtime(path)
        age_minutes = max(0.0, (now_ts - modified) / 60.0)
        ages[label] = age_minutes
        if age_minutes > max_age:
            failures.append(
                f"{label}: {age_minutes:.1f} 分钟 > {max_age:.0f} 分钟"
            )
        if spec.get("same_local_day"):
            source_day = time.localtime(modified)[:3]
            current_day = time.localtime(now_ts)[:3]
            if source_day != current_day:
                failures.append(f"{label}: 非当日采集")
    if failures:
        raise SystemExit(
            "SOURCE FRESHNESS FAILED："
            + "；".join(failures)
            + "。禁止发布可执行计划；请重采五源、重评分、重出稿。"
        )
    print(
        "SOURCE FRESHNESS PASS: "
        + ", ".join(f"{k}={v:.1f}m" for k, v in ages.items())
    )
    return ages

def _console_safe_text(text, stream):
    encoding = getattr(stream, "encoding", None) or "utf-8"
    return str(text).encode(encoding, "replace").decode(encoding, "replace")


def run_python_gate(script_path, args, label):
    """Run a Python quality gate and propagate its exit status."""
    command = [sys.executable, os.path.abspath(script_path), *args]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.stdout:
        print(_console_safe_text(result.stdout, sys.stdout), end="")
    if result.stderr:
        print(_console_safe_text(result.stderr, sys.stderr), end="", file=sys.stderr)
    if result.returncode != 0:
        detail = f"{label} FAILED: exit={result.returncode}"
        stdout_tail = _console_safe_text(result.stdout.strip()[-600:], sys.stderr)
        stderr_tail = _console_safe_text(result.stderr.strip()[-600:], sys.stderr)
        if stdout_tail:
            detail += f"; stdout_tail={stdout_tail}"
        if stderr_tail:
            detail += f"; stderr_tail={stderr_tail}"
        raise SystemExit(detail)
    print(f"{label} PASS")
    return {
        "label": label,
        "script": os.path.abspath(script_path),
        "args": list(args),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

def run_report_lint(report_path):
    run_python_gate(
        os.path.join(os.path.dirname(__file__), "report_lint.py"),
        [os.path.abspath(report_path)],
        "REPORT LINT",
    )

def run_frozen_verifier(page_id, mode):
    return run_python_gate(
        os.path.join(
            os.path.dirname(__file__),
            "notion_verify_against_yesterday.py",
        ),
        [page_id, mode],
        "FROZEN GOLD VERIFY",
    )

DAILY_REPORT_TITLE_PREFIXES = {"🌅", "🌇", "🌙"}


def _daily_report_prefix_from_title(title):
    text = str(title)
    if "日报" not in text:
        return None
    for prefix in DAILY_REPORT_TITLE_PREFIXES:
        if text.startswith(prefix):
            return prefix
    return None


def _assert_daily_publish_entrypoint(title_prefix, daily_payload_source):
    if title_prefix not in DAILY_REPORT_TITLE_PREFIXES:
        return
    if not isinstance(daily_payload_source, dict):
        raise RuntimeError(
            "daily report Notion writes must go through publish_report.py with "
            "daily_payload_builder payload_source evidence"
        )
    if (
        daily_payload_source.get("status") == "passed"
        and daily_payload_source.get("kind") == "combined_md_to_notion_payload"
    ):
        return
    if (
        daily_payload_source.get("status") == "skipped"
        and "historical" in str(daily_payload_source.get("reason", ""))
    ):
        return
    raise RuntimeError(
        "daily report Notion writes require payload_source.kind="
        "combined_md_to_notion_payload before transaction"
    )


def _assert_daily_create_entrypoint(title, daily_payload_source):
    title_prefix = _daily_report_prefix_from_title(title)
    if title_prefix is None:
        return
    _assert_daily_publish_entrypoint(title_prefix, daily_payload_source)


def replace_page_transactional(
    parent_id,
    title,
    title_prefix,
    children,
    image_after_heading,
    image_paths,
    verifier_mode,
    *,
    daily_payload_source=None,
):
    """Publish a verified replacement without deleting the last good page first.

    Prepare phase:
      1. Snapshot all matching live pages.
      2. Create a uniquely titled staging page.
      3. Upload images, verify landing, rename to the final title, and run the
         frozen verifier.
      4. Any prepare failure archives only the staging page; old pages survive.

    Commit phase:
      5. Archive old pages only after every gate passed.
      6. Require exactly one live matching page.  A commit failure keeps the
         verified new page live (duplicates are safer than data loss).
    """
    _assert_daily_publish_entrypoint(title_prefix, daily_payload_source)
    old_pages = find_child_pages(parent_id, title_prefix)
    staging_title = f"{title} [发布中-{uuid.uuid4().hex[:8]}]"
    page_id = None

    try:
        page_id = create_page(
            parent_id,
            staging_title,
            children,
            daily_payload_source=daily_payload_source,
        )
        if image_paths:
            insert_images_after_heading(
                page_id,
                image_after_heading,
                image_paths,
            )
        ok, message = verify_published(
            page_id,
            parent_id,
            expect_images=len(image_paths),
        )
        if not ok:
            raise RuntimeError("PUBLISH VERIFY FAILED: " + message)
        print("PUBLISH VERIFY PASS:", message)

        set_page_title(page_id, title)
        verifier_evidence = run_frozen_verifier(page_id, verifier_mode)
    except BaseException:
        if page_id:
            try:
                archive_page(page_id)
                print("ROLLBACK staged page:", page_id)
            except Exception as rollback_error:
                print(
                    "ROLLBACK FAILED — manual cleanup required:",
                    page_id,
                    rollback_error,
                    file=sys.stderr,
                )
        raise

    # Commit begins here.  Do not roll back the verified new page if cleanup of
    # an old page fails; keeping duplicates is safer than deleting all reports.
    for old_page in old_pages:
        if old_page != page_id:
            archive_page(old_page)
            print("archived old:", old_page)

    unique, unique_message = verify_single_live_child(
        parent_id,
        title_prefix,
        page_id,
    )
    if not unique:
        raise RuntimeError("LIVE PAGE UNIQUENESS FAILED: " + unique_message)
    print("LIVE PAGE UNIQUENESS PASS:", unique_message)
    return page_id, old_pages, verifier_evidence

def create_page(parent, title, children, *, daily_payload_source=None):
    _assert_daily_create_entrypoint(title, daily_payload_source)
    assert_workspace()  # 🔴前置门：token 指向错误 workspace 即 abort，杜绝推错地方
    head, rest = children[:100], children[100:]
    payload = {"parent":{"type":"page_id","page_id":parent},
               "properties":{"title":{"title":[{"type":"text","text":{"content":title}}]}},
               "children":head}
    pid = None
    for attempt in range(4):
        try:
            r = requests.post("https://api.notion.com/v1/pages", headers=_h(),
                              data=json.dumps(payload), timeout=60)
            r.raise_for_status(); pid = r.json()["id"]; break
        except _NET_ERRS:
            time.sleep(1.5 * (2 ** attempt))
            pid = _find_exact_child_page(parent, title)  # 页已建(含 head·POST 原子) → 复用，绝不重发
            if pid: break
            if attempt == 3: raise
    done = len(head)
    while rest:
        chunk, rest = rest[:100], rest[100:]
        for attempt in range(4):
            try:
                r = requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children",
                                   headers=_h(), data=json.dumps({"children":chunk}), timeout=60)
                r.raise_for_status(); done += len(chunk); break
            except _NET_ERRS:
                time.sleep(1.5 * (2 ** attempt))
                have = len(get_children(pid))
                if have >= done + len(chunk):   # 该 chunk 已落地(响应丢失) → 不重发
                    done += len(chunk); break
                if have != done:                # 部分落地(PATCH 应原子·理论不出现) → 硬停人工核查
                    raise RuntimeError(f"children 部分写入 have={have} done={done} page={pid} 人工核查")
                if attempt == 3: raise          # 确认未落地 → 重发安全；4 次仍败则抛出
    return pid

def ensure_date_page(date_str):
    """date_str 形如 '2026.6.2'，返回 AI agent plan 下日期子页 id，缺则建空页。"""
    title = _date_page_title(date_str)
    pid = find_child_page(AI_AGENT_PLAN, title)
    if pid:
        return pid
    legacy_pid = None if title == date_str else find_child_page(AI_AGENT_PLAN, date_str)
    if legacy_pid:
        set_page_title(legacy_pid, title)
        return legacy_pid
    return create_page(AI_AGENT_PLAN, title, [])

def upload_image(path, name=None):
    if not os.path.isfile(path):  # 🔴门D：图文件不存在即明确 abort（治 cards 没生成/push 图名不匹配的 FileNotFoundError 半途崩）
        raise SystemExit(f"🔴ABORT 插图：图文件不存在 {path}·先确认 cards 脚本已生成图、且 push 的 imgs 路径名与 cards 输出名一致（make_card 首参=fname）。")
    name = name or os.path.basename(path)
    # 图片上传是日志里实际报 SSL EOF 的点，可安全重试；
    # 关键：每次重试都重开文件句柄（文件指针已到 EOF 时重发会传空内容）。
    for attempt in range(3):
        try:
            r = requests.post("https://api.notion.com/v1/file_uploads",
                              headers=_h(), data=json.dumps({}), timeout=30); r.raise_for_status()
            fu = r.json()
            with open(path, "rb") as f:
                r2 = requests.post(fu["upload_url"], headers=_h(json_ct=False),
                                   files={"file":(name, f, "image/png")}, timeout=60); r2.raise_for_status()
            return fu["id"]
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise
            time.sleep(1.5)

def insert_after(page, after_id, blocks):
    patch = {"children":blocks}
    if after_id: patch["after"] = after_id
    r = requests.patch(f"https://api.notion.com/v1/blocks/{page}/children",
                       headers=_h(), data=json.dumps(patch)); r.raise_for_status()

def insert_images_after_heading(page, heading_prefix, image_paths):
    """幂等化（固化 6/9 守卫脚本经验·查 has_img 再插）：页内图已齐则跳过（重跑/恢复场景防重复插图）；
    插入失败(SSL EOF)后复查——单次 PATCH 原子，图已落地则不重发。"""
    blocks = get_children(page)
    have = sum(1 for b in blocks if b["type"] == "image")
    if have >= len(image_paths):
        return
    hid = find_heading(blocks, heading_prefix)
    imgs = [image_block(upload_image(p)) for p in image_paths]
    for attempt in range(4):
        try:
            insert_after(page, hid, imgs); return
        except _NET_ERRS:
            time.sleep(1.5 * (2 ** attempt))
            now = sum(1 for b in get_children(page) if b["type"] == "image")
            if now >= have + len(imgs):   # 已落地(响应丢失) → 不重发
                return
            if attempt == 3: raise

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

def push_subpage(
    date_str,
    title,
    children,
    img_after_heading=None,
    img_paths=None,
    dedup_prefix=None,
    *,
    daily_payload_source=None,
):
    """一站式：定位/建日期页 → 防重复 → 建子页(写 children) → 可选在某标题后插图。返回子页 id 或 None(已存在)。"""
    date_page = ensure_date_page(date_str)
    if dedup_prefix and find_child_page(date_page, dedup_prefix):
        print(f"ABORT 已存在同名子页: {dedup_prefix}"); return None
    pid = create_page(
        date_page,
        title,
        children,
        daily_payload_source=daily_payload_source,
    )
    if img_after_heading and img_paths:
        insert_images_after_heading(pid, img_after_heading, img_paths)
    return pid
