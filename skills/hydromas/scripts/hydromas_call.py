#!/usr/bin/env python3
"""HydroMAS CLI — OpenClaw 技能调用脚本。

用法:
    python3 hydromas_call.py chat "自然语言问题" [--role operator|researcher|designer]
    python3 hydromas_call.py report "自然语言问题" [--role ...] [--folder TOKEN] [--user-openid ID]
    python3 hydromas_call.py skill <技能名> ['{"param":"value"}']
    python3 hydromas_call.py sim [duration] [--initial_h 0.5] [--title "..."]
    python3 hydromas_call.py skills [--role operator]
    python3 hydromas_call.py health
    python3 hydromas_call.py roles
    python3 hydromas_call.py history [--user-openid ID] [--limit N]

report 命令 = chat + 自动生成飞书文档（含表格+图表），返回文档链接。
--user-openid: 指定请求用户的飞书 open_id，文档将授权给该用户 + 管理员。
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time as _time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import requests as _req

BASE_URL = "http://localhost:8000"
TIMEOUT = 180  # bumped from 120 for large sims
CHART_DIR = "/tmp/hydromas-charts"
HYDROMAS_API_KEY = os.environ.get("HYDROMAS_API_KEY", "")

# ── Feishu config ──
FEISHU_BASE = "https://open.feishu.cn/open-apis"
FEISHU_APP_ID = "cli_a915cc56d5f89cb1"
FEISHU_APP_SECRET = "t4fBWSGN56TEzZrNXvvYTbYWOMlZFjxR"
DEFAULT_USER_OPENID = "ou_607e1555930b5636c8b88b176b9d3bf2"  # admin/default
FEISHU_DOC_DOMAIN = "leixiaohui1974.feishu.cn"

# Feishu block types
BT_TEXT, BT_H2, BT_H3, BT_H4 = 2, 4, 5, 6
BT_BULLET, BT_ORDERED, BT_CODE = 12, 13, 14
BT_QUOTE, BT_DIVIDER, BT_IMAGE = 15, 22, 27
BT_TABLE, BT_TABLE_CELL = 31, 32

# ── Feishu token cache & session pool ──
_feishu_token_cache: dict = {"token": None, "expires": 0}
_feishu_session: _req.Session | None = None


def _get_feishu_session() -> _req.Session:
    """Return a reusable requests.Session (TCP connection pooling)."""
    global _feishu_session
    if _feishu_session is None:
        _feishu_session = _req.Session()
        _feishu_session.headers.update({"Content-Type": "application/json"})
    return _feishu_session


def _api_headers() -> dict:
    """Build common headers for HydroMAS API calls."""
    h = {"Content-Type": "application/json"}
    if HYDROMAS_API_KEY:
        h["X-API-Key"] = HYDROMAS_API_KEY
    return h


def _post(path: str, data: dict) -> dict:
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers=_api_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"error": str(e)}


def _post_binary(path: str, data: dict) -> bytes | dict:
    """POST and return raw bytes (for image endpoints)."""
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers=_api_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "image" in ct:
                return resp.read()
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"error": str(e)}


def _get(path: str) -> dict:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    if HYDROMAS_API_KEY:
        req.add_header("X-API-Key", HYDROMAS_API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"error": str(e)}


def _save_chart(png_data: bytes, prefix: str = "sim") -> str:
    """Save PNG data to CHART_DIR, return the file path."""
    os.makedirs(CHART_DIR, exist_ok=True)
    ts = int(_time.time())
    path = f"{CHART_DIR}/{prefix}_{ts}.png"
    with open(path, "wb") as f:
        f.write(png_data)
    return path


def _format_sim_summary(summary: dict) -> str:
    """Format simulation summary as Markdown table."""
    dur = summary.get("duration", 0)
    lines = [
        "### 仿真参数",
        "",
        "| 参数 | 值 |",
        "|------|------|",
        f"| 仿真时长 | {dur:.0f}s ({dur/60:.1f}min) |",
        f"| 时间步长 | {summary.get('dt', 1.0)}s |",
        f"| 求解器 | {summary.get('solver', '?')} |",
        f"| 步数 | {summary.get('steps', '?')} |",
        "",
        "### 水位变化",
        "",
        "| 指标 | 值 (m) |",
        "|------|--------|",
        f"| 初始水位 | {summary.get('initial_h', 0):.4f} |",
        f"| 最终水位 | {summary.get('final_h', 0):.4f} |",
        f"| 最高水位 | {summary.get('max_h', 0):.4f} |",
        f"| 最低水位 | {summary.get('min_h', 0):.4f} |",
        f"| 水位变化 | {summary.get('h_change', 0):+.4f} |",
        "",
        "### 流量",
        "",
        "| 指标 | 值 (m³/s) |",
        "|------|-----------|",
    ]
    if summary.get("inflow_start") is not None:
        lines.append(f"| 入流 | {summary['inflow_start']:.6f} → {summary.get('inflow_end', 0):.6f} |")
    if summary.get("outflow_start") is not None:
        lines.append(f"| 出流 | {summary['outflow_start']:.6f} → {summary.get('outflow_end', 0):.6f} |")
    return "\n".join(lines)


def _generate_chart_from_sim(sim_data: dict, title: str = "水箱仿真结果") -> str | None:
    """Call HydroMAS chart API to generate a chart from simulation data. Returns file path or None."""
    if "water_level" not in sim_data or "time" not in sim_data:
        return None

    chart_req = {
        "time": sim_data["time"],
        "water_level": sim_data["water_level"],
        "outflow": sim_data.get("outflow", []),
        "inflow": sim_data.get("inflow", []),
        "title": title,
    }
    result = _post_binary("/api/chart/render", chart_req)
    if isinstance(result, bytes):
        return _save_chart(result, "sim")
    return None


def _format_result(data: dict, indent: int = 0) -> str:
    """Format dict as readable Markdown. Simulation data gets special treatment."""
    if "error" in data:
        return f"**Error**: {data['error']}"

    # Detect simulation result
    inner = data.get("data", data)
    if isinstance(inner, dict) and "water_level" in inner and "time" in inner:
        # Generate chart
        tool_name = data.get("tool", data.get("skill", "simulate"))
        chart_path = _generate_chart_from_sim(inner, f"HydroMAS - {tool_name}")

        # Build summary from raw data
        wl = inner["water_level"]
        outflow = inner.get("outflow", [])
        inflow = inner.get("inflow", [])
        meta = inner.get("metadata", {})
        dur = inner["time"][-1] if inner["time"] else 0

        summary = {
            "duration": dur, "dt": meta.get("dt", 1.0), "solver": meta.get("solver", "?"),
            "steps": meta.get("steps", len(wl) - 1),
            "initial_h": wl[0], "final_h": wl[-1], "max_h": max(wl), "min_h": min(wl),
            "h_change": wl[-1] - wl[0],
            "inflow_start": inflow[0] if inflow else None,
            "inflow_end": inflow[-1] if inflow else None,
            "outflow_start": outflow[0] if outflow else None,
            "outflow_end": outflow[-1] if outflow else None,
        }

        parts = []
        if data.get("status"):
            parts.append(f"**状态**: {data['status']}")
        if data.get("tool"):
            parts.append(f"**工具**: {data['tool']}")
        header = " | ".join(parts) if parts else ""

        text = f"{header}\n\n{_format_sim_summary(summary)}"
        if chart_path:
            text += f"\n\n**过程线图**: {chart_path}"
        return text

    # Generic formatting
    lines = []
    for k, v in data.items():
        prefix = "  " * indent
        if isinstance(v, dict):
            lines.append(f"{prefix}**{k}**:")
            lines.append(_format_result(v, indent + 1))
        elif isinstance(v, list):
            if len(v) > 20 and all(isinstance(x, (int, float)) for x in v):
                lines.append(f"{prefix}**{k}**: [{v[0]:.4f}, ..., {v[-1]:.4f}] ({len(v)} values)")
            else:
                lines.append(f"{prefix}**{k}**:")
                for item in v:
                    if isinstance(item, dict):
                        lines.append(_format_result(item, indent + 1))
                        lines.append("")
                    else:
                        lines.append(f"{prefix}  - {item}")
        else:
            lines.append(f"{prefix}**{k}**: {v}")
    return "\n".join(lines)


# ── Commands ──────────────────────────────────────────────

def cmd_chat(args: list[str]):
    """Natural language chat with HydroMAS."""
    if not args:
        print("Usage: hydromas_call.py chat \"your question\" [--role operator|researcher|designer]")
        sys.exit(1)

    message = args[0]
    role = "operator"

    i = 1
    while i < len(args):
        if args[i] == "--role" and i + 1 < len(args):
            role = args[i + 1]
            i += 2
        else:
            i += 1

    # Auto-detect role from keywords
    msg_lower = message.lower()
    if any(k in msg_lower for k in ["仿真", "模拟", "simulate", "水箱", "阶跃", "数据分析", "wnal"]):
        if role == "operator":
            role = "researcher"
    elif any(k in msg_lower for k in ["控制设计", "优化设计", "蒸发优化", "回用优化", "pid", "mpc"]):
        if role == "operator":
            role = "designer"

    result = _post("/api/gateway/chat", {
        "message": message,
        "role": role,
        "session_id": "",
        "params": {},
    })

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"## HydroMAS ({role})\n")
    if isinstance(result.get("response"), str):
        print(result["response"])
    elif isinstance(result.get("result"), dict):
        print(_format_result(result["result"]))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_sim(args: list[str]):
    """Run simulation + chart in one step via /api/chart/simulate-and-chart."""
    duration = 300.0
    initial_h = 0.5
    title = "水箱仿真结果"

    i = 0
    while i < len(args):
        if args[i] == "--initial_h" and i + 1 < len(args):
            initial_h = float(args[i + 1]); i += 2
        elif args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]; i += 2
        elif args[i].replace(".", "").isdigit():
            duration = float(args[i]); i += 1
        else:
            i += 1

    result = _post("/api/chart/simulate-and-chart", {
        "duration": duration,
        "initial_h": initial_h,
        "title": title,
    })

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    # Save chart
    chart_b64 = result.get("chart_base64", "")
    chart_path = None
    if chart_b64:
        png = base64.b64decode(chart_b64)
        chart_path = _save_chart(png, "sim")

    # Output
    summary = result.get("summary", {})
    print(f"## HydroMAS 仿真结果\n")
    print(_format_sim_summary(summary))
    if chart_path:
        size_kb = result.get("chart_size", 0) / 1024
        print(f"\n**过程线图**: {chart_path} ({size_kb:.0f} KB)")


def cmd_skill(args: list[str]):
    """Call a HydroMAS skill directly."""
    if not args:
        print("Usage: hydromas_call.py skill <skill_name> ['{\"param\":\"value\"}']")
        sys.exit(1)

    skill_name = args[0]
    params = json.loads(args[1]) if len(args) > 1 else {}

    result = _post("/api/gateway/skill", {
        "skill_name": skill_name,
        "params": params,
    })

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"## Skill: {skill_name}\n")
    if isinstance(result.get("result"), dict):
        print(_format_result(result["result"]))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_skills(args: list[str]):
    """List available skills."""
    role = None
    for i, a in enumerate(args):
        if a == "--role" and i + 1 < len(args):
            role = args[i + 1]

    path = "/api/gateway/skills"
    if role:
        path += f"?role={role}"
    result = _get(path)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"## HydroMAS Skills ({result.get('total', '?')} total)\n")
    for s in result.get("skills", []):
        name = s.get("name", "?")
        desc = s.get("description", "").split("/")[0].strip()
        triggers = ", ".join(s.get("trigger_phrases", []))
        status = "active" if s.get("has_instance") else "inactive"
        print(f"- **{name}** [{status}]: {desc}")
        if triggers:
            print(f"  触发词: {triggers}")


def cmd_health(args: list[str]):
    """Check HydroMAS health."""
    result = _get("/api/gateway/health")
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    status = result.get("status", "unknown")
    agents = result.get("agents_registered", 0)
    layers = result.get("platform", {}).get("layers", [])
    print(f"Status: {status}")
    print(f"Agents: {agents}")
    print(f"Layers: {', '.join(layers)}")


def cmd_roles(args: list[str]):
    """Show available roles."""
    result = _get("/api/gateway/roles")
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    for role_id, info in result.get("roles", {}).items():
        name = info.get("name", role_id)
        desc = info.get("description", "")
        caps = ", ".join(info.get("capabilities", []))
        print(f"### {name} ({role_id})")
        print(f"  {desc}")
        print(f"  能力: {caps}")
        print()


# ══════════════════════════════════════════════════════════════
# Feishu Document helpers (for report command)
# ══════════════════════════════════════════════════════════════

def _feishu_token():
    """Get Feishu tenant_access_token (cached for 55 min)."""
    now = _time.time()
    if _feishu_token_cache["token"] and now < _feishu_token_cache["expires"]:
        return _feishu_token_cache["token"]
    s = _get_feishu_session()
    r = s.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
               json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Feishu auth failed: {d}")
    _feishu_token_cache["token"] = d["tenant_access_token"]
    _feishu_token_cache["expires"] = now + 55 * 60  # 55 min TTL
    return d["tenant_access_token"]


def _feishu_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _feishu_create_doc(token, title, folder_token=None):
    """Create a new Feishu document. Returns doc_token."""
    s = _get_feishu_session()
    body = {"title": title}
    if folder_token:
        body["folder_token"] = folder_token
    r = s.post(f"{FEISHU_BASE}/docx/v1/documents",
               headers=_feishu_headers(token), json=body)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Create doc failed: {d}")
    return d["data"]["document"]["document_id"]


def _feishu_create_blocks(token, doc_token, parent_id, blocks, index=-1):
    """Create child blocks in a Feishu doc."""
    s = _get_feishu_session()
    body = {"children": blocks}
    if index >= 0:
        body["index"] = index
    r = s.post(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{parent_id}/children",
        headers=_feishu_headers(token), json=body)
    d = r.json()
    if d.get("code") != 0:
        return None, d
    return d["data"]["children"], None


def _feishu_create_table(token, doc_token, rows, index=-1):
    """Create a native Feishu table and populate cell content.

    Steps: 1) Create empty table  2) PATCH each cell's text block.
    Returns True on success.
    """
    s = _get_feishu_session()

    n_rows = len(rows)
    n_cols = max(len(r) for r in rows) if rows else 0
    if n_rows == 0 or n_cols == 0:
        return False

    # Step 1: Create empty table structure
    table_block = {
        "block_type": BT_TABLE,
        "table": {
            "property": {
                "row_size": n_rows,
                "column_size": n_cols,
                "header_row": True,
                "column_width": [200] * n_cols,
            }
        },
    }
    body = {"children": [table_block]}
    if index >= 0:
        body["index"] = index
    r = s.post(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
        headers=_feishu_headers(token), json=body)
    d = r.json()
    if d.get("code") != 0:
        return False

    cell_ids = d["data"]["children"][0].get("table", {}).get("cells", [])
    if len(cell_ids) != n_rows * n_cols:
        return False

    # Step 2: PATCH each cell's text block with content
    hdrs = _feishu_headers(token)
    for idx, cell_id in enumerate(cell_ids):
        ri, ci = divmod(idx, n_cols)
        cell_text = rows[ri][ci] if ci < len(rows[ri]) else ""
        is_header = (ri == 0)

        r2 = s.get(
            f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{cell_id}/children",
            headers=hdrs)
        text_blocks = r2.json().get("data", {}).get("items", [])
        if not text_blocks:
            continue

        text_block_id = text_blocks[0]["block_id"]
        patch_body = {
            "update_text_elements": {
                "elements": [{
                    "text_run": {
                        "content": cell_text or " ",
                        "text_element_style": {"bold": True} if is_header else {},
                    }
                }]
            }
        }
        s.patch(
            f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{text_block_id}",
            headers=hdrs, json=patch_body)

    return True


def _feishu_upload_image(token, parent_block_id, image_path):
    """Upload image to Feishu. Returns file_token."""
    s = _get_feishu_session()
    with open(image_path, "rb") as f:
        r = s.post(
            f"{FEISHU_BASE}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}", "Content-Type": None},
            data={
                "file_name": os.path.basename(image_path),
                "parent_type": "docx_image",
                "parent_node": parent_block_id,
                "size": str(os.path.getsize(image_path)),
            },
            files={"file": (os.path.basename(image_path), f, "image/png")})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Upload image failed: {d}")
    return d["data"]["file_token"]


def _feishu_patch_image(token, doc_token, block_id, file_token):
    """Patch an image block with an uploaded file."""
    s = _get_feishu_session()
    r = s.patch(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{block_id}",
        headers=_feishu_headers(token),
        json={"replace_image": {"token": file_token}})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Patch image failed: {d}")


def _feishu_grant(token, doc_token, openid, perm="full_access"):
    """Grant permission on a document."""
    s = _get_feishu_session()
    r = s.post(
        f"{FEISHU_BASE}/drive/v1/permissions/{doc_token}/members?type=docx",
        headers=_feishu_headers(token),
        json={"member_type": "openid", "member_id": openid, "perm": perm})
    return r.json().get("code") == 0


def _grant_multi_users(token, doc_token, user_openids=None):
    """Grant document access to admin + any extra requesting users."""
    # Always grant to admin
    _feishu_grant(token, doc_token, DEFAULT_USER_OPENID)
    # Grant to extra users (skip duplicates)
    if user_openids:
        for oid in user_openids:
            if oid and oid != DEFAULT_USER_OPENID:
                _feishu_grant(token, doc_token, oid)


def _text_elements(text):
    """Parse inline Markdown (bold, links) into Feishu text elements."""
    elements = []
    pattern = r'(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))'
    parts = re.split(pattern, text)
    for p in parts:
        if not p:
            continue
        if p.startswith("**") and p.endswith("**"):
            elements.append({"text_run": {
                "content": p[2:-2],
                "text_element_style": {"bold": True}
            }})
        else:
            m = re.match(r'\[([^\]]+)\]\(([^)]+)\)', p)
            if m:
                elements.append({"text_run": {
                    "content": m.group(1),
                    "text_element_style": {"link": {"url": m.group(2)}}
                }})
            else:
                elements.append({"text_run": {
                    "content": p,
                    "text_element_style": {}
                }})
    if not elements:
        elements = [{"text_run": {"content": text or " ", "text_element_style": {}}}]
    return elements


def _make_block(block_type, field_name, text):
    return {"block_type": block_type, field_name: {"elements": _text_elements(text)}}


def _md_to_feishu_blocks(md_text):
    """Convert Markdown text to Feishu block list."""
    lines = md_text.split('\n')
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # Skip H1 (doc title)
        if re.match(r'^#\s+[^#]', stripped):
            i += 1
            continue
        if stripped in ('---', '***', '___'):
            blocks.append({"block_type": BT_DIVIDER, "divider": {}})
            i += 1; continue
        if stripped.startswith('## '):
            blocks.append(_make_block(BT_H2, "heading2", stripped[3:]))
            i += 1; continue
        if stripped.startswith('### '):
            blocks.append(_make_block(BT_H3, "heading3", stripped[4:]))
            i += 1; continue
        if stripped.startswith('#### '):
            blocks.append(_make_block(BT_H4, "heading4", stripped[5:]))
            i += 1; continue
        # Table → native Feishu table block (block_type=31)
        if stripped.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            rows = []
            for tl in table_lines:
                if re.match(r'^\|[-:\s|]+\|$', tl):
                    continue
                cells = [c.strip() for c in tl.strip('|').split('|')]
                rows.append(cells)
            if rows:
                blocks.append({"_table": True, "rows": rows})
            continue
        if stripped.startswith('- '):
            blocks.append(_make_block(BT_BULLET, "bullet", stripped[2:]))
            i += 1; continue
        m = re.match(r'^(\d+)\.\s+(.+)', stripped)
        if m:
            blocks.append(_make_block(BT_ORDERED, "ordered", m.group(2)))
            i += 1; continue
        if stripped.startswith('> '):
            blocks.append(_make_block(BT_QUOTE, "quote", stripped[2:]))
            i += 1; continue
        # Code block
        if stripped.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            code_text = '\n'.join(code_lines) or " "
            blocks.append({
                "block_type": BT_CODE,
                "code": {
                    "elements": [{"text_run": {"content": code_text, "text_element_style": {}}}],
                    "style": {"language": 1}
                }
            })
            continue
        # Regular text
        blocks.append({"block_type": BT_TEXT, "text": {"elements": _text_elements(stripped)}})
        i += 1
    return blocks


def _feishu_write_blocks(token, doc_token, blocks):
    """Write a mixed list of regular blocks and table markers to a Feishu doc.

    Handles {"_table": True, "rows": [...]} entries via create+PATCH,
    and batches regular blocks via the children API.
    Returns number of blocks written.
    """
    written = 0
    batch = []

    def _flush_batch():
        nonlocal written
        if not batch:
            return
        batch_size = 20
        for start in range(0, len(batch), batch_size):
            chunk = batch[start:start + batch_size]
            created, err = _feishu_create_blocks(token, doc_token, doc_token, chunk)
            if err:
                for b in chunk:
                    c, e = _feishu_create_blocks(token, doc_token, doc_token, [b])
                    if c:
                        written += 1
            else:
                written += len(created)
        batch.clear()

    for item in blocks:
        if isinstance(item, dict) and item.get("_table"):
            # Flush pending regular blocks first
            _flush_batch()
            # Create native table then PATCH cell content
            rows = item["rows"]
            ok = _feishu_create_table(token, doc_token, rows)
            if ok:
                written += 1
            else:
                # Fallback: write table as text rows
                fallback = [{"block_type": BT_TEXT, "text": {"elements": [
                    {"text_run": {"content": " │ ".join(rows[0]),
                                  "text_element_style": {"bold": True}}}
                ]}}]
                for row in rows[1:]:
                    fallback.append({"block_type": BT_TEXT, "text": {
                        "elements": _text_elements(" │ ".join(row))
                    }})
                c, e = _feishu_create_blocks(token, doc_token, doc_token, fallback)
                written += len(fallback) if not e else 0
        else:
            batch.append(item)

    _flush_batch()
    return written


def _publish_to_feishu(title, md_text, chart_path=None, folder_token=None,
                       user_openids=None):
    """Create a Feishu doc, write content, insert chart, grant access. Returns doc URL.

    Args:
        user_openids: list of extra user open_ids to grant access (admin always included).
    """
    token = _feishu_token()
    s = _get_feishu_session()

    doc_token = _feishu_create_doc(token, title, folder_token)

    blocks = _md_to_feishu_blocks(md_text)
    written = _feishu_write_blocks(token, doc_token, blocks)

    # Insert chart image
    if chart_path and os.path.exists(chart_path):
        r = s.get(
            f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
            headers=_feishu_headers(token), params={"page_size": 50})
        d = r.json()
        all_blocks = d.get("data", {}).get("items", [])
        if all_blocks:
            last_block_id = all_blocks[-1]["block_id"]
            last_index = len(all_blocks)
            # Create empty image block
            created, err = _feishu_create_blocks(
                token, doc_token, doc_token,
                [{"block_type": BT_IMAGE, "image": {}}],
                index=last_index)
            if created:
                img_block_id = created[0]["block_id"]
                file_token = _feishu_upload_image(token, img_block_id, chart_path)
                _feishu_patch_image(token, doc_token, img_block_id, file_token)

    # Grant access — admin + requesting user(s)
    _grant_multi_users(token, doc_token, user_openids)

    doc_url = f"https://{FEISHU_DOC_DOMAIN}/docx/{doc_token}"
    return doc_url, doc_token, written


def _generate_tank_schematic(params: dict) -> str | None:
    """Call HydroMAS chart API to generate a tank schematic. Returns PNG path or None."""
    result = _post_binary("/api/chart/schematic", params)
    if isinstance(result, bytes):
        return _save_chart(result, "schematic")
    return None


def _build_analysis_markdown(data: dict) -> str:
    """Build comprehensive Markdown report from tank-analysis API response."""
    params = data.get("parameters", {})
    analysis = data.get("analysis", {})
    odd = data.get("odd_check", {})
    insights = data.get("insights", [])
    recommendations = data.get("recommendations", [])

    dur = params.get("duration_s", 300)
    lines = [
        f"# {data.get('title', 'HydroMAS 仿真分析报告')}",
        "",
        f"> 生成时间：{data.get('generated_at', '')[:19]}  |  HydroMAS 五层架构平台",
        "",
        "---",
        "",
        "## 一、仿真配置",
        "",
        "| 参数 | 值 | 说明 |",
        "|------|------|------|",
        f"| 水箱截面积 | {params.get('tank_area_m2', '?')} m² | 水平截面 |",
        f"| 流量系数 Cd | {params.get('discharge_coeff', '?')} | Torricelli 出流系数 |",
        f"| 出口面积 | {params.get('outlet_area_m2', '?')} m² | 底部出口 |",
        f"| 水位上限 | {params.get('h_max_m', '?')} m | ODD 安全边界 |",
        f"| 初始水位 | {params.get('initial_h_m', '?')} m | 仿真起点 |",
        f"| 入流量 | {params.get('q_in_m3s', '?'):.4f} m³/s | {'恒定' if params.get('inflow_type') == 'constant' else '时变'} |",
        f"| 仿真时长 | {dur:.0f}s ({dur/60:.1f}min) | 时间步长 {params.get('dt_s', '?')}s |",
        f"| 求解器 | {params.get('solver', '?')} | {'四阶 Runge-Kutta' if params.get('solver') == 'rk4' else 'Euler 法'} |",
        "",
        "## 二、系统概念图",
        "",
        "（见下方插图）",
        "",
        "## 三、仿真结果",
        "",
        "### 3.1 水位变化",
        "",
        "| 指标 | 值 (m) | 含义 |",
        "|------|--------|------|",
        f"| 初始水位 | {analysis.get('initial_h', 0):.4f} | 仿真起点 |",
        f"| 最终水位 | {analysis.get('final_h', 0):.4f} | 仿真终点 |",
        f"| 最高水位 | {analysis.get('h_max_sim', 0):.4f} | 过程最大 |",
        f"| 最低水位 | {analysis.get('h_min_sim', 0):.4f} | 过程最小 |",
        f"| 水位变化 | {analysis.get('h_change', 0):+.4f} | 净变化量 |",
        f"| 体积变化 | {analysis.get('volume_change_m3', 0):+.4f} m³ | ΔV = Δh × A |",
        "",
        "### 3.2 流量统计",
        "",
        "| 指标 | 值 |",
        "|------|------|",
        f"| 总入流 | {analysis.get('q_in_total_m3', 0):.4f} m³ |",
        f"| 总出流 | {analysis.get('q_out_total_m3', 0):.4f} m³ |",
        f"| 质量守恒误差 | {analysis.get('mass_balance_error_m3', 0):.6f} m³ |",
        "",
        "### 3.3 动态特性",
        "",
        f"- **响应类型**: {analysis.get('response_type', '?')}",
        f"- **是否达稳态**: {'是' if analysis.get('is_steady_state') else '否'}",
        f"- **理论稳态水位**: {analysis.get('h_steady_state_theory', 0):.4f} m",
    ]

    tau = analysis.get("time_constant_s")
    if tau:
        lines.append(f"- **系统时间常数**: τ ≈ {tau:.0f}s ({tau/60:.1f}min)")

    lines += [
        "",
        "## 四、过程线图",
        "",
        "（见下方插图）",
        "",
        "## 五、ODD 安全评估",
        "",
        f"**状态**: {odd.get('status', '?')}",
        f"- 上限裕度: {odd.get('margin_high_pct', '?')}%",
        f"- 下限裕度: {odd.get('margin_low_pct', '?')}%",
        "",
    ]
    for v in odd.get("violations", []):
        lines.append(f"- {v}")

    lines += [
        "",
        "## 六、物理解读",
        "",
    ]
    for i, ins in enumerate(insights, 1):
        lines.append(f"{i}. {ins}")

    if recommendations:
        lines += [
            "",
            "## 七、工程建议",
            "",
        ]
        for r in recommendations:
            lines.append(f"- {r}")

    lines += [
        "",
        "---",
        "",
        "*报告由 HydroMAS 五层架构平台自动生成（L0 Core → L2 MCP → L4 Agent → OpenClaw）*",
    ]
    return "\n".join(lines)


def _publish_report_to_feishu(title, md_text, images, folder_token=None,
                              user_openids=None):
    """Create Feishu doc with content and multiple images. Returns (url, doc_token, written).

    Args:
        user_openids: list of extra user open_ids to grant access (admin always included).
    """
    token = _feishu_token()
    s = _get_feishu_session()

    doc_token = _feishu_create_doc(token, title, folder_token)

    blocks = _md_to_feishu_blocks(md_text)
    written = _feishu_write_blocks(token, doc_token, blocks)

    # Insert images at section markers
    for img_info in images:
        img_path = img_info["path"]
        section_keyword = img_info["after_section"]
        if not img_path or not os.path.exists(img_path):
            continue

        r = s.get(
            f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
            headers=_feishu_headers(token), params={"page_size": 100})
        d = r.json()
        all_blocks = d.get("data", {}).get("items", [])

        # Find the section
        target_idx = len(all_blocks)  # default: append at end
        heading_fields = {4: "heading2", 5: "heading3", 6: "heading4"}
        found_section = False
        for bi, blk in enumerate(all_blocks):
            bt = blk.get("block_type", 0)
            field = heading_fields.get(bt)
            if field and field in blk:
                txt = ""
                for el in blk[field].get("elements", []):
                    if "text_run" in el:
                        txt += el["text_run"]["content"]
                if section_keyword in txt:
                    found_section = True
                elif found_section:
                    target_idx = bi
                    break
        if found_section and target_idx == len(all_blocks):
            target_idx = len(all_blocks)

        # Create image block
        created, err = _feishu_create_blocks(
            token, doc_token, doc_token,
            [{"block_type": BT_IMAGE, "image": {}}],
            index=target_idx)
        if created:
            img_block_id = created[0]["block_id"]
            file_token = _feishu_upload_image(token, img_block_id, img_path)
            _feishu_patch_image(token, doc_token, img_block_id, file_token)

    # Grant access — admin + requesting user(s)
    _grant_multi_users(token, doc_token, user_openids)

    doc_url = f"https://{FEISHU_DOC_DOMAIN}/docx/{doc_token}"
    return doc_url, doc_token, written


def _parse_sim_params(text: str) -> dict:
    """Extract simulation parameters from natural language text.

    Supports Chinese and English patterns like:
      初始水位1.0米, 时长600秒, 面积2平方米, 入流0.02m³/s,
      出口面积0.005, 流量系数0.65, duration 600, initial_h 1.0, etc.
    Returns a dict with keys matching TankAnalysisRequest fields.
    """
    params: dict = {}

    # --- initial water level ---
    m = re.search(r'初始水位\s*([\d.]+)\s*(?:米|m)', text)
    if not m:
        m = re.search(r'initial[_\s]?h(?:eight)?\s*[=:]\s*([\d.]+)', text, re.I)
    if not m:
        m = re.search(r'水位\s*([\d.]+)\s*(?:米|m)', text)
    if m:
        params["initial_h"] = float(m.group(1))

    # --- duration ---
    m = re.search(r'时长\s*([\d.]+)\s*(?:秒|s)', text)
    if not m:
        m = re.search(r'(?:仿真|模拟)?\s*([\d.]+)\s*(?:秒|s)\b', text)
    if not m:
        m = re.search(r'duration\s*[=:]\s*([\d.]+)', text, re.I)
    if m:
        params["duration"] = float(m.group(1))

    # --- tank area ---
    m = re.search(r'(?:水箱)?面积\s*([\d.]+)\s*(?:平方米|m²|m2|㎡)', text)
    if not m:
        m = re.search(r'(?:tank[_\s]?)?area\s*[=:]\s*([\d.]+)', text, re.I)
    if m:
        params.setdefault("tank_params", {})["area"] = float(m.group(1))

    # --- outlet area ---
    m = re.search(r'出口面积\s*([\d.]+)\s*(?:平方米|m²|m2|㎡)?', text)
    if not m:
        m = re.search(r'outlet[_\s]?area\s*[=:]\s*([\d.]+)', text, re.I)
    if m:
        params.setdefault("tank_params", {})["outlet_area"] = float(m.group(1))

    # --- discharge coefficient ---
    m = re.search(r'(?:流量系数|Cd)\s*[=:]\s*([\d.]+)', text, re.I)
    if m:
        params.setdefault("tank_params", {})["cd"] = float(m.group(1))

    # --- inflow ---
    m = re.search(r'入流\s*([\d.]+)\s*(?:m³/s)?', text)
    if not m:
        m = re.search(r'q[_\s]?in\s*[=:]\s*([\d.]+)', text, re.I)
    if m:
        params["q_in_profile"] = [[0, float(m.group(1))]]

    # --- dt ---
    m = re.search(r'(?:步长|dt)\s*[=:]\s*([\d.]+)', text, re.I)
    if m:
        params["dt"] = float(m.group(1))

    return params


# ══════════════════════════════════════════════════════════════
# Generic skill routing + adaptive report architecture
# ══════════════════════════════════════════════════════════════

_skills_cache: dict = {"skills": None, "expires": 0}

# Strong simulation keywords — always indicate tank simulation
_SIM_STRONG = {"仿真", "模拟", "水位变化", "阶跃响应", "水动力"}
# "水箱" alone is too broad (e.g. "水箱PID控制器" is control design, not sim).
# Require "水箱" + a simulation-context word.
_SIM_CONTEXT = {"初始水位", "时长", "入流", "出流", "水位", "运行", "排水", "充水"}
# Non-simulation override: if any of these appear, skip simulation route
_SIM_OVERRIDE = {"控制器", "pid", "mpc", "控制系统", "参数整定", "设计控制"}


def _find_matching_skill(message: str) -> str | None:
    """Dynamically match message to a HydroMAS skill via trigger phrases.

    Queries /api/gateway/skills to get available skills and their trigger phrases,
    then uses a two-level scoring strategy:
      - Exact phrase match in message: 3 points per match
      - Individual word match (for multi-word triggers): 1 point per word
    Tie-breaking: earliest match position in message wins (primary intent first).
    """
    now = _time.time()
    if _skills_cache["skills"] is None or now > _skills_cache["expires"]:
        result = _get("/api/gateway/skills")
        _skills_cache["skills"] = result.get("skills", [])
        _skills_cache["expires"] = now + 300  # 5 min cache

    skills = _skills_cache["skills"]
    msg_lower = message.lower()
    best_match = None
    best_score = 0
    best_pos = len(msg_lower)  # position of earliest trigger match (lower = better)

    for skill in skills:
        triggers = skill.get("trigger_phrases", [])
        score = 0
        earliest_pos = len(msg_lower)

        for t in triggers:
            t_lower = t.lower()
            pos = msg_lower.find(t_lower)
            if pos >= 0:
                # Exact phrase match: 3 points
                score += 3
                earliest_pos = min(earliest_pos, pos)
            else:
                # Word-level match: check if all words in trigger appear in message
                words = [w for w in re.split(r'[\s\-_]+', t_lower) if len(w) >= 2]
                if words and all(w in msg_lower for w in words):
                    score += 1
                    for w in words:
                        p = msg_lower.find(w)
                        if p >= 0:
                            earliest_pos = min(earliest_pos, p)

        if score > best_score or (score == best_score and score > 0
                                  and earliest_pos < best_pos):
            best_score = score
            best_match = skill.get("name")
            best_pos = earliest_pos

    return best_match if best_score > 0 else None


def _is_simulation_request(message: str) -> bool:
    """Check if the message is specifically a tank simulation request.

    Tank simulation uses the rich /api/report/tank-analysis endpoint which
    produces structured data with simulation arrays, ODD checks, and insights.
    Avoids false positives like "水箱PID控制器" (control design, not simulation).
    """
    msg_lower = message.lower()
    # Override: control/design keywords mean it's NOT a simulation
    if any(kw in msg_lower for kw in _SIM_OVERRIDE):
        return False
    # Strong sim keywords always match
    if any(kw in msg_lower for kw in _SIM_STRONG):
        return True
    # "水箱" needs context (e.g. "水箱仿真" yes, "水箱控制器" no)
    if "水箱" in msg_lower:
        return any(ctx in msg_lower for ctx in _SIM_CONTEXT)
    return False


# ── Default parameters for each skill (based on alumina plant config) ──

# ── Default parameters for each skill (alumina plant real operating data) ──
# Node format: node_id + node_type required by calc_full_plant_balance
_ALUMINA_NODES = [
    {"node_id": "water_treatment", "node_type": "intake", "q_in": 433, "q_out": 420, "q_loss": 13},
    {"node_id": "clear_pool", "node_type": "pool", "q_in": 420, "q_out": 415, "q_loss": 5, "volume": 6000, "capacity": 8000},
    {"node_id": "high_pool", "node_type": "pool", "q_in": 665, "q_out": 650, "q_loss": 15, "volume": 10000, "capacity": 15000},
    {"node_id": "ws_dissolution", "node_type": "workshop", "q_in": 158, "q_out": 140, "q_loss": 18},
    {"node_id": "ws_evaporation", "node_type": "workshop", "q_in": 50, "q_out": 42, "q_loss": 8},
    {"node_id": "ws_decomposition", "node_type": "workshop", "q_in": 21, "q_out": 19, "q_loss": 2},
    {"node_id": "ws_red_mud", "node_type": "workshop", "q_in": 136, "q_out": 100, "q_loss": 36},
    {"node_id": "ws_calcination", "node_type": "workshop", "q_in": 33, "q_out": 20, "q_loss": 13},
    {"node_id": "ws_raw_material", "node_type": "workshop", "q_in": 17, "q_out": 15, "q_loss": 2},
    {"node_id": "ws_auxiliary", "node_type": "workshop", "q_in": 18, "q_out": 16, "q_loss": 2},
    {"node_id": "cooling_towers", "node_type": "workshop", "q_in": 175, "q_out": 0, "q_loss": 0, "q_evap": 175},
    {"node_id": "reuse_station", "node_type": "reuse", "q_in": 250, "q_out": 240, "q_loss": 10},
]
# Edge format: [source_id, dest_id] pairs
_ALUMINA_EDGES = [
    ["water_treatment", "clear_pool"],
    ["clear_pool", "high_pool"],
    ["high_pool", "ws_dissolution"],
    ["high_pool", "ws_evaporation"],
    ["high_pool", "ws_decomposition"],
    ["high_pool", "ws_red_mud"],
    ["high_pool", "ws_calcination"],
    ["high_pool", "ws_raw_material"],
    ["high_pool", "ws_auxiliary"],
    ["high_pool", "cooling_towers"],
    ["ws_dissolution", "reuse_station"],
    ["ws_evaporation", "reuse_station"],
    ["reuse_station", "high_pool"],
]
_TOWER_PARAMS = {
    "water_flow_m3h": 500, "t_in": 42, "t_out": 32, "n_cells": 4, "fan_power_kw": 55,
}
_WEATHER = {"t_db": 28, "t_wb": 22, "humidity": 0.65, "wind_speed": 2.5}
# calc_params for predict_calcination_evap: slurry_flow, moisture, temp
_CALC_PARAMS = {"slurry_flow": 25.0, "moisture": 0.15, "temp": 1000}
# mud_params for predict_red_mud_water: mud_mass, moisture_ratio
_MUD_PARAMS = {"mud_mass": 800, "moisture_ratio": 0.55}

_SKILL_DEFAULTS: dict[str, dict] = {
    "evap_optimization": {
        "tower_params": _TOWER_PARAMS,
        "weather": _WEATHER,
        "calc_params": _CALC_PARAMS,
        "mud_params": _MUD_PARAMS,
    },
    "global_dispatch": {
        # Skill reads "historical_demand"; internally passes as "historical_data" to MCP tool
        "historical_demand": [10200, 10400, 10350, 10500, 10380, 10450, 10400],
        "weather_forecast": [
            {"t_db": 28, "t_wb": 22, "humidity": 0.65, "wind_speed": 2.5},
            {"t_db": 30, "t_wb": 23, "humidity": 0.60, "wind_speed": 3.0},
            {"t_db": 27, "t_wb": 21, "humidity": 0.70, "wind_speed": 2.0},
        ],
        # optimize_global_dispatch expects: demand_forecast, supply_config
        "supply_config": {
            "wujiang": {"capacity": 7800},
            "flood_channel": {"capacity": 2600},
        },
    },
    "daily_report": {
        "nodes_data": _ALUMINA_NODES,
        "edges_data": _ALUMINA_EDGES,
        "tower_params": _TOWER_PARAMS,
        "weather": _WEATHER,
        "calc_params": _CALC_PARAMS,
        "mud_params": _MUD_PARAMS,
    },
    "leak_diagnosis": {
        "nodes_data": _ALUMINA_NODES,
        "edges_data": _ALUMINA_EDGES,
    },
    "reuse_scheduling": {
        "sources": [
            {"id": "ws_dissolution_out", "flow_m3d": 3360, "quality": {"tds": 800, "ph": 12}},
            {"id": "ws_evaporation_out", "flow_m3d": 1008, "quality": {"tds": 500, "ph": 10}},
            {"id": "ws_decomposition_out", "flow_m3d": 456, "quality": {"tds": 300, "ph": 9}},
        ],
        "demands": [
            {"id": "cooling_towers", "flow_m3d": 4200, "quality_req": {"tds_max": 1000, "ph_range": [6, 10]}},
            {"id": "ws_raw_material", "flow_m3d": 400, "quality_req": {"tds_max": 2000}},
        ],
    },
    "odd_assessment": {
        "current_state": {
            "total_intake": 10400, "reuse_rate": 0.36,
            "reservoir_level": 0.75, "total_demand": 350,
        },
        "system_capabilities": {
            "sensing": 65, "communication": 70, "modeling": 55,
            "prediction": 60, "control": 50, "odd_monitoring": 45,
            "decision_support": 40,
        },
    },
    "data_analysis_predict": {
        "raw_data": [
            1.0, 0.98, 0.95, 0.93, 0.90, 0.88, 0.85, 0.83, 0.82, 0.80,
            0.79, 0.78, 0.77, 0.76, 0.76, 0.75, 0.75, 0.74, 0.74, 0.74,
        ],
        "horizon": 10,
        "model": "linear",
    },
    "control_system_design": {},
}


def _get_skill_defaults(skill_name: str) -> dict:
    """Return default parameters for a skill, based on the alumina plant config."""
    return _SKILL_DEFAULTS.get(skill_name, {})


def _humanize_key(key: str) -> str:
    """Convert snake_case keys to human-readable bilingual (Chinese + English) labels.
    将 snake_case 键名转换为中英文双语标签。"""
    KEY_MAP = {
        # ── 仿真 / Simulation ──
        "initial_h": "初始水位 Initial Level (m)",
        "final_h": "最终水位 Final Level (m)",
        "h_change": "水位变化 Level Change (m)",
        "h_max_sim": "最高水位 Max Level (m)",
        "h_min_sim": "最低水位 Min Level (m)",
        "volume_change_m3": "体积变化 Volume Change (m³)",
        "duration": "时长 Duration (s)",
        "dt": "时间步长 Time Step (s)",
        "tank_area": "水箱面积 Tank Area (m²)",
        "max_level": "最大水位 Max Level (m)",
        "min_level": "最小水位 Min Level (m)",
        "final_level": "最终水位 Final Level (m)",
        "level_range": "水位范围 Level Range",
        "time": "时间 Time",
        "water_level": "水位 Water Level",
        "outflow": "出流 Outflow",
        "inflow": "入流 Inflow",
        "inflow_rate": "入流量 Inflow Rate",
        # ── 控制 / Control ──
        "controller_type": "控制器类型 Controller Type",
        "setpoint": "设定值 Setpoint",
        "performance_metrics": "性能指标 Performance Metrics",
        "control_output": "控制输出 Control Output",
        "error": "误差 Error",
        "settling_time": "调节时间 Settling Time (s)",
        "overshoot": "超调量 Overshoot (%)",
        "rise_time": "上升时间 Rise Time (s)",
        "steady_state_error": "稳态误差 Steady-State Error",
        "response_time": "响应时间 Response Time (s)",
        "open_loop_simulation": "开环仿真 Open-Loop Sim",
        "control_simulation": "闭环仿真 Closed-Loop Sim",
        "response_type": "响应类型 Response Type",
        "is_steady_state": "是否达稳态 Steady State",
        "h_steady_state_theory": "理论稳态水位 Theoretical SS Level (m)",
        "time_constant_s": "时间常数 Time Constant (s)",
        # ── 辨识 / Identification ──
        "identification": "系统辨识 System ID",
        "identified_params": "辨识参数 Identified Params",
        "fit_error": "拟合误差 Fit Error",
        "model_type": "模型类型 Model Type",
        # ── 预测 / Prediction ──
        "forecast": "预报结果 Forecast",
        "predictions": "预测值 Predictions",
        "confidence_upper": "置信区间上界 Confidence Upper",
        "confidence_lower": "置信区间下界 Confidence Lower",
        "confidence_level": "置信水平 Confidence Level",
        "horizon": "预测期数 Forecast Horizon",
        "model": "预测模型 Model",
        "backtest": "回测 Backtest",
        "backtest_fitted": "回测拟合值 Backtest Fitted",
        "cleaned_data": "清洗后数据 Cleaned Data",
        "cleaned_timeseries": "清洗后时序 Cleaned Series",
        "accuracy": "精度 Accuracy",
        # ── 预警 / Warning ──
        "warning": "预警信息 Warning",
        "warning_level": "预警等级 Warning Level",
        "rehearsal": "预演方案 Rehearsal",
        "plan": "应急预案 Plan",
        "risk_threshold": "风险阈值 Risk Threshold",
        "risk_score": "风险得分 Risk Score",
        # ── 水量平衡 / Water Balance ──
        "total_intake": "总取水量 Total Intake (m³/d)",
        "total_consumption": "总消耗量 Total Consumption (m³/d)",
        "total_loss": "总漏损 Total Loss (m³/d)",
        "total_evap": "总蒸发 Total Evaporation (m³/d)",
        "balance_error": "平衡误差 Balance Error (m³)",
        "residual": "残差 Residual",
        "is_balanced": "是否平衡 Balanced",
        "node_residuals": "节点残差 Node Residuals",
        "node_type": "节点类型 Node Type",
        "q_in_total_m3": "总入流 Total Inflow (m³)",
        "q_out_total_m3": "总出流 Total Outflow (m³)",
        "mass_balance_error_m3": "质量守恒误差 Mass Balance Error (m³)",
        "balance": "平衡 Balance",
        "balance_data": "平衡数据 Balance Data",
        "nodes": "节点 Nodes",
        "edges": "边 Edges",
        # ── 蒸发 / Evaporation ──
        "evaporation": "蒸发 Evaporation",
        "evaporation_loss": "蒸发损失 Evaporation Loss",
        "evap_daily_m3": "日蒸发量 Daily Evap (m³)",
        "evap_rate_m3h": "蒸发速率 Evap Rate (m³/h)",
        "evap_ratio": "蒸发比 Evap Ratio",
        "total_daily_m3": "日总蒸发量 Total Daily Evap (m³)",
        "total_hourly_m3": "时总蒸发量 Total Hourly Evap (m³/h)",
        "water_carry_m3d": "日带水量 Daily Water Carry (m³)",
        "water_carry_m3h": "时带水量 Hourly Water Carry (m³/h)",
        "cooling_tower": "冷却塔 Cooling Tower",
        "calcination": "焙烧 Calcination",
        "red_mud": "赤泥 Red Mud",
        "breakdown": "分项明细 Breakdown",
        # ── 泄漏检测 / Leak Detection ──
        "leak_detected": "泄漏检测 Leak Detected",
        "leak_location": "泄漏位置 Leak Location",
        "leak_probability": "泄漏概率 Leak Probability",
        "anomaly_scores": "异常分数 Anomaly Scores",
        "max_score": "最大分数 Max Score",
        "suspects": "嫌疑管段 Suspect Pipes",
        "n_suspects": "嫌疑管段数 Num Suspects",
        "pipe_id": "管段标识 Pipe ID",
        "pipe_segment": "管段 Pipe Segment",
        "confidence": "置信度 Confidence",
        "attention_weight": "关注权重 Attention Weight",
        "connected_nodes": "连接节点 Connected Nodes",
        "fused_results": "融合结果 Fused Results",
        "combined_confidence": "综合置信度 Combined Confidence",
        "evidence": "证据 Evidence",
        # ── 回用 / Reuse ──
        "reuse_rate": "回用率 Reuse Rate",
        "new_reuse_rate": "新回用率 New Reuse Rate",
        "current_reuse_rate": "当前回用率 Current Reuse Rate",
        "matched_sources": "匹配水源 Matched Sources",
        "matched_demands": "匹配需求 Matched Demands",
        "matched_paths": "匹配路径 Matched Paths",
        "unmatched": "未匹配 Unmatched",
        "source_quality": "源水质 Source Quality",
        "n_matched": "匹配数 Matched Count",
        "n_unmatched": "未匹配数 Unmatched Count",
        "quality_margin": "水质裕度 Quality Margin",
        "cod_margin": "COD裕度 COD Margin",
        "turbidity_margin": "浊度裕度 Turbidity Margin",
        "rejection_reasons": "拒绝理由 Rejection Reasons",
        "total_reuse_m3d": "总回用量 Total Reuse (m³/d)",
        "total_demand_m3d": "总需求 Total Demand (m³/d)",
        "reuse_volume": "回用量 Reuse Volume",
        "water_saving": "节水量 Water Saving",
        "improvement": "改进幅度 Improvement",
        "daily_savings_m3": "日节水量 Daily Savings (m³)",
        "annual_savings_m3": "年节水量 Annual Savings (m³)",
        "daily_cost_saving_cny": "日节省费用 Daily Savings (CNY)",
        "annual_cost_saving_cny": "年节省费用 Annual Savings (CNY)",
        "water_price_cny_per_m3": "水价 Water Price (CNY/m³)",
        # ── 调度 / Dispatch ──
        "schedule": "调度方案 Schedule",
        "dispatch_commands": "调度指令 Dispatch Commands",
        "total_demand": "总需求 Total Demand",
        "total_supply": "总供水 Total Supply",
        "allocation": "分配 Allocation",
        "deficit": "短缺 Deficit",
        "rule_applied": "应用规则 Rule Applied",
        "priority": "优先级 Priority",
        "best_scheme": "最优方案 Best Scheme",
        "rank": "排名 Rank",
        "scheme_index": "方案索引 Scheme Index",
        "label": "标签 Label",
        "total_score": "总分 Total Score",
        "safety_score": "安全分 Safety Score",
        "efficiency_score": "效率分 Efficiency Score",
        "cost_score": "成本分 Cost Score",
        "cost": "成本 Cost",
        "feasible": "可行性 Feasibility",
        "rule": "规则 Rule",
        "method": "方法 Method",
        "source_id": "水源标识 Source ID",
        "target_id": "目标标识 Target ID",
        "volume_m3d": "体积 Volume (m³/d)",
        # ── ODD / 运行设计域 ──
        "current_odd_status": "当前ODD状态 Current ODD Status",
        "scan_results": "边界扫描结果 Scan Results",
        "odd_zone": "ODD区域 ODD Zone",
        "odd_violations": "ODD越界 ODD Violations",
        "odd_assessment": "ODD评估 ODD Assessment",
        "worst_zone": "最坏区域 Worst Zone",
        "time_to_breach": "越界时间 Time to Breach",
        "violations": "越界情况 Violations",
        "n_violations": "越界数 Num Violations",
        "recommended_action": "推荐行动 Recommended Action",
        "zone": "区域 Zone",
        "bounds": "边界 Bounds",
        "n_checked": "检查数 Num Checked",
        "mrc_plan": "最小风险方案 MRC Plan",
        "safety_verification": "安全验证 Safety Verification",
        "approved": "是否批准 Approved",
        "safety_rating": "安全评级 Safety Rating",
        "non_engineering_measures": "非工程措施 Non-Engineering Measures",
        "reporting_flow": "上报流程 Reporting Flow",
        "current_zone": "当前区域 Current Zone",
        "scenarios_tested": "测试方案数 Scenarios Tested",
        "scenarios_with_violations": "有越界方案数 Scenarios with Violations",
        "scenario": "方案 Scenario",
        "forecast_used": "使用的预报 Forecast Used",
        # ── WNAL / 水网自主等级 ──
        "wnal_assessment": "WNAL水网自主等级评估 WNAL Assessment",
        "wnal_level": "WNAL等级 WNAL Level",
        "wnal_score": "WNAL分数 WNAL Score",
        "wnal_gaps": "WNAL差距 WNAL Gaps",
        "overall_assessment": "总体评估 Overall Assessment",
        "level_description": "等级描述 Level Description",
        "score": "分数 Score",
        "total_weighted": "总加权分 Total Weighted",
        "max_possible": "最大可能分 Max Possible",
        "recommendations": "改进建议 Recommendations",
        "capability": "能力 Capability",
        "raw_score": "原始分数 Raw Score",
        "weight": "权重 Weight",
        "weighted_score": "加权分数 Weighted Score",
        "gap": "差距 Gap",
        "improvement_impact": "改进影响 Improvement Impact",
        "dimensions": "维度 Dimensions",
        # ── KPI / 关键绩效指标 ──
        "rmse": "均方根误差 RMSE",
        "mae": "平均绝对误差 MAE",
        "RMSE": "均方根误差 RMSE",
        "MAE": "平均绝对误差 MAE",
        "MAPE": "平均绝对百分比误差 MAPE",
        "NSE": "纳什效率系数 NSE",
        "r_squared": "决定系数 R²",
        "kpi_score": "KPI分数 KPI Score",
        "pump_efficiency": "泵效率 Pump Efficiency",
        "water_per_ton_alumina": "吨氧化铝用水量 Water/Ton Alumina",
        # ── 异常检测 / Anomaly Detection ──
        "anomalies": "异常项 Anomalies",
        "anomaly_count": "异常数 Anomaly Count",
        "classification": "分类 Classification",
        "outliers": "异常值 Outliers",
        "n_outliers": "异常值数 Num Outliers",
        "removed_indices": "移除索引 Removed Indices",
        # ── 设计 / Design ──
        "supply_capacity": "供水能力 Supply Capacity",
        "min_reserve_time": "最小储备时间 Min Reserve Time",
        "peak_demand": "峰值需求 Peak Demand",
        "optimal_area": "优化面积 Optimal Area",
        "optimal_height": "优化高度 Optimal Height",
        "capacity": "容量 Capacity",
        "sensitivity_indices": "敏感性指数 Sensitivity Indices",
        "ranking": "排列 Ranking",
        "parameter_ranges": "参数范围 Parameter Ranges",
        # ── 通用 / General ──
        "summary": "摘要 Summary",
        "status": "状态 Status",
        "level": "等级 Level",
        "message": "信息 Message",
        "success": "执行状态 Success",
        "steps_completed": "完成步骤 Steps Completed",
        "execution_time": "执行时间 Execution Time (s)",
        "data": "数据 Data",
        "details": "详情 Details",
        "date": "日期 Date",
        "report_markdown": "报告内容 Report",
        "target_config": "目标配置 Target Config",
        "sensor_id": "传感器标识 Sensor ID",
        "timestamp": "时间戳 Timestamp",
        "amplitude_db": "幅值 Amplitude (dB)",
        "frequency_hz": "频率 Frequency (Hz)",
        "n_results": "结果数 Num Results",
        # ── 技能名称 / Skill Names ──
        "daily_report": "日运营报告 Daily Report",
        "odd_assessment": "ODD安全评估 ODD Assessment",
        "data_analysis_predict": "数据分析预测 Data Analysis & Prediction",
        "control_system_design": "控制系统设计 Control System Design",
        "evap_optimization": "蒸发优化 Evaporation Optimization",
        "global_dispatch": "全局调度优化 Global Dispatch",
        "leak_diagnosis": "泄漏诊断 Leak Diagnosis",
        "reuse_scheduling": "回用调度 Reuse Scheduling",
        "four_prediction_loop": "四预闭环 Four-Prediction Loop",
        "forecast_skill": "预报 Forecast",
        "warning_skill": "预警 Warning",
        "rehearsal_skill": "预演 Rehearsal",
        "plan_skill": "预案 Plan",
        "full_lifecycle": "全生命周期 Full Lifecycle",
        "optimization_design": "优化设计 Optimization Design",
    }
    if key in KEY_MAP:
        return KEY_MAP[key]
    # Fallback: attempt basic word-level Chinese translation for common terms
    WORD_MAP = {
        "total": "总", "max": "最大", "min": "最小", "avg": "平均",
        "rate": "率", "count": "计数", "num": "数量", "score": "分数",
        "water": "水", "level": "水位", "flow": "流量", "pipe": "管道",
        "node": "节点", "edge": "边", "loss": "损失", "gain": "增益",
        "input": "输入", "output": "输出", "error": "误差", "time": "时间",
        "daily": "日", "annual": "年", "monthly": "月", "hourly": "时",
        "pressure": "压力", "quality": "水质", "energy": "能耗",
        "pump": "泵", "valve": "阀门", "tank": "水箱", "tower": "塔",
        "demand": "需求", "supply": "供给", "balance": "平衡",
    }
    english_title = key.replace("_", " ").replace("-", " ").title()
    # Try to build a partial Chinese prefix from known words
    words = key.lower().replace("-", "_").split("_")
    cn_parts = [WORD_MAP[w] for w in words if w in WORD_MAP]
    if cn_parts:
        return "".join(cn_parts) + " " + english_title
    return english_title


def _format_value(v) -> str:
    """Format a value for display in a table cell.
    将值格式化为中文友好的表格单元格内容。"""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, float):
        if abs(v) < 0.001 and v != 0:
            return f"{v:.6f}"
        return f"{v:.4f}"
    # Translate common English status/value strings to bilingual
    VALUE_MAP = {
        "safe": "安全 Safe", "at_risk": "有风险 At Risk", "danger": "危险 Danger",
        "normal": "正常 Normal", "extended": "扩展 Extended", "mrc": "最小风险 MRC",
        "completed": "已完成 Completed", "failed": "失败 Failed",
        "pending": "待处理 Pending", "running": "运行中 Running",
        "unknown": "未知 Unknown", "none": "无 None",
        "low": "低 Low", "medium": "中 Medium", "high": "高 High",
        "critical": "严重 Critical",
        "linear": "线性 Linear", "polynomial": "多项式 Polynomial",
        "lstm": "LSTM神经网络",
        "True": "是", "False": "否",
        "true": "是", "false": "否",
    }
    s = str(v)
    if s in VALUE_MAP:
        return VALUE_MAP[s]
    return s


def _render_dict_to_md(d: dict, lines: list, level: int = 2):
    """Recursively render a dict as Markdown sections and tables.

    - Flat dicts (all scalar values) → table
    - Nested dicts → sub-sections
    - Lists of dicts → table rows
    - Lists of scalars → bullet list or summary
    - Time-series arrays (time, water_level, etc.) → skipped (handled by chart generator)
    """
    TIMESERIES_KEYS = {"time", "water_level", "outflow", "inflow", "response", "t"}
    heading = "#" * min(level, 5)

    # Separate scalar vs complex items
    scalars = {}
    complex_items = {}
    for k, v in d.items():
        if k in TIMESERIES_KEYS and isinstance(v, list) and len(v) > 10:
            continue  # skip raw time series
        if isinstance(v, (str, int, float, bool, type(None))):
            scalars[k] = v
        else:
            complex_items[k] = v

    # Render scalars as a table if there are multiple
    if len(scalars) >= 2:
        lines.append("| 指标 | 值 |")
        lines.append("|------|------|")
        for k, v in scalars.items():
            lines.append(f"| {_humanize_key(k)} | {_format_value(v)} |")
        lines.append("")
    elif len(scalars) == 1:
        k, v = next(iter(scalars.items()))
        lines.append(f"- **{_humanize_key(k)}**: {_format_value(v)}")
        lines.append("")

    # Render complex items
    for k, v in complex_items.items():
        if isinstance(v, dict):
            lines.append(f"{heading} {_humanize_key(k)}")
            lines.append("")
            _render_dict_to_md(v, lines, level + 1)
        elif isinstance(v, list):
            if not v:
                continue
            if all(isinstance(x, (int, float)) for x in v):
                if len(v) > 10:
                    lines.append(f"- **{_humanize_key(k)}**: {len(v)} 个数据点 [{v[0]:.4f} ... {v[-1]:.4f}]")
                else:
                    lines.append(f"- **{_humanize_key(k)}**: {', '.join(_format_value(x) for x in v)}")
            elif all(isinstance(x, dict) for x in v):
                lines.append(f"{heading} {_humanize_key(k)}")
                lines.append("")
                keys = list(v[0].keys())
                lines.append("| " + " | ".join(_humanize_key(kk) for kk in keys) + " |")
                lines.append("|" + "------|" * len(keys))
                for row in v[:20]:  # limit to 20 rows
                    lines.append("| " + " | ".join(_format_value(row.get(kk, "")) for kk in keys) + " |")
                if len(v) > 20:
                    lines.append(f"| ... | 共 {len(v)} 行 |")
                lines.append("")
            elif all(isinstance(x, str) for x in v):
                for x in v:
                    lines.append(f"- {x}")
                lines.append("")
            else:
                lines.append(f"- **{_humanize_key(k)}**: {json.dumps(v, ensure_ascii=False)[:200]}")
                lines.append("")


def _trim_large_data(data: dict, max_list_items: int = 5, max_depth: int = 4) -> dict:
    """Trim large nested data to prevent massive reports.
    限制嵌套数据大小以避免报告过大。
    """
    import copy

    def _trim(obj, depth=0):
        if depth > max_depth:
            if isinstance(obj, dict):
                return {f"...{len(obj)} items...": "..."}
            if isinstance(obj, list):
                return [f"...{len(obj)} items..."]
            return obj
        if isinstance(obj, dict):
            trimmed = {}
            for k, v in obj.items():
                # Skip keys that produce massive output
                if k in ("step_results", "forecast_series") and isinstance(v, list) and len(v) > max_list_items:
                    trimmed[k] = f"[{len(v)} entries, showing first {max_list_items}]"
                    continue
                trimmed[k] = _trim(v, depth + 1)
            return trimmed
        if isinstance(obj, list):
            if len(obj) > max_list_items and all(isinstance(x, dict) for x in obj):
                return [_trim(x, depth + 1) for x in obj[:max_list_items]] + [
                    {f"... and {len(obj) - max_list_items} more": ""}
                ]
            return [_trim(x, depth + 1) for x in obj]
        return obj

    return _trim(copy.deepcopy(data))


def _build_adaptive_report(message: str, result: dict, skill_name: str | None = None) -> str:
    """Build a Markdown report that adapts to any response structure.

    Works with any skill/chat response — no hardcoded section templates needed.
    """
    from datetime import datetime
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# HydroMAS 分析报告",
        "",
        f"> **问题**: {message}",
        f"> **时间**: {now_str}",
    ]
    if skill_name:
        lines.append(f"> **分析类型**: {_humanize_key(skill_name)}")
    lines += ["", "---", ""]

    # Extract main data — handle various response wrappers
    data = result
    if isinstance(data, dict):
        # Handle chat path failures — render data from successful tool call or error info
        if data.get("_chat_failed"):
            inner = data.get("result", {})
            if isinstance(inner, dict) and inner.get("status") == "completed" and "data" in inner:
                # Tool call succeeded on retry/with defaults — use its data
                data = inner["data"]
                tool_name = inner.get("tool", "")
                lines.append(f"*分析工具: {_humanize_key(tool_name)}*")
                lines.append("")
            elif isinstance(inner, dict) and "data" in inner:
                data = inner["data"]
            else:
                # Tool call still failed — produce a graceful message
                failed_tool = data.get("_chat_error_tool", "")
                lines.append(f"> 注意：自动分析工具 `{failed_tool}` 未能执行。")
                lines.append(f"> 以下为系统基础信息摘要。")
                lines.append("")
                # Render whatever data we have, excluding internal flags
                data = {k: v for k, v in data.items()
                        if not k.startswith("_chat") and k not in ("status",)}
        # Skill endpoint: {success, data, steps_completed, execution_time}
        elif "data" in data and isinstance(data["data"], dict):
            meta_lines = []
            if "steps_completed" in data:
                meta_lines.append(f"完成步骤: {data['steps_completed']}")
            if "execution_time" in data:
                meta_lines.append(f"耗时: {data['execution_time']:.1f}s")
            if meta_lines:
                lines.append(f"*{' | '.join(meta_lines)}*")
                lines.append("")
            data = data["data"]
        # Gateway/chat: {response: "text", ...}
        elif "response" in data and isinstance(data["response"], str):
            lines.append(data["response"])
            lines += ["", "---", "", "*报告由 HydroMAS 平台自动生成*"]
            return "\n".join(lines)
        # Gateway/skill: {result: {...}}
        elif "result" in data and isinstance(data["result"], dict):
            inner = data["result"]
            if "data" in inner:
                data = inner["data"]
            else:
                data = inner

    if isinstance(data, dict):
        # If skill returned a report_markdown, use it directly
        if "report_markdown" in data and isinstance(data["report_markdown"], str):
            lines.append(data["report_markdown"])
            # Also render other data sections (excluding report_markdown itself)
            other_data = {k: v for k, v in data.items() if k != "report_markdown"}
            if other_data:
                lines.append("")
                lines.append("## 详细数据 Detailed Data")
                lines.append("")
                _render_dict_to_md(other_data, lines, level=3)
        else:
            # Trim oversized nested data (e.g. ODD scan step_results)
            data = _trim_large_data(data)
            _render_dict_to_md(data, lines, level=2)
    elif isinstance(data, str):
        lines.append(data)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _render_dict_to_md(item, lines, level=2)
                lines.append("")
            else:
                lines.append(f"- {item}")

    lines += ["", "---", "", "*报告由 HydroMAS 五层架构平台自动生成*"]
    return "\n".join(lines)


def _auto_detect_charts(result: dict) -> list[str]:
    """Scan result for time-series data and generate charts automatically.

    Looks for dicts containing both 'time' and 'water_level' arrays.
    Returns list of chart file paths.
    """
    charts = []

    def _scan(d: dict, label: str = "HydroMAS"):
        if not isinstance(d, dict):
            return
        if "time" in d and "water_level" in d:
            if isinstance(d["time"], list) and isinstance(d["water_level"], list):
                path = _generate_chart_from_sim(d, label)
                if path:
                    charts.append(path)
                return  # don't recurse into this dict further
        for k, v in d.items():
            if isinstance(v, dict):
                _scan(v, _humanize_key(k))

    # Check common response wrappers
    data = result
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        elif "result" in data and isinstance(data["result"], dict):
            data = data["result"]
            if "data" in data and isinstance(data["data"], dict):
                data = data["data"]
        elif "simulation" in data and isinstance(data["simulation"], dict):
            data = data["simulation"]

    _scan(data)
    return charts


def cmd_report(args: list[str]):
    """Run HydroMAS analysis + publish Feishu document.

    Architecture:
      1. If tank simulation keywords → use rich /api/report/tank-analysis endpoint
      2. Else dynamically match skills from /api/gateway/skills trigger phrases
         → call matched skill via /api/gateway/skill
      3. Else fallback to /api/gateway/chat (orchestrator auto-routes)
      4. Build adaptive markdown from whatever response structure comes back
      5. Auto-detect time-series data for chart generation
      6. Publish to Feishu doc
    """
    if not args:
        print("Usage: hydromas_call.py report \"自然语言问题\" [--role ...] [--folder TOKEN] [--user-openid ID]")
        sys.exit(1)

    message = args[0]
    folder_token = None
    user_openid = None
    i = 1
    while i < len(args):
        if args[i] == "--folder" and i + 1 < len(args):
            folder_token = args[i + 1]; i += 2
        elif args[i] == "--user-openid" and i + 1 < len(args):
            user_openid = args[i + 1]; i += 2
        else:
            i += 1

    user_openids = [user_openid] if user_openid else None

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    skill_name = None

    # ── Route 1: Tank simulation (uses dedicated rich endpoint) ──
    if _is_simulation_request(message):
        parsed = _parse_sim_params(message)
        api_payload: dict = {"title": message}
        if "initial_h" in parsed:
            api_payload["initial_h"] = parsed["initial_h"]
        if "duration" in parsed:
            api_payload["duration"] = parsed["duration"]
        if "dt" in parsed:
            api_payload["dt"] = parsed["dt"]
        if "tank_params" in parsed:
            api_payload["tank_params"] = parsed["tank_params"]
        if "q_in_profile" in parsed:
            api_payload["q_in_profile"] = parsed["q_in_profile"]

        result = _post("/api/report/tank-analysis", api_payload)
        if "error" not in result:
            # Tank sim: use existing rich report format
            md_text = _build_analysis_markdown(result)
            params = result.get("parameters", {})
            sim = result.get("simulation", {})
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_schem = pool.submit(_generate_tank_schematic, params)
                f_chart = pool.submit(_generate_chart_from_sim, sim, message)
                schematic_path = f_schem.result()
                chart_path = f_chart.result()

            title = f"HydroMAS — {message} ({now})"
            images = [
                img for img in [
                    {"path": schematic_path, "after_section": "系统概念图"},
                    {"path": chart_path, "after_section": "过程线图"},
                ] if img["path"]
            ]
            try:
                doc_url, doc_tok, written = _publish_report_to_feishu(
                    title, md_text, images, folder_token, user_openids)
                _record_report(user_openid or "", doc_tok, doc_url, title, "simulation")
                analysis = result.get("analysis", {})
                print(f"飞书文档: {doc_url}")
                print(f"摘要: 水位 {analysis.get('initial_h', 0):.2f}m→{analysis.get('final_h', 0):.2f}m "
                      f"(Δ{analysis.get('h_change', 0):+.2f}m)，{analysis.get('response_type', '')}")
            except Exception as e:
                print(f"飞书文档创建失败: {e}")
                print(f"\n{md_text}")
                sys.exit(1)
            return

    # ── Route 2: Dynamic skill matching ──
    skill_name = _find_matching_skill(message)
    if skill_name:
        params = _get_skill_defaults(skill_name)
        result = _post("/api/gateway/skill", {
            "skill_name": skill_name,
            "params": params,
            "role": "operator",
        })
        # Check both top-level error and nested result.success
        if "error" in result:
            skill_name = None
        else:
            inner = result.get("result", {})
            if isinstance(inner, dict) and inner.get("success") is False:
                skill_name = None  # skill execution failed

    # ── Route 3: Fallback to gateway/chat ──
    if not skill_name:
        msg_lower = message.lower()
        role = "operator"
        if any(k in msg_lower for k in ["仿真", "模拟", "分析", "数据", "wnal"]):
            role = "researcher"
        elif any(k in msg_lower for k in ["控制", "优化", "设计", "pid", "mpc"]):
            role = "designer"
        result = _post("/api/gateway/chat", {
            "message": message, "role": role, "session_id": "",
            "user_id": user_openid or "", "params": {},
        })

        # Check for chat path tool execution failures
        chat_inner = result.get("result", {})
        if isinstance(chat_inner, dict) and chat_inner.get("status") == "failed":
            failed_tool = chat_inner.get("tool", "unknown")
            failed_error = chat_inner.get("error", "")
            _log(f"Chat tool '{failed_tool}' failed: {failed_error[:100]}")
            # Wrap the error so we still produce a meaningful report
            result["_chat_failed"] = True
            result["_chat_error_tool"] = failed_tool
            result["_chat_error_msg"] = failed_error

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    # ── Build adaptive report ──
    md_text = _build_adaptive_report(message, result, skill_name)

    # ── Auto-detect and generate charts ──
    chart_paths = _auto_detect_charts(result)
    images = [{"path": p, "after_section": ""} for p in chart_paths if p]

    title = f"HydroMAS — {message} ({now})"

    try:
        if images:
            doc_url, doc_tok, written = _publish_report_to_feishu(
                title, md_text, images, folder_token, user_openids)
        else:
            doc_url, doc_tok, written = _publish_to_feishu(
                title, md_text, chart_path=None, folder_token=folder_token,
                user_openids=user_openids)

        _record_report(user_openid or "", doc_tok, doc_url, title,
                       skill_name or "chat")

        # Build concise summary from result
        summary_parts = []
        data = result.get("data", result.get("result", {}))
        if isinstance(data, dict):
            if "summary" in data:
                summary_parts.append(str(data["summary"])[:100])
            elif "warning_level" in data:
                summary_parts.append(f"预警等级: {data['warning_level']}")
            elif "controller_type" in data:
                summary_parts.append(f"控制器: {data['controller_type']}")
        if isinstance(result.get("response"), str):
            summary_parts.append(result["response"][:100])
        if skill_name:
            summary_parts.insert(0, f"[{_humanize_key(skill_name)}]")

        print(f"飞书文档: {doc_url}")
        print(f"摘要: {' | '.join(summary_parts) if summary_parts else '分析完成'}")

    except Exception as e:
        print(f"飞书文档创建失败: {e}")
        print(f"\n{md_text}")
        sys.exit(1)


REPORT_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
    "hydromas", "data", "report_history.jsonl"
)
# Normalize path
REPORT_HISTORY_PATH = os.path.normpath(
    os.environ.get("HYDROMAS_REPORT_HISTORY",
                    "/home/admin/hydromas/data/report_history.jsonl")
)


def _record_report(user_id: str, doc_token: str, doc_url: str,
                   title: str, skill: str):
    """Append a report record to the JSONL history file."""
    from datetime import datetime
    record = {
        "user_id": user_id or DEFAULT_USER_OPENID,
        "doc_token": doc_token,
        "doc_url": doc_url,
        "title": title,
        "skill": skill or "chat",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    os.makedirs(os.path.dirname(REPORT_HISTORY_PATH), exist_ok=True)
    with open(REPORT_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_report_history(user_id: str | None = None,
                         limit: int = 20) -> list[dict]:
    """Load report history from JSONL, optionally filtered by user_id."""
    if not os.path.exists(REPORT_HISTORY_PATH):
        return []
    records = []
    with open(REPORT_HISTORY_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if user_id and rec.get("user_id") != user_id:
                continue
            records.append(rec)
    records.reverse()  # newest first
    return records[:limit]


def cmd_history(args: list[str]):
    """Show report history."""
    user_id = None
    limit = 20
    i = 0
    while i < len(args):
        if args[i] == "--user-openid" and i + 1 < len(args):
            user_id = args[i + 1]; i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    records = _load_report_history(user_id, limit)
    if not records:
        print("无报告记录。")
        return

    print(f"## 报告历史 (共 {len(records)} 条)\n")
    print("| # | 时间 | 分析类型 | 标题 | 链接 |")
    print("|---|------|---------|------|------|")
    for idx, rec in enumerate(records, 1):
        t = rec.get("created_at", "")[:16]
        skill = rec.get("skill", "")
        title = rec.get("title", "")[:30]
        url = rec.get("doc_url", "")
        print(f"| {idx} | {t} | {skill} | {title} | [查看]({url}) |")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "chat": cmd_chat,
        "report": cmd_report,
        "sim": cmd_sim,
        "skill": cmd_skill,
        "skills": cmd_skills,
        "health": cmd_health,
        "roles": cmd_roles,
        "history": cmd_history,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
