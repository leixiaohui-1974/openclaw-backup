#!/usr/bin/env python3
"""HydroMAS CLI — OpenClaw 技能调用脚本。

用法:
    python3 hydromas_call.py chat "自然语言问题" [--role operator|researcher|designer]
    python3 hydromas_call.py report "自然语言问题" [--role ...] [--folder TOKEN]
    python3 hydromas_call.py skill <技能名> ['{"param":"value"}']
    python3 hydromas_call.py sim [duration] [--initial_h 0.5] [--title "..."]
    python3 hydromas_call.py skills [--role operator]
    python3 hydromas_call.py health
    python3 hydromas_call.py roles

report 命令 = chat + 自动生成飞书文档（含表格+图表），返回文档链接。
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time as _time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
TIMEOUT = 120
CHART_DIR = "/tmp/hydromas-charts"

# ── Feishu config ──
FEISHU_BASE = "https://open.feishu.cn/open-apis"
FEISHU_APP_ID = "cli_a915cc56d5f89cb1"
FEISHU_APP_SECRET = "t4fBWSGN56TEzZrNXvvYTbYWOMlZFjxR"
FEISHU_USER_OPENID = "ou_607e1555930b5636c8b88b176b9d3bf2"
FEISHU_DOC_DOMAIN = "leixiaohui1974.feishu.cn"

# Feishu block types
BT_TEXT, BT_H2, BT_H3, BT_H4 = 2, 4, 5, 6
BT_BULLET, BT_ORDERED, BT_CODE = 12, 13, 14
BT_QUOTE, BT_DIVIDER, BT_IMAGE = 15, 22, 27


def _post(path: str, data: dict) -> dict:
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
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
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
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
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
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
    """Get Feishu tenant_access_token."""
    import requests
    r = requests.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Feishu auth failed: {d}")
    return d["tenant_access_token"]


def _feishu_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _feishu_create_doc(token, title, folder_token=None):
    """Create a new Feishu document. Returns doc_token."""
    import requests
    body = {"title": title}
    if folder_token:
        body["folder_token"] = folder_token
    r = requests.post(f"{FEISHU_BASE}/docx/v1/documents",
                      headers=_feishu_headers(token), json=body)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Create doc failed: {d}")
    return d["data"]["document"]["document_id"]


def _feishu_create_blocks(token, doc_token, parent_id, blocks, index=-1):
    """Create child blocks in a Feishu doc."""
    import requests
    body = {"children": blocks}
    if index >= 0:
        body["index"] = index
    r = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{parent_id}/children",
        headers=_feishu_headers(token), json=body)
    d = r.json()
    if d.get("code") != 0:
        return None, d
    return d["data"]["children"], None


def _feishu_upload_image(token, parent_block_id, image_path):
    """Upload image to Feishu. Returns file_token."""
    import requests
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{FEISHU_BASE}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
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
    import requests
    r = requests.patch(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{block_id}",
        headers=_feishu_headers(token),
        json={"replace_image": {"token": file_token}})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Patch image failed: {d}")


def _feishu_grant(token, doc_token, openid, perm="full_access"):
    """Grant permission on a document."""
    import requests
    r = requests.post(
        f"{FEISHU_BASE}/drive/v1/permissions/{doc_token}/members?type=docx",
        headers=_feishu_headers(token),
        json={"member_type": "openid", "member_id": openid, "perm": perm})
    return r.json().get("code") == 0


def _text_elements(text):
    """Parse inline Markdown (bold, links) into Feishu text elements."""
    import re
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
            m = __import__("re").match(r'\[([^\]]+)\]\(([^)]+)\)', p)
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
    import re
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
        # Table → bold header + text rows
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
                blocks.append({"block_type": BT_TEXT, "text": {"elements": [
                    {"text_run": {"content": " │ ".join(rows[0]), "text_element_style": {"bold": True}}}
                ]}})
                for row in rows[1:]:
                    blocks.append({"block_type": BT_TEXT, "text": {
                        "elements": _text_elements(" │ ".join(row))
                    }})
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


def _publish_to_feishu(title, md_text, chart_path=None, folder_token=None):
    """Create a Feishu doc, write content, insert chart, grant access. Returns doc URL."""
    import time

    token = _feishu_token()

    # 1. Create doc
    doc_token = _feishu_create_doc(token, title, folder_token)

    # 2. Write blocks
    blocks = _md_to_feishu_blocks(md_text)
    batch_size = 20
    written = 0
    for start in range(0, len(blocks), batch_size):
        batch = blocks[start:start + batch_size]
        created, err = _feishu_create_blocks(token, doc_token, doc_token, batch)
        if err:
            for b in batch:
                c, e = _feishu_create_blocks(token, doc_token, doc_token, [b])
                if c:
                    written += 1
        else:
            written += len(created)
        time.sleep(0.3)

    # 3. Insert chart image
    if chart_path and os.path.exists(chart_path):
        time.sleep(0.5)
        # Get current blocks to find last one
        import requests
        r = requests.get(
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

    # 4. Grant access
    _feishu_grant(token, doc_token, FEISHU_USER_OPENID)

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


def _publish_report_to_feishu(title, md_text, images, folder_token=None):
    """Create Feishu doc with content and multiple images. Returns (url, doc_token, written)."""
    import time as tm

    token = _feishu_token()
    doc_token = _feishu_create_doc(token, title, folder_token)

    blocks = _md_to_feishu_blocks(md_text)
    batch_size = 20
    written = 0
    for start in range(0, len(blocks), batch_size):
        batch = blocks[start:start + batch_size]
        created, err = _feishu_create_blocks(token, doc_token, doc_token, batch)
        if err:
            for b in batch:
                c, e = _feishu_create_blocks(token, doc_token, doc_token, [b])
                if c:
                    written += 1
        else:
            written += len(created)
        tm.sleep(0.3)

    # Insert images at section markers
    import requests
    for img_info in images:
        img_path = img_info["path"]
        section_keyword = img_info["after_section"]
        if not os.path.exists(img_path):
            continue

        tm.sleep(0.5)
        # Get current blocks
        r = requests.get(
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

    # Grant access
    _feishu_grant(token, doc_token, FEISHU_USER_OPENID)

    doc_url = f"https://{FEISHU_DOC_DOMAIN}/docx/{doc_token}"
    return doc_url, doc_token, written


def cmd_report(args: list[str]):
    """Run comprehensive HydroMAS analysis + publish rich Feishu document."""
    if not args:
        print("Usage: hydromas_call.py report \"自然语言问题\" [--role ...] [--folder TOKEN]")
        sys.exit(1)

    message = args[0]
    folder_token = None
    i = 1
    while i < len(args):
        if args[i] == "--folder" and i + 1 < len(args):
            folder_token = args[i + 1]; i += 2
        else:
            i += 1

    # Step 1: Call comprehensive analysis API
    result = _post("/api/report/tank-analysis", {
        "title": message,
    })
    if "error" in result:
        # Fallback to chat
        result = _post("/api/gateway/chat", {
            "message": message, "role": "researcher", "session_id": "", "params": {},
        })
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)
        # Simple fallback output
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Step 2: Generate schematic diagram
    params = result.get("parameters", {})
    schematic_path = _generate_tank_schematic(params)

    # Step 3: Generate process chart
    sim = result.get("simulation", {})
    chart_path = _generate_chart_from_sim(sim, message)

    # Step 4: Build comprehensive markdown
    md_text = _build_analysis_markdown(result)

    # Step 5: Publish to Feishu
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"HydroMAS — {message} ({now})"

    images = [
        {"path": schematic_path, "after_section": "系统概念图"},
        {"path": chart_path, "after_section": "过程线图"},
    ]

    try:
        doc_url, doc_token_val, written = _publish_report_to_feishu(
            title, md_text, images, folder_token)

        print(f"## HydroMAS 分析报告已生成\n")
        print(f"**飞书文档**: {doc_url}")
        print(f"**文档标题**: {title}")
        print(f"**内容块数**: {written}")
        print(f"**概念图**: {schematic_path}")
        print(f"**过程线图**: {chart_path}")
        print(f"\n---\n")

        # Print key findings summary for agent
        analysis = result.get("analysis", {})
        odd = result.get("odd_check", {})
        print(f"**响应类型**: {analysis.get('response_type', '?')}")
        print(f"**水位**: {analysis.get('initial_h', 0):.4f}m → {analysis.get('final_h', 0):.4f}m (Δ{analysis.get('h_change', 0):+.4f}m)")
        print(f"**ODD状态**: {odd.get('status', '?')}")
        if result.get("insights"):
            print(f"\n**关键发现**:")
            for ins in result["insights"][:3]:
                print(f"  - {ins}")
        if result.get("recommendations"):
            print(f"\n**工程建议**:")
            for rec in result["recommendations"]:
                print(f"  - {rec}")

    except Exception as e:
        print(f"飞书文档创建失败: {e}")
        print(f"\n以下是分析结果（文本）:\n")
        print(md_text)
        sys.exit(1)


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
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
