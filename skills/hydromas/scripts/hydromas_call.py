#!/usr/bin/env python3
"""HydroMAS CLI — OpenClaw 技能调用脚本。

用法:
    python3 hydromas_call.py chat "自然语言问题" [--role operator|researcher|designer]
    python3 hydromas_call.py report "自然语言问题" [--role ...] [--folder TOKEN] [--user-openid ID]
    python3 hydromas_call.py skill <技能名> ['{"param":"value"}']
    python3 hydromas_call.py sim [duration] [--initial_h 0.5] [--title "..."]
    python3 hydromas_call.py api <skill_name> ['{"param":"value"}']
    python3 hydromas_call.py api list
    python3 hydromas_call.py skills [--role operator]
    python3 hydromas_call.py health
    python3 hydromas_call.py roles
    python3 hydromas_call.py history [--user-openid ID] [--limit N]
    python3 hydromas_call.py evolve [status|run|solidify|daemon-start|daemon-stop]

report 命令 = chat + 自动生成飞书文档（含表格+图表），返回文档链接。
api 命令 = 直接调用任意 HydroMAS API 端点，所有参数均有默认值。
evolve 命令 = EvoMap GEP演化管理，支持单次运行/状态查看/固化/守护进程。
--user-openid: 指定请求用户的飞书 open_id，文档将授权给该用户 + 管理员。

角色/案例/参数语法（chat/report 命令支持）:
    @运维/@科研/@设计  — 角色前缀
    #水箱/#氧化铝/#水网  — 案例标签
    初始水位1.0米, kp=3.0 — 参数覆盖
    帮助/查看参数/重置参数 — 元命令
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import time as _time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from typing import Any

# Ensure sibling modules (llm_client.py) are importable
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import requests as _req
try:
    from tank_pid import (
        DisturbanceConfig,
        DualTankConfig,
        MeasurementNoiseConfig,
        PIDGains,
        ParameterUncertaintyConfig,
        SimulationConfig,
        build_pid_report_markdown,
        generate_pid_report_artifacts,
        simulate_dual_tank_pid,
    )
    _TANK_PID_IMPORT_ERROR = None
except Exception as _tank_pid_exc:
    DisturbanceConfig = DualTankConfig = PIDGains = SimulationConfig = None
    MeasurementNoiseConfig = ParameterUncertaintyConfig = None
    build_pid_report_markdown = generate_pid_report_artifacts = None
    simulate_dual_tank_pid = None
    _TANK_PID_IMPORT_ERROR = _tank_pid_exc

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
except Exception:
    _plt = None

BASE_URL = "http://localhost:8000"
TIMEOUT = 180  # bumped from 120 for large sims
CHART_DIR = "/tmp/hydromas-charts"
SESSION_DIR = "/home/admin/hydromas/data/sessions"
HYDROMAS_API_KEY = os.environ.get("HYDROMAS_API_KEY", "")

# ── Feishu config (credentials from env vars) ──
FEISHU_BASE = "https://open.feishu.cn/open-apis"
FEISHU_APP_ID = ""
FEISHU_APP_SECRET = ""
DEFAULT_USER_OPENID = ""
FEISHU_DOC_DOMAIN = "docs.feishu.cn"
_FEISHU_CONFIG_SOURCE: dict[str, str] = {}

# Feishu block types
BT_TEXT, BT_H2, BT_H3, BT_H4 = 2, 4, 5, 6
BT_BULLET, BT_ORDERED, BT_CODE = 12, 13, 14
BT_QUOTE, BT_DIVIDER, BT_IMAGE = 15, 22, 27
BT_TABLE, BT_TABLE_CELL = 31, 32

# ── Feishu token cache & session pool ──
_feishu_token_cache: dict = {"token": None, "expires": 0}
_feishu_session: _req.Session | None = None


def _read_simple_env_file(path: pathlib.Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from a .env-like file."""
    out: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return out
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            out[key] = value.strip().strip('"').strip("'")
    except Exception:
        return out
    return out


def _read_agents_markdown_credentials(path: pathlib.Path) -> dict[str, str]:
    """Safely parse FEISHU_* assignments from AGENTS.md key lines."""
    out: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return out
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return out
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_DEFAULT_OPENID", "FEISHU_DOC_DOMAIN"):
        value = _extract_agents_key_value(lines, key)
        if value:
            out[key] = value
    return out


def _extract_agents_key_value(lines: list[str], key: str) -> str:
    """Extract a single KEY[:=]VALUE assignment from AGENTS.md lines."""
    pat = re.compile(
        rf"^\s*(?:[-*]\s*)?(?:`)?{re.escape(key)}(?:`)?\s*[:=]\s*(.+?)\s*$"
    )
    for raw in lines:
        m = pat.match(raw)
        if not m:
            continue
        value = m.group(1).strip()
        if not value:
            continue
        # Trim inline comments; AGENTS entries are expected as single-line key/value.
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ) or (value.startswith("`") and value.endswith("`")):
            value = value[1:-1].strip()
        value = value.rstrip(",;")
        if value:
            return value
    return ""


def _is_local_cli_execution() -> bool:
    """Treat direct CLI execution as local mode for config fallback."""
    return __name__ == "__main__"


def _read_openclaw_json_credentials(path: pathlib.Path) -> dict[str, str]:
    """Read Feishu credentials from ~/.openclaw/openclaw.json when available."""
    out: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return out
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return out

    if not isinstance(data, dict):
        return out

    channels = data.get("channels")
    if not isinstance(channels, dict):
        return out
    feishu = channels.get("feishu")
    if not isinstance(feishu, dict):
        return out
    accounts = feishu.get("accounts")
    if not isinstance(accounts, dict):
        return out

    # Prefer the default account, then any other account.
    candidates: list[dict[str, Any]] = []
    default_acc = accounts.get("default")
    if isinstance(default_acc, dict):
        candidates.append(default_acc)
    for name, acc in accounts.items():
        if name == "default":
            continue
        if isinstance(acc, dict):
            candidates.append(acc)

    for acc in candidates:
        app_id = str(acc.get("appId", "") or "").strip()
        app_secret = str(acc.get("appSecret", "") or "").strip()
        if app_id and "FEISHU_APP_ID" not in out:
            out["FEISHU_APP_ID"] = app_id
        if app_secret and "FEISHU_APP_SECRET" not in out:
            out["FEISHU_APP_SECRET"] = app_secret
        if "FEISHU_APP_ID" in out and "FEISHU_APP_SECRET" in out:
            break
    return out


def _candidate_agents_paths(cwd: pathlib.Path, script_dir: pathlib.Path) -> list[pathlib.Path]:
    """Build a deduplicated AGENTS.md search list near workspace/script roots."""
    candidates: list[pathlib.Path] = []
    candidates.append(cwd / "AGENTS.md")
    candidates.append(script_dir / "AGENTS.md")
    for parent in script_dir.parents:
        candidates.append(parent / "AGENTS.md")
    for parent in cwd.parents:
        candidates.append(parent / "AGENTS.md")
    out: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _load_feishu_config() -> tuple[dict[str, str], dict[str, str]]:
    """Load Feishu config from env, with local-mode-only fallback files."""
    keys = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_DEFAULT_OPENID", "FEISHU_DOC_DOMAIN")
    values: dict[str, str] = {k: os.environ.get(k, "") for k in keys}
    sources: dict[str, str] = {k: ("env" if values[k] else "") for k in keys}

    script_dir = pathlib.Path(_SCRIPT_DIR)
    cwd = pathlib.Path.cwd()

    if _is_local_cli_execution():
        search_paths: list[pathlib.Path] = []
        for base in (cwd, script_dir, script_dir.parent):
            search_paths.extend([base / ".env", base / ".env.local"])
        dedup_paths: list[pathlib.Path] = []
        seen: set[pathlib.Path] = set()
        for p in search_paths:
            if p not in seen:
                seen.add(p)
                dedup_paths.append(p)

        for env_path in dedup_paths:
            vals = _read_simple_env_file(env_path)
            for key in keys:
                if not values[key] and vals.get(key):
                    values[key] = vals[key]
                    sources[key] = "config"

        openclaw_cfg = pathlib.Path.home() / ".openclaw" / "openclaw.json"
        cfg_vals = _read_openclaw_json_credentials(openclaw_cfg)
        for key in keys:
            if not values[key] and cfg_vals.get(key):
                values[key] = cfg_vals[key]
                sources[key] = "config"

        for ag_path in _candidate_agents_paths(cwd, script_dir):
            vals = _read_agents_markdown_credentials(ag_path)
            for key in keys:
                if not values[key] and vals.get(key):
                    values[key] = vals[key]
                    sources[key] = "AGENTS.md"

    if not values["FEISHU_DOC_DOMAIN"]:
        values["FEISHU_DOC_DOMAIN"] = "docs.feishu.cn"
        sources["FEISHU_DOC_DOMAIN"] = "default"
    # open.feishu.cn is API host, not human-facing doc host.
    # Rewrite to docs.feishu.cn unless user explicitly configured another doc domain.
    if values["FEISHU_DOC_DOMAIN"].strip().lower() == "open.feishu.cn":
        values["FEISHU_DOC_DOMAIN"] = "docs.feishu.cn"
        if not sources["FEISHU_DOC_DOMAIN"]:
            sources["FEISHU_DOC_DOMAIN"] = "rewrite"

    return values, sources


def _init_feishu_config() -> None:
    global FEISHU_APP_ID, FEISHU_APP_SECRET, DEFAULT_USER_OPENID, FEISHU_DOC_DOMAIN, _FEISHU_CONFIG_SOURCE
    vals, src = _load_feishu_config()
    FEISHU_APP_ID = vals["FEISHU_APP_ID"]
    FEISHU_APP_SECRET = vals["FEISHU_APP_SECRET"]
    DEFAULT_USER_OPENID = vals["FEISHU_DEFAULT_OPENID"]
    FEISHU_DOC_DOMAIN = vals["FEISHU_DOC_DOMAIN"]
    _FEISHU_CONFIG_SOURCE = src


def _print_feishu_credential_status(context: str) -> bool:
    """Print explicit Feishu credential status before report execution."""
    app_id_ok = bool(FEISHU_APP_ID.strip())
    app_secret_ok = bool(FEISHU_APP_SECRET.strip())
    cred_sources = {
        _FEISHU_CONFIG_SOURCE.get("FEISHU_APP_ID") or "none",
        _FEISHU_CONFIG_SOURCE.get("FEISHU_APP_SECRET") or "none",
    }
    cred_source = cred_sources.pop() if len(cred_sources) == 1 else "mixed"
    print(f"[startup:{context}] Feishu credential status:", file=sys.stderr)
    print(f"[startup:{context}] Feishu credential source: {cred_source}", file=sys.stderr)
    print(
        f"  - FEISHU_APP_ID: {'OK' if app_id_ok else 'MISSING'} "
        f"(source={_FEISHU_CONFIG_SOURCE.get('FEISHU_APP_ID') or 'none'})",
        file=sys.stderr,
    )
    print(
        f"  - FEISHU_APP_SECRET: {'OK' if app_secret_ok else 'MISSING'} "
        f"(source={_FEISHU_CONFIG_SOURCE.get('FEISHU_APP_SECRET') or 'none'})",
        file=sys.stderr,
    )
    print(
        f"  - FEISHU_DEFAULT_OPENID: {'SET' if DEFAULT_USER_OPENID.strip() else 'EMPTY'} "
        f"(source={_FEISHU_CONFIG_SOURCE.get('FEISHU_DEFAULT_OPENID') or 'none'})",
        file=sys.stderr,
    )
    return app_id_ok and app_secret_ok


_init_feishu_config()


def _extract_user_openid_from_args(args: list[str]) -> str:
    """Extract --user-openid value from CLI args when present."""
    i = 0
    while i < len(args):
        if args[i] == "--user-openid" and i + 1 < len(args):
            return (args[i + 1] or "").strip()
        i += 1
    return ""


def _resolve_notify_target_openid(cli_args: list[str]) -> str:
    """Resolve Feishu open_id for direct notification."""
    candidates = [
        _extract_user_openid_from_args(cli_args),
        os.environ.get("OPENCLAW_TRIGGER_USER_OPENID", ""),
        os.environ.get("OPENCLAW_USER_OPENID", ""),
        os.environ.get("OPENCLAW_SENDER_ID", ""),
        os.environ.get("FEISHU_USER_OPENID", ""),
        DEFAULT_USER_OPENID,
    ]
    for c in candidates:
        c = (c or "").strip()
        if c:
            return c
    return ""


def notify_feishu(status: str, summary: str, duration_sec: float | None = None,
                  user_openid: str | None = None) -> None:
    """Send Feishu DM via OpenClaw message interface; fallback to system event."""
    payload = {
        "status": (status or "unknown").strip() or "unknown",
        "summary": (summary or "HydroMAS task finished.").strip(),
    }
    if duration_sec is not None:
        payload["duration"] = round(max(0.0, float(duration_sec)), 3)
    text = json.dumps(payload, ensure_ascii=False)
    target = (user_openid or "").strip()
    try:
        if target:
            sent = subprocess.run(
                [
                    "openclaw", "message", "send",
                    "--channel", "feishu",
                    "--target", target,
                    "--message", text,
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if sent.returncode == 0:
                return
        subprocess.run(
            ["openclaw", "system", "event", "--text", text, "--mode", "now"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(f"[notify_feishu] failed: {exc}", file=sys.stderr)


def _send_feishu_dm_text(text: str, user_openid: str | None = None) -> bool:
    """Send plain Feishu DM text via OpenClaw message interface."""
    target = (user_openid or "").strip()
    if not target:
        return False
    try:
        sent = subprocess.run(
            [
                "openclaw", "message", "send",
                "--channel", "feishu",
                "--target", target,
                "--message", text,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return sent.returncode == 0
    except Exception as exc:
        print(f"[feishu_dm] failed: {exc}", file=sys.stderr)
        return False


def _notify_report_ready(doc_url: str, summary: str, user_openid: str | None = None) -> None:
    """Push a human-friendly report message to Feishu DM."""
    target = (user_openid or "").strip()
    if not target or not doc_url:
        return
    token = doc_url.rstrip("/").split("/")[-1] if "/" in doc_url else ""
    backups = _doc_url_candidates(token)[1:]
    msg = "HydroMAS 报告已生成\n" f"链接: {doc_url}\n"
    if backups:
        msg += f"备用: {backups[0]}\n"
    msg += f"摘要: {summary}"
    ok = _send_feishu_dm_text(msg, target)
    if not ok:
        print(f"[feishu_dm] report notify failed target={target}", file=sys.stderr)


def _get_feishu_session() -> _req.Session:
    """Return a reusable requests.Session (TCP connection pooling)."""
    global _feishu_session
    if _feishu_session is None:
        _feishu_session = _req.Session()
        _feishu_session.headers.update({"Content-Type": "application/json"})
    return _feishu_session


def _validate_feishu_credentials():
    """Ensure required Feishu credentials are present."""
    missing = []
    if not FEISHU_APP_ID.strip():
        missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET.strip():
        missing.append("FEISHU_APP_SECRET")
    if missing:
        raise RuntimeError(
            "Missing Feishu credentials: "
            + ", ".join(missing)
            + ". Configure env vars or provide them via .env / AGENTS.md before using report/full-report."
        )


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
    cli_role = None
    user_openid = None

    i = 1
    while i < len(args):
        if args[i] == "--role" and i + 1 < len(args):
            cli_role = args[i + 1]; i += 2
        elif args[i] == "--user-openid" and i + 1 < len(args):
            user_openid = args[i + 1]; i += 2
        else:
            i += 1

    # Resolve context (role, case, cleaned message, merged params, session)
    role, case_id, cleaned_msg, merged_params, session = _resolve_context(
        message, user_openid, cli_role)

    # Check meta commands first
    meta_response = _handle_meta_command(cleaned_msg, session)
    if meta_response is not None:
        print(meta_response)
        return

    case_name = CASE_PROFILES.get(case_id, {}).get("name", case_id)

    # Try LLM intent classification → if skill matched, call skill endpoint
    skill_name = _find_matching_skill(cleaned_msg)
    if skill_name is None:
        llm_result = _llm_classify_intent(cleaned_msg, role, case_id)
        if llm_result and llm_result.get("skill_name"):
            skill_name = llm_result["skill_name"]
            print(f"[LLM] 意图识别: {skill_name} "
                  f"(置信度: {llm_result.get('confidence', '?')})",
                  file=sys.stderr)

    if skill_name:
        # Route to skill endpoint for better results
        skill_defaults = _get_skill_defaults(skill_name, case_id)
        skill_params = {}
        _deep_merge(skill_params, skill_defaults)
        _deep_merge(skill_params, merged_params)
        result = _post("/api/gateway/skill", {
            "skill_name": skill_name,
            "params": skill_params,
            "role": role,
        })
        if "error" in result:
            # Skill failed, fallback to chat
            skill_name = None

    if not skill_name:
        result = _post("/api/gateway/chat", {
            "message": cleaned_msg,
            "role": role,
            "session_id": "",
            "params": {
                "case_id": case_id,
                "case_name": case_name,
                "param_overrides": merged_params,
            },
        })

    # Save session
    _save_session(session)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"## HydroMAS ({role} | {case_name})\n")
    if skill_name:
        print(f"*[技能: {skill_name}]*\n")
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
    """Get Feishu tenant_access_token (cached, with retry/backoff)."""
    _validate_feishu_credentials()
    now = _time.time()
    # Use 5-min buffer before expiry to avoid mid-operation expiration
    if _feishu_token_cache["token"] and now < _feishu_token_cache["expires"] - 300:
        return _feishu_token_cache["token"]
    s = _get_feishu_session()
    last_err = None
    for attempt in range(3):
        try:
            r = s.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
                       json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
                       timeout=15)
            d = r.json()
            if d.get("code") == 0:
                _feishu_token_cache["token"] = d["tenant_access_token"]
                _feishu_token_cache["expires"] = now + d.get("expire", 7200)
                return d["tenant_access_token"]
            last_err = f"code={d.get('code')}: {d.get('msg')}"
        except Exception as e:
            last_err = str(e)
        if attempt < 2:
            _time.sleep((attempt + 1) * 2)
    raise RuntimeError(f"Feishu auth failed after 3 attempts: {last_err}")


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


def _doc_url_candidates(doc_token: str) -> list[str]:
    """Build multiple doc URL forms to avoid tenant/domain mismatch issues."""
    token = (doc_token or "").strip()
    if not token:
        return []
    urls: list[str] = []
    for host in ("feishu.cn", "docs.feishu.cn", FEISHU_DOC_DOMAIN):
        host = (host or "").strip().lower()
        if not host:
            continue
        u = f"https://{host}/docx/{token}"
        if u not in urls:
            urls.append(u)
    return urls


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
    """Grant permission on a document.

    Returns:
        (ok, detail): ok indicates API-level success, detail carries msg/code.
    """
    s = _get_feishu_session()
    r = s.post(
        f"{FEISHU_BASE}/drive/v1/permissions/{doc_token}/members?type=docx",
        headers=_feishu_headers(token),
        json={"member_type": "openid", "member_id": openid, "perm": perm})
    d = r.json()
    if d.get("code") == 0:
        return True, "ok"
    return False, f"code={d.get('code')} msg={d.get('msg', '')}"


def _grant_multi_users(token, doc_token, user_openids=None):
    """Grant document access to admin + any extra requesting users."""
    targets: list[tuple[str, str]] = []

    # Always grant to admin when configured
    admin_oid = (DEFAULT_USER_OPENID or "").strip()
    if admin_oid:
        targets.append(("admin", admin_oid))

    # Explicitly grant to user_openids passed from --user-openid, even when admin is empty.
    for oid in (user_openids or []):
        clean = (oid or "").strip()
        if clean and clean != admin_oid:
            targets.append(("request_user", clean))

    if not targets:
        print(f"[feishu_grant] skipped: no openid target for doc={doc_token}", file=sys.stderr)
        return

    for label, oid in targets:
        ok, detail = _feishu_grant(token, doc_token, oid, perm="full_access")
        status = "OK" if ok else "FAILED"
        print(
            f"[feishu_grant] {status} role={label} openid={oid} perm=full_access "
            f"doc={doc_token} detail={detail}",
            file=sys.stderr,
        )


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

    doc_url = _doc_url_candidates(doc_token)[0]
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


def _build_dual_tank_pid_inputs(result: dict, merged_params: dict):
    """Build local dual-tank PID simulation configs from API + user parameters."""
    params = result.get("parameters", {}) if isinstance(result, dict) else {}
    tank_params = params.get("tank_params", {}) if isinstance(params.get("tank_params"), dict) else {}

    area = float(tank_params.get("area", merged_params.get("tank_area", 1.0)))
    out_area = float(tank_params.get("outlet_area", merged_params.get("outlet_area", 0.01)))
    cd = float(tank_params.get("cd", merged_params.get("cd", 0.6)))

    duration = float(params.get("duration_s", merged_params.get("duration", 300.0)))
    dt = float(params.get("dt_s", merged_params.get("dt", 1.0)))
    initial_h = float(params.get("initial_h_m", merged_params.get("initial_h", 0.5)))
    base_inflow = float(params.get("q_in_m3s", merged_params.get("q_in", 0.01)))

    setpoint = float(merged_params.get("setpoint", max(0.2, min(1.6, initial_h + 0.3))))
    kp = float(merged_params.get("kp", 2.0))
    ki = float(merged_params.get("ki", 0.1))
    kd = float(merged_params.get("kd", 0.5))

    disturbance_type = str(merged_params.get("disturbance_type", "outflow")).strip().lower() or "outflow"
    if disturbance_type not in {"inflow", "outflow"}:
        disturbance_type = "outflow"
    disturbance_start = float(merged_params.get("disturbance_start", min(120.0, duration * 0.4)))
    disturbance_end = merged_params.get("disturbance_end")
    disturbance_end_v = float(disturbance_end) if disturbance_end is not None else None
    disturbance_mag = float(merged_params.get("disturbance_magnitude", max(0.001, 0.15 * base_inflow)))

    tank_cfg = DualTankConfig(
        area1=area,
        area2=area,
        c12=max(0.01, cd * out_area * 8.0),
        c2=max(0.01, cd * out_area * 7.0),
        h_min=0.0,
        h_max=float(params.get("h_max_m", 2.0)),
    )
    sim_cfg = SimulationConfig(
        duration_s=duration,
        dt_s=max(0.1, dt),
        initial_h1=max(0.0, initial_h),
        initial_h2=max(0.0, initial_h * 0.9),
        setpoint=setpoint,
        base_inflow=base_inflow,
        inflow_min=0.0,
        inflow_max=max(0.02, base_inflow * 5.0),
    )
    gains = PIDGains(kp=kp, ki=ki, kd=kd)
    disturbance_cfg = DisturbanceConfig(
        kind=disturbance_type,
        start_s=max(0.0, disturbance_start),
        end_s=disturbance_end_v,
        magnitude=disturbance_mag,
    )
    noise_cfg = MeasurementNoiseConfig(
        enabled=bool(merged_params.get("enable_measurement_noise", False)),
        std_h1=float(merged_params.get("noise_std_h1", 0.0)),
        std_h2=float(merged_params.get("noise_std_h2", 0.003)),
        bias_h1=float(merged_params.get("noise_bias_h1", 0.0)),
        bias_h2=float(merged_params.get("noise_bias_h2", 0.0)),
        seed=int(merged_params.get("noise_seed", 42)),
    )
    uncertainty_cfg = ParameterUncertaintyConfig(
        enabled=bool(merged_params.get("enable_param_uncertainty", False)),
        rel_area1=float(merged_params.get("unc_rel_area1", 0.0)),
        rel_area2=float(merged_params.get("unc_rel_area2", 0.0)),
        rel_c12=float(merged_params.get("unc_rel_c12", 0.0)),
        rel_c2=float(merged_params.get("unc_rel_c2", 0.0)),
        seed=int(merged_params.get("unc_seed", 123)),
    )
    optimizer_method = str(merged_params.get("pid_optimizer", "random_refine")).strip() or "random_refine"
    robust_samples = int(merged_params.get("pid_robust_samples", 8))
    return (
        tank_cfg,
        sim_cfg,
        gains,
        disturbance_cfg,
        noise_cfg,
        uncertainty_cfg,
        optimizer_method,
        robust_samples,
    )


def _extract_report_case_count(message: str, merged_params: dict) -> int:
    """Parse requested case count from message/params. Supports 2~20."""
    raw = merged_params.get("report_cases")
    if isinstance(raw, (int, float)):
        n = int(raw)
        return max(2, min(20, n))

    text = (message or "").lower()
    patterns = [
        r"(\d+)\s*(?:个|组)?\s*(?:测试)?案例",
        r"(\d+)\s*cases?",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            n = int(m.group(1))
            return max(2, min(20, n))

    cn_map = {
        "二十": 20,
        "十五": 15,
        "十二": 12,
        "十": 10,
        "五": 5,
    }
    for k, v in cn_map.items():
        if f"{k}个案例" in text or f"{k}案例" in text or f"{k}个测试" in text:
            return v
    return 0


def _plot_case_timeseries(case_name: str, baseline: dict, optimized: dict, out_dir: str) -> str | None:
    if _plt is None:
        return None
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{case_name}_timeseries.png")
    _plt.figure(figsize=(10, 4.6))
    _plt.plot(baseline["time_s"], baseline["h2_m"], label="Baseline h2", linewidth=1.6, alpha=0.9)
    _plt.plot(optimized["time_s"], optimized["h2_m"], label="Optimized h2", linewidth=2.0)
    _plt.plot(optimized["time_s"], optimized["setpoint_m"], "--", label="Setpoint", linewidth=1.4)
    _plt.xlabel("Time (s)")
    _plt.ylabel("Water Level (m)")
    _plt.title(f"{case_name} - Water Level Tracking")
    _plt.grid(alpha=0.25)
    _plt.legend()
    _plt.tight_layout()
    _plt.savefig(path, dpi=150)
    _plt.close()
    return path


def _plot_case_control(case_name: str, baseline: dict, optimized: dict, out_dir: str) -> str | None:
    if _plt is None:
        return None
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{case_name}_control.png")
    _plt.figure(figsize=(10, 4.2))
    _plt.plot(baseline["time_s"], baseline["control_u_m3s"], label="Baseline u", linewidth=1.6, alpha=0.9)
    _plt.plot(optimized["time_s"], optimized["control_u_m3s"], label="Optimized u", linewidth=1.8)
    _plt.xlabel("Time (s)")
    _plt.ylabel("Inflow u (m3/s)")
    _plt.title(f"{case_name} - Control Signal")
    _plt.grid(alpha=0.25)
    _plt.legend()
    _plt.tight_layout()
    _plt.savefig(path, dpi=150)
    _plt.close()
    return path


def _plot_case_error(case_name: str, optimized: dict, out_dir: str) -> str | None:
    if _plt is None:
        return None
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{case_name}_error.png")
    t = optimized["time_s"]
    e = [sp - h for sp, h in zip(optimized["setpoint_m"], optimized["h2_m"])]
    _plt.figure(figsize=(10, 3.8))
    _plt.plot(t, e, linewidth=1.8, color="#b1282b")
    _plt.axhline(0.0, color="#333333", linewidth=0.9)
    _plt.xlabel("Time (s)")
    _plt.ylabel("Tracking Error (m)")
    _plt.title(f"{case_name} - Tracking Error")
    _plt.grid(alpha=0.25)
    _plt.tight_layout()
    _plt.savefig(path, dpi=150)
    _plt.close()
    return path


def _plot_case_disturbance(case_name: str, optimized: dict, out_dir: str) -> str | None:
    if _plt is None:
        return None
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{case_name}_disturbance.png")
    _plt.figure(figsize=(10, 3.4))
    _plt.step(
        optimized["time_s"],
        optimized["disturbance_m3s"],
        where="post",
        linewidth=1.9,
        color="#7c3aed",
    )
    _plt.xlabel("Time (s)")
    _plt.ylabel("Disturbance (m3/s)")
    _plt.title(f"{case_name} - Disturbance Profile ({optimized.get('disturbance_kind', 'outflow')})")
    _plt.grid(alpha=0.25)
    _plt.tight_layout()
    _plt.savefig(path, dpi=150)
    _plt.close()
    return path


def _assess_case_correctness(
    tank_cfg: DualTankConfig,
    sim_case: SimulationConfig,
    sim_base: dict,
    sim_best: dict,
) -> dict:
    """Evaluate numeric plausibility and control correctness for one case."""
    notes: list[str] = []
    status = "PASS"

    h2 = sim_best.get("h2_m", []) or []
    t = sim_best.get("time_s", []) or []
    m_best = sim_best.get("metrics", {}) or {}
    m_base = sim_base.get("metrics", {}) or {}

    if len(h2) < 10 or len(t) != len(h2):
        status = "WARN"
        notes.append("时序长度异常")

    h_lo = min(h2) if h2 else float("nan")
    h_hi = max(h2) if h2 else float("nan")
    if not (math.isfinite(h_lo) and math.isfinite(h_hi)):
        status = "WARN"
        notes.append("水位序列存在非有限值")
    elif h_lo < tank_cfg.h_min - 1e-6 or h_hi > tank_cfg.h_max + 1e-6:
        status = "WARN"
        notes.append(f"水位越界[{h_lo:.3f}, {h_hi:.3f}]")

    for key in ("iae", "overshoot_m", "control_energy"):
        v = float(m_best.get(key, float("nan")))
        if not math.isfinite(v) or v < -1e-12:
            status = "WARN"
            notes.append(f"{key} 非法({v})")

    final_h = float(h2[-1]) if h2 else float("nan")
    err_final = abs(sim_case.setpoint - final_h) if math.isfinite(final_h) else float("inf")
    err_tol = max(0.25, 0.15 * max(sim_case.setpoint, 1e-6))
    if err_final > err_tol:
        status = "WARN"
        notes.append(f"终值误差偏大({err_final:.3f}m>{err_tol:.3f}m)")

    iae_best = float(m_best.get("iae", float("inf")))
    iae_base = float(m_base.get("iae", float("inf")))
    if math.isfinite(iae_best) and math.isfinite(iae_base) and iae_best > iae_base * 1.35:
        status = "WARN"
        notes.append("优化后IAE显著劣化")

    if not notes:
        notes.append("主要物理与控制指标均在合理范围")
    return {"status": status, "notes": notes, "final_error": err_final}


def _build_multi_case_suite(
    case_count: int,
    tank_cfg: DualTankConfig,
    sim_cfg: SimulationConfig,
    seed_gains: PIDGains,
    best_gains: PIDGains,
    disturbance_cfg: DisturbanceConfig,
    noise_cfg: MeasurementNoiseConfig,
    uncertainty_cfg: ParameterUncertaintyConfig
) -> tuple[str, list[dict], list[dict]]:
    """Generate N-case PID test suite markdown + images + case summaries."""
    base_setpoint = float(sim_cfg.setpoint)
    base_mag = max(1e-6, float(disturbance_cfg.magnitude))
    base_start = max(0.0, float(disturbance_cfg.start_s))
    base_duration = max(30.0, float(sim_cfg.duration_s))
    mag_factors = [0.8, 1.0, 1.2, 1.5, 1.8]
    setpoint_offsets = [-0.12, -0.06, 0.0, 0.06, 0.12]
    start_factors = [0.25, 0.35, 0.45, 0.55]

    md_lines = [
        f"## 八、多案例完整验证（{case_count}案例）",
        "",
        "| 案例 | IAE | 超调(m) | 稳定时间(s) | 控制能量 | 最优PID(Kp/Ki/Kd) |",
        "|---|---:|---:|---:|---:|---|",
    ]
    images: list[dict] = []
    case_summaries: list[dict] = []
    pass_count = 0
    warn_count = 0
    run_tag = int(_time.time())

    for idx in range(1, case_count + 1):
        label_cn = f"案例{idx}"
        label_en = f"Case {idx:02d}"
        setpoint = max(
            tank_cfg.h_min + 0.05,
            min(tank_cfg.h_max - 0.05, base_setpoint + setpoint_offsets[(idx - 1) % len(setpoint_offsets)]),
        )
        dist_kind = "inflow" if idx % 4 == 0 else "outflow"
        dist_mag = base_mag * mag_factors[(idx - 1) % len(mag_factors)]
        start_s = max(6.0, base_duration * start_factors[(idx - 1) % len(start_factors)])
        sim_case = SimulationConfig(
            **{
                **sim_cfg.__dict__,
                "setpoint": setpoint,
                "duration_s": max(180.0, base_duration + 20.0 * ((idx - 1) % 3)),
            }
        )
        dist_case = DisturbanceConfig(
            **{
                **disturbance_cfg.__dict__,
                "kind": dist_kind,
                "magnitude": dist_mag,
                "start_s": start_s,
            }
        )
        noise_on = idx > int(case_count * 0.6)
        unc_on = idx > int(case_count * 0.75)
        noise_case = MeasurementNoiseConfig(
            **{
                **noise_cfg.__dict__,
                "enabled": noise_on,
                "std_h2": max(0.002, float(noise_cfg.std_h2 or 0.0) + 0.001 * ((idx - 1) % 3)),
                "seed": int(noise_cfg.seed + idx),
            }
        )
        unc_case = ParameterUncertaintyConfig(
            **{
                **uncertainty_cfg.__dict__,
                "enabled": unc_on,
                "rel_area1": max(0.0, float(uncertainty_cfg.rel_area1 or 0.0) + (0.01 if unc_on else 0.0)),
                "rel_area2": max(0.0, float(uncertainty_cfg.rel_area2 or 0.0) + (0.01 if unc_on else 0.0)),
                "rel_c12": max(0.0, float(uncertainty_cfg.rel_c12 or 0.0) + (0.02 if unc_on else 0.0)),
                "rel_c2": max(0.0, float(uncertainty_cfg.rel_c2 or 0.0) + (0.02 if unc_on else 0.0)),
                "seed": int(uncertainty_cfg.seed + idx),
            }
        )
        case_dir = os.path.join(_REPORT_IMAGE_DIR, f"pid_suite_{run_tag}_case{idx}")
        sim_base = simulate_dual_tank_pid(
            tank=tank_cfg,
            sim=sim_case,
            gains=seed_gains,
            disturbance=dist_case,
            measurement_noise=noise_case,
            parameter_uncertainty=unc_case,
        )
        sim_best = simulate_dual_tank_pid(
            tank=tank_cfg,
            sim=sim_case,
            gains=best_gains,
            disturbance=dist_case,
            measurement_noise=noise_case,
            parameter_uncertainty=unc_case,
        )
        m = sim_best.get("metrics", {})
        settling = m.get("settling_time_s")
        settling_s = f"{settling:.1f}" if isinstance(settling, (int, float)) and math.isfinite(settling) else "N/A"
        assess = _assess_case_correctness(tank_cfg, sim_case, sim_base, sim_best)
        if assess["status"] == "PASS":
            pass_count += 1
        else:
            warn_count += 1

        md_lines.append(
            f"| {label_cn} | {m.get('iae', 0.0):.4f} | {m.get('overshoot_m', 0.0):.4f} | "
            f"{settling_s} | {m.get('control_energy', 0.0):.4f} | "
            f"{best_gains.kp:.3f}/{best_gains.ki:.3f}/{best_gains.kd:.3f} |"
        )

        sec = label_cn
        md_lines += [
            "",
            f"### {sec}",
            f"- 工况: setpoint={setpoint:.2f}m, disturbance={dist_kind}:{dist_mag:.5f}m3/s @ {start_s:.1f}s",
            f"- 噪声/不确定性: noise={noise_on}, uncertainty={unc_on}",
            f"- 最优 PID: Kp={best_gains.kp:.4f}, Ki={best_gains.ki:.4f}, Kd={best_gains.kd:.4f}",
            f"- 基线/优化 IAE: {sim_base['metrics'].get('iae', 0.0):.4f} → {m.get('iae', 0.0):.4f}",
            f"- 计算结果评审: **{assess['status']}**（终值误差={assess['final_error']:.3f}m）",
            f"- 评审依据: {'；'.join(assess['notes'])}",
            "",
            f"#### {sec} 水位过程线",
            "（见下方插图）",
            "",
            f"#### {sec} 控制输入曲线",
            "（见下方插图）",
            "",
            f"#### {sec} 跟踪误差曲线",
            "（见下方插图）",
            "",
            f"#### {sec} 扰动过程线",
            "（见下方插图）",
            "",
        ]

        ts = _plot_case_timeseries(label_en, sim_base, sim_best, case_dir)
        uc = _plot_case_control(label_en, sim_base, sim_best, case_dir)
        er = _plot_case_error(label_en, sim_best, case_dir)
        ds = _plot_case_disturbance(label_en, sim_best, case_dir)
        for path, anchor in [
            (ts, f"{sec} 水位过程线"),
            (uc, f"{sec} 控制输入曲线"),
            (er, f"{sec} 跟踪误差曲线"),
            (ds, f"{sec} 扰动过程线"),
        ]:
            if path:
                images.append({"path": path, "after_section": anchor})

        case_summaries.append(
            {
                "name": sec,
                "status": assess["status"],
                "iae": float(m.get("iae", 0.0)),
                "overshoot": float(m.get("overshoot_m", 0.0)),
                "settling": settling_s,
                "energy": float(m.get("control_energy", 0.0)),
            }
        )

    md_lines += [
        "",
        "### 八.附 计算结果正确性总评",
        f"- 评审结论: PASS={pass_count}，WARN={warn_count}",
        "- 评审维度: 边界约束、指标有限性、终值误差、优化退化检查。",
        "",
    ]

    return "\n".join(md_lines), images, case_summaries


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

    def _list_doc_children_all() -> list[dict]:
        """List all top-level blocks with pagination."""
        items: list[dict] = []
        page_token: str | None = None
        for _ in range(50):
            params = {"page_size": 200}
            if page_token:
                params["page_token"] = page_token
            r = s.get(
                f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
                headers=_feishu_headers(token),
                params=params,
            )
            d = r.json()
            if d.get("code") != 0:
                raise RuntimeError(f"List blocks failed: {d}")
            data = d.get("data", {}) or {}
            items.extend(data.get("items", []) or [])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return items

    def _heading_text(blk: dict) -> str:
        bt = blk.get("block_type", 0)
        field = {4: "heading2", 5: "heading3", 6: "heading4"}.get(bt)
        if not field or field not in blk:
            return ""
        txt = ""
        for el in blk[field].get("elements", []):
            if "text_run" in el:
                txt += el["text_run"].get("content", "")
        return txt

    inserted_count = 0
    expected_count = 0

    # Insert images at section markers
    for img_info in images:
        img_path = img_info["path"]
        section_keyword = img_info["after_section"]
        if not img_path or not os.path.exists(img_path):
            continue
        expected_count += 1

        all_blocks = _list_doc_children_all()

        # Find the section
        target_idx = len(all_blocks)  # default: append at end
        found_section = False
        for bi, blk in enumerate(all_blocks):
            txt = _heading_text(blk)
            if not txt:
                continue
            if section_keyword and section_keyword in txt:
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
        if not created or err:
            raise RuntimeError(
                f"Create image block failed section='{section_keyword}' path='{img_path}' err={err}"
            )
        img_block_id = created[0]["block_id"]
        file_token = _feishu_upload_image(token, img_block_id, img_path)
        _feishu_patch_image(token, doc_token, img_block_id, file_token)
        inserted_count += 1

    if expected_count > 0 and inserted_count != expected_count:
        raise RuntimeError(
            f"Image embedding mismatch: expected={expected_count}, inserted={inserted_count}"
        )

    # Grant access — admin + requesting user(s)
    _grant_multi_users(token, doc_token, user_openids)

    doc_url = _doc_url_candidates(doc_token)[0]
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
# Role / Case / Parameter — Three-Layer Context Model
# ══════════════════════════════════════════════════════════════

# ── Role prefix parsing ──

_ROLE_PREFIXES = {
    "@运维": "operator", "@科研": "researcher", "@设计": "designer",
    "@operator": "operator", "@researcher": "researcher", "@designer": "designer",
}

def _parse_role_prefix(message: str) -> tuple[str | None, str]:
    """Extract @role prefix from message. Returns (role|None, cleaned_msg)."""
    stripped = message.lstrip()
    for prefix, role in _ROLE_PREFIXES.items():
        if stripped.startswith(prefix):
            cleaned = stripped[len(prefix):].lstrip()
            return role, cleaned
    return None, message


# ── Case tag parsing ──

_CASE_TAGS = {
    "#水箱": "tank", "#tank": "tank",
    "#氧化铝": "alumina", "#alumina": "alumina", "#水网": "alumina",
}

# Heuristic keywords for case auto-detection
_TANK_HINTS = {"水箱", "水位", "水槽", "tank", "液位", "初始水位", "阶跃响应"}
_ALUMINA_HINTS = {"管网", "车间", "泄漏", "日报", "四预", "蒸发", "回用", "调度",
                  "氧化铝", "焙烧", "赤泥", "冷却塔", "水平衡", "alumina"}


def _parse_case_tag(message: str) -> tuple[str | None, str]:
    """Extract #case tag from message. Returns (case_id|None, cleaned_msg)."""
    stripped = message.lstrip()
    for tag, case_id in _CASE_TAGS.items():
        if stripped.startswith(tag):
            cleaned = stripped[len(tag):].lstrip()
            return case_id, cleaned
        # Also match tag anywhere in message (but only strip the first occurrence)
        idx = stripped.find(tag)
        if idx >= 0:
            cleaned = (stripped[:idx] + stripped[idx + len(tag):]).strip()
            return case_id, cleaned
    return None, message


def _infer_case_from_content(message: str) -> str | None:
    """Heuristic case detection from message content."""
    msg_lower = message.lower()
    tank_score = sum(1 for kw in _TANK_HINTS if kw in msg_lower)
    alumina_score = sum(1 for kw in _ALUMINA_HINTS if kw in msg_lower)
    if tank_score > alumina_score:
        return "tank"
    if alumina_score > tank_score:
        return "alumina"
    return None


# ── Case profiles ──

CASE_PROFILES = {
    "tank": {
        "name": "双容水箱",
        "config_path": "/home/admin/hydromas/data/tank_config.json",
        "default_params": {
            "initial_h": 0.5,
            "duration": 300,
            "dt": 1.0,
            "tank_params": {"area": 1.0, "cd": 0.6, "outlet_area": 0.01, "h_max": 2.0},
            "pid": {"kp": 2.0, "ki": 0.1, "kd": 0.5, "setpoint": 1.0},
            "mpc": {"horizon": 10, "setpoint": 1.0},
        },
        "applicable_skills": [
            "control_system_design", "optimization_design",
            "data_analysis_predict", "full_lifecycle", "odd_assessment",
        ],
    },
    "alumina": {
        "name": "氧化铝厂",
        "config_path": "/home/admin/hydromas/data/alumina_config.json",
        "default_params": {
            "daily_intake": 10400,
            "target_reuse_rate": 0.5,
        },
        "applicable_skills": [
            "four_prediction_loop", "daily_report", "leak_diagnosis",
            "evap_optimization", "global_dispatch", "reuse_scheduling",
            "odd_assessment", "forecast_skill", "warning_skill",
        ],
    },
}


# ── Session management ──

@dataclass
class UserSession:
    user_id: str
    last_role: str = "operator"
    last_case: str = "alumina"
    param_overrides: dict = field(default_factory=dict)
    updated_at: str = ""


def _session_path(user_id: str) -> str:
    """Return file path for a user session."""
    uid_hash = hashlib.md5(user_id.encode()).hexdigest()[:12] if user_id else "default"
    return os.path.join(SESSION_DIR, f"session_{uid_hash}.json")


def _load_session(user_id: str) -> UserSession:
    """Load session from disk, or create a new one."""
    path = _session_path(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return UserSession(
                user_id=data.get("user_id", user_id),
                last_role=data.get("last_role", "operator"),
                last_case=data.get("last_case", "alumina"),
                param_overrides=data.get("param_overrides", {}),
                updated_at=data.get("updated_at", ""),
            )
        except (json.JSONDecodeError, KeyError):
            pass
    return UserSession(user_id=user_id)


def _save_session(session: UserSession):
    """Persist session to disk (atomic write via temp file + rename)."""
    from datetime import datetime
    session.updated_at = datetime.now().isoformat(timespec="seconds")
    os.makedirs(SESSION_DIR, exist_ok=True)
    path = _session_path(session.user_id)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(asdict(session), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)  # atomic on POSIX


# ── Extended parameter parsing ──

def _parse_user_params(message: str, case_id: str) -> dict:
    """Extract user parameters from natural language, case-aware.

    Covers both tank and alumina parameters.
    Returns a flat dict of parameter overrides.
    """
    params: dict = {}
    text = message

    # ── Common tank parameters ──
    if case_id == "tank" or case_id is None:
        # initial_h
        m = re.search(r'初始水位\s*([\d.]+)\s*(?:米|m)?', text)
        if not m:
            m = re.search(r'initial[_\s]?h(?:eight)?\s*[=:]\s*([\d.]+)', text, re.I)
        if not m:
            m = re.search(r'水位\s*([\d.]+)\s*(?:米|m)', text)
        if m:
            params["initial_h"] = float(m.group(1))

        # duration
        m = re.search(r'时长\s*([\d.]+)\s*(?:秒|s)', text)
        if not m:
            m = re.search(r'(?:仿真|模拟)?\s*([\d.]+)\s*(?:秒|s)\b', text)
        if not m:
            m = re.search(r'duration\s*[=:]\s*([\d.]+)', text, re.I)
        if m:
            params["duration"] = float(m.group(1))

        # dt
        m = re.search(r'(?:步长|dt)\s*[=:]\s*([\d.]+)', text, re.I)
        if m:
            params["dt"] = float(m.group(1))

        # setpoint
        m = re.search(r'(?:设定值|setpoint|目标水位)\s*[=:]*\s*([\d.]+)', text, re.I)
        if m:
            params["setpoint"] = float(m.group(1))

        # tank_area
        m = re.search(r'(?:水箱)?面积\s*([\d.]+)\s*(?:平方米|m²|m2|㎡)', text)
        if not m:
            m = re.search(r'(?:tank[_\s]?)?area\s*[=:]\s*([\d.]+)', text, re.I)
        if m:
            params["tank_area"] = float(m.group(1))

        # cd
        m = re.search(r'(?:流量系数|Cd)\s*[=:]\s*([\d.]+)', text, re.I)
        if m:
            params["cd"] = float(m.group(1))

        # outlet_area
        m = re.search(r'出口面积\s*([\d.]+)\s*(?:平方米|m²|m2|㎡)?', text)
        if not m:
            m = re.search(r'outlet[_\s]?area\s*[=:]\s*([\d.]+)', text, re.I)
        if m:
            params["outlet_area"] = float(m.group(1))

        # q_in
        m = re.search(r'入流\s*([\d.]+)\s*(?:m³/s)?', text)
        if not m:
            m = re.search(r'q[_\s]?in\s*[=:]\s*([\d.]+)', text, re.I)
        if m:
            params["q_in"] = float(m.group(1))

        # PID parameters
        for pid_key in ("kp", "ki", "kd"):
            m = re.search(rf'{pid_key}\s*[=:]\s*([\d.]+)', text, re.I)
            if m:
                params[pid_key] = float(m.group(1))

        # disturbance (step profile)
        m = re.search(r'(?:扰动幅值|disturbance[_\s]?magnitude)\s*[=:]?\s*([+-]?[\d.]+)', text, re.I)
        if m:
            params["disturbance_magnitude"] = float(m.group(1))
        m = re.search(r'(?:扰动开始|disturbance[_\s]?start)\s*[=:]?\s*([\d.]+)\s*(?:秒|s)?', text, re.I)
        if m:
            params["disturbance_start"] = float(m.group(1))
        m = re.search(r'(?:扰动结束|disturbance[_\s]?end)\s*[=:]?\s*([\d.]+)\s*(?:秒|s)?', text, re.I)
        if m:
            params["disturbance_end"] = float(m.group(1))
        if re.search(r'(?:入流扰动|inflow disturbance|disturbance[_\s]?type\s*[=:]?\s*inflow)', text, re.I):
            params["disturbance_type"] = "inflow"
        elif re.search(r'(?:出流扰动|outflow disturbance|disturbance[_\s]?type\s*[=:]?\s*outflow)', text, re.I):
            params["disturbance_type"] = "outflow"

        # MPC horizon
        m = re.search(r'(?:预测步长|horizon)\s*[=:]\s*(\d+)', text, re.I)
        if m:
            params["horizon"] = int(m.group(1))

    # ── Alumina parameters ──
    if case_id == "alumina" or case_id is None:
        # daily_intake
        m = re.search(r'(?:日取水量|daily[_\s]?intake)\s*[=:]*\s*([\d.]+)', text, re.I)
        if m:
            params["daily_intake"] = float(m.group(1))

        # target_reuse_rate
        m = re.search(r'(?:目标回用率|target[_\s]?reuse[_\s]?rate)\s*[=:]*\s*([\d.]+)', text, re.I)
        if m:
            params["target_reuse_rate"] = float(m.group(1))

    return params


# ── Meta commands ──

_META_HELP = """## HydroMAS 交互帮助

### 角色前缀
- `@运维` / `@operator` — 运维助理（四预、调度、日报）
- `@科研` / `@researcher` — 科研助理（仿真、分析、预测）
- `@设计` / `@designer` — 设计助理（控制、优化、敏感性）

### 案例标签
- `#水箱` / `#tank` — 双容水箱案例
- `#氧化铝` / `#alumina` / `#水网` — 氧化铝厂水网案例

### 参数覆盖（自然语言）
- 水箱: `初始水位1.0米`, `时长600秒`, `面积2平方米`, `kp=3.0`, `setpoint=1.5`
- 氧化铝: `日取水量10000`, `目标回用率0.5`

### 元命令
- `帮助` / `help` — 显示此帮助
- `查看参数` / `当前设置` — 查看当前角色、案例和参数覆盖
- `重置参数` — 清空参数覆盖，恢复默认
- `切换水箱` — 切换到水箱案例
- `切换氧化铝` — 切换到氧化铝案例

### 示例
```
@科研 #水箱 仿真初始水位1.0米，时长600秒
@运维 运行四预闭环
@设计 #氧化铝 蒸发优化
改为面积2平方米，再仿真一次
查看参数
重置参数
```
"""


def _handle_meta_command(message: str, session: UserSession) -> str | None:
    """Handle meta commands. Returns response string or None if not a meta command."""
    stripped = message.strip()

    if stripped in ("帮助", "help", "Help", "HELP"):
        return _META_HELP

    if stripped in ("查看参数", "当前设置", "show params", "show settings"):
        case_name = CASE_PROFILES.get(session.last_case, {}).get("name", session.last_case)
        lines = [
            "## 当前设置",
            "",
            f"- **角色**: {session.last_role}",
            f"- **案例**: {case_name} ({session.last_case})",
        ]
        if session.param_overrides:
            lines.append("- **参数覆盖**:")
            for k, v in session.param_overrides.items():
                lines.append(f"  - {k} = {v}")
        else:
            lines.append("- **参数覆盖**: 无（使用默认）")
        lines.append(f"\n*上次更新: {session.updated_at or '—'}*")
        return "\n".join(lines)

    if stripped in ("重置参数", "reset params", "reset"):
        session.param_overrides = {}
        _save_session(session)
        return "参数已重置为默认值。"

    if stripped in ("切换水箱", "switch tank"):
        session.last_case = "tank"
        _save_session(session)
        return "已切换到 **双容水箱** 案例。"

    if stripped in ("切换氧化铝", "switch alumina"):
        session.last_case = "alumina"
        _save_session(session)
        return "已切换到 **氧化铝厂** 案例。"

    return None


# ── Unified context resolution ──

def _resolve_context(message: str, user_openid: str | None, cli_role: str | None
                     ) -> tuple[str, str, str, dict, UserSession]:
    """Resolve role, case, params, and session from message + context.

    Returns: (role, case_id, cleaned_msg, merged_params, session)

    Priority chains:
      Role:  --role CLI > @prefix > session memory > keyword heuristic > "operator"
      Case:  #tag > content heuristic > session memory > "alumina"
      Params: case defaults < skill defaults < session overrides < inline params
    """
    # 1. Parse @role prefix
    prefix_role, cleaned = _parse_role_prefix(message)

    # 2. Parse #case tag
    tag_case, cleaned = _parse_case_tag(cleaned)

    # 3. Load session
    uid = user_openid or ""
    session = _load_session(uid)

    # 4. Resolve role (priority: CLI > prefix > session > heuristic > default)
    if cli_role and cli_role != "operator":
        role = cli_role
    elif prefix_role:
        role = prefix_role
    elif session.last_role:
        role = session.last_role
    else:
        role = "operator"
    # Keyword heuristic fallback (only when no explicit role is set)
    # Override session role if strong keywords are detected.
    if not cli_role and not prefix_role:
        msg_lower = cleaned.lower()
        if any(k in msg_lower for k in ["控制设计", "优化设计", "蒸发优化", "回用优化", "pid", "mpc"]):
            role = "designer"
        elif any(k in msg_lower for k in ["仿真", "模拟", "simulate", "阶跃", "数据分析", "wnal"]):
            role = "researcher"

    # 5. Resolve case (priority: #tag > content heuristic > session > default)
    if tag_case:
        case_id = tag_case
    else:
        inferred = _infer_case_from_content(cleaned)
        if inferred:
            case_id = inferred
        elif session.last_case:
            case_id = session.last_case
        else:
            case_id = "alumina"

    # 6. Parse inline parameters
    inline_params = _parse_user_params(cleaned, case_id)

    # 7. Merge parameters: case defaults < session overrides < inline
    case_defaults = CASE_PROFILES.get(case_id, {}).get("default_params", {})
    merged = {}
    _deep_merge(merged, case_defaults)
    _deep_merge(merged, session.param_overrides)
    _deep_merge(merged, inline_params)

    # 8. Update session
    session.last_role = role
    session.last_case = case_id
    if inline_params:
        _deep_merge(session.param_overrides, inline_params)

    return role, case_id, cleaned, merged, session


def _deep_merge(base: dict, overlay: dict):
    """Deep merge overlay into base (in place)."""
    for k, v in overlay.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ══════════════════════════════════════════════════════════════
# Generic skill routing + adaptive report architecture
# ══════════════════════════════════════════════════════════════

_skills_cache: dict = {"skills": None, "expires": 0}

# Strong simulation keywords — always indicate tank simulation
_SIM_STRONG = {"仿真", "模拟", "水位变化", "阶跃响应", "水动力", "双容水箱", "扰动测试", "扰动试验"}
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


# ── LLM-based intent classification (Layer 1) ──

def _build_skill_catalog() -> str:
    """用缓存的 skills 列表构建 LLM 提示词中的技能目录。"""
    now = _time.time()
    if _skills_cache["skills"] is None or now > _skills_cache["expires"]:
        result = _get("/api/gateway/skills")
        _skills_cache["skills"] = result.get("skills", [])
        _skills_cache["expires"] = now + 300

    lines = []
    for s in (_skills_cache["skills"] or []):
        name = s.get("name", "")
        desc = s.get("description", "").split("/")[0].strip()[:60]
        triggers = ", ".join(s.get("trigger_phrases", [])[:5])
        lines.append(f"- {name}: {desc} (触发词: {triggers})")
    return "\n".join(lines)


def _llm_classify_intent(message: str, role: str, case_id: str) -> dict | None:
    """关键词匹配失败时，用 LLM 分类意图。

    返回 {"skill_name": "...", "confidence": 0.8, "explanation": "..."} 或 None。
    """
    try:
        from llm_client import call_llm_json
    except ImportError:
        return None

    skill_catalog = _build_skill_catalog()
    if not skill_catalog:
        return None

    system_prompt = (
        "你是 HydroMAS 水网智能平台的意图分类器。\n"
        "根据用户输入，判断应调用哪个技能。\n\n"
        f"当前角色: {role}，案例: {case_id}\n\n"
        f"可用技能:\n{skill_catalog}\n\n"
        "规则:\n"
        "1. 明确匹配技能 → 返回技能名\n"
        "2. 纯闲聊/知识问答 → skill_name 返回 null\n"
        "3. 只返回 JSON，不要其他文本\n\n"
        '格式: {"skill_name": "xxx或null", "confidence": 0.0-1.0, "explanation": "理由"}'
    )

    result = call_llm_json(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        temperature=0.1,
        max_tokens=256,
        timeout=60,
    )

    if not result:
        return None

    # Validate: skill_name must exist in known skills
    sn = result.get("skill_name")
    if sn and sn != "null":
        known_names = {s.get("name") for s in (_skills_cache["skills"] or [])}
        if sn not in known_names:
            return None
        confidence = result.get("confidence", 0)
        if confidence < 0.5:
            return None  # low confidence → don't override
    else:
        result["skill_name"] = None

    return result


# ── LLM result interpretation (Layer 2) ──

_ROLE_NAMES = {
    "operator": "运维工程师",
    "researcher": "科研人员",
    "designer": "设计工程师",
}

_REPORT_IMAGE_DIR = "/tmp/hydromas-report-images"

# ── Role-specific report styling ──
_ROLE_REPORT_STYLE = {
    "operator": {
        "title_suffix": "运维监控报告",
        "icon": "🔧",
        "intro": (
            "本报告面向一线运维人员，以**运行状态监控**和**操作指导**为核心。"
            "采用「状态面板 → 异常告警 → 操作清单」结构，帮助快速定位问题并采取行动。"
        ),
        "section_style": "dashboard",  # KPI面板+告警+操作清单
        "summary_prompt_extra": (
            "你正在为一线运维班组撰写当班运行报告。\n"
            "写作风格要求：\n"
            "- 开头用 🟢/🟡/🔴 信号灯标注每个子系统状态\n"
            "- 突出异常值和告警阈值（如'水位 1.82m 接近上限 2.0m'）\n"
            "- 操作建议要精确到具体阀门/泵/仪表编号\n"
            "- 语气直接果断，像班组交接时的口头汇报"
        ),
        "interpret_prompt_extra": (
            "你在为运维值班人员解读数据，要求：\n"
            "- 重点关注是否超限、是否需要立即干预\n"
            "- 用对比说明趋势（如'较上周下降3%'、'连续2天偏高'）\n"
            "- 给出具体操作步骤而非建议方向"
        ),
    },
    "researcher": {
        "title_suffix": "科研分析报告",
        "icon": "📊",
        "intro": (
            "本报告面向科研分析人员，以**数据分析深度**和**方法论严谨性**为核心。"
            "采用「方法论 → 数据分析 → 模型验证 → 结论」学术报告结构。"
        ),
        "section_style": "academic",  # 方法+数据+验证+结论
        "summary_prompt_extra": (
            "你正在为水利工程科研团队撰写技术分析报告。\n"
            "写作风格要求：\n"
            "- 使用学术化表述，标注分析方法（如'基于 ARX 模型辨识'、'Merkel 蒸发模型'）\n"
            "- 给出性能指标的统计意义（RMSE、NSE、MAE）\n"
            "- 与行业标准/文献基准值对比（如'回用率 36% 低于 GB/T 标准推荐的 50%'）\n"
            "- 指出数据不足或模型局限性\n"
            "- 建议后续研究方向"
        ),
        "interpret_prompt_extra": (
            "你在为科研人员解读分析结果，要求：\n"
            "- 从方法论角度评价结果可靠性\n"
            "- 解释关键参数的物理意义\n"
            "- 与理论值/经验公式进行对比\n"
            "- 指出异常数据点的可能原因"
        ),
    },
    "designer": {
        "title_suffix": "设计规格报告",
        "icon": "📐",
        "intro": (
            "本报告面向系统设计工程师，以**设计参数优化**和**安全域校核**为核心。"
            "采用「设计需求 → 方案分析 → 参数优化 → 安全验证」工程设计规格书结构。"
        ),
        "section_style": "specification",  # 需求+方案+参数+验证
        "summary_prompt_extra": (
            "你正在为水利系统设计工程师撰写设计规格评估报告。\n"
            "写作风格要求：\n"
            "- 以设计参数和安全裕度为核心（如'PID 超调量 8.2% < 限值 10%，裕度 1.8%'）\n"
            "- 列出关键设计变量及其取值范围\n"
            "- 对比不同设计方案的性能指标（PID vs MPC）\n"
            "- 明确标注 ODD（运行设计域）的边界条件\n"
            "- 给出设计余量和安全系数建议"
        ),
        "interpret_prompt_extra": (
            "你在为设计工程师解读分析结果，要求：\n"
            "- 评估当前参数是否满足设计规格\n"
            "- 指出优化空间和约束条件\n"
            "- 量化安全裕度（离ODD边界的距离）\n"
            "- 建议下一步设计迭代方向"
        ),
    },
}


def _truncate_result_for_llm(result: dict, max_chars: int = 2000) -> str:
    """截断结果 JSON，去掉时序数组，保留关键指标。"""
    def _strip_arrays(obj, depth=0):
        if depth > 3:
            return "..."
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if isinstance(v, list) and len(v) > 10:
                    out[k] = f"[{len(v)} items, first={v[0]}, last={v[-1]}]"
                elif isinstance(v, dict):
                    out[k] = _strip_arrays(v, depth + 1)
                else:
                    out[k] = v
            return out
        return obj

    stripped = _strip_arrays(result)
    text = json.dumps(stripped, ensure_ascii=False, default=str)
    if len(text) > max_chars:
        text = text[:max_chars] + "...(截断)"
    return text


def _llm_interpret_result(message: str, result: dict, skill_name: str | None,
                          role: str, case_id: str) -> str | None:
    """生成角色定制化深度专业解读（5-8句）。失败返回 None。"""
    try:
        from llm_client import call_llm
    except ImportError:
        return None

    role_name = _ROLE_NAMES.get(role, "工程师")
    case_name = CASE_PROFILES.get(case_id, {}).get("name", case_id)
    result_text = _truncate_result_for_llm(result, max_chars=3000)

    # Role-specific interpretation style
    role_style = _ROLE_REPORT_STYLE.get(role, {})
    role_extra = role_style.get("interpret_prompt_extra", "")

    system_prompt = (
        f"你是 HydroMAS 水网智能平台的资深{role_name}。\n"
        f"当前案例: {case_name}\n\n"
    )
    if role_extra:
        system_prompt += role_extra + "\n\n"
    system_prompt += (
        "请对以下分析结果进行深度专业解读，按以下结构输出：\n\n"
        "**核心结论**（1-2句，最关键的发现）\n\n"
        "**数据解读**（2-3句，解释关键数值含义、趋势、与行业标准的对比）\n\n"
        "**操作建议**（2-3句，针对当前角色的具体可执行建议）\n\n"
        "要求：\n"
        "- 用中文，专业但不晦涩\n"
        "- 引用具体数值（如'回用率36%低于行业平均50%'）\n"
        "- 建议要具体可操作，不要泛泛而谈\n"
        "- 不要加Markdown标题，直接用加粗标记段落\n"
        "- 不要重复原始数据表格中已有的内容"
    )

    user_prompt = f"用户问题: {message}\n"
    if skill_name:
        user_prompt += f"分析技能: {skill_name}\n"
    user_prompt += f"分析结果:\n{result_text}"

    return call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=800,
        timeout=60,
    )


def _llm_executive_summary(role: str, case_id: str,
                            skill_results: list[tuple[str, dict]]) -> str | None:
    """为综合报告生成角色定制化执行摘要。skill_results = [(skill_name, result), ...]"""
    try:
        from llm_client import call_llm
    except ImportError:
        return None

    role_name = _ROLE_NAMES.get(role, "工程师")
    case_name = CASE_PROFILES.get(case_id, {}).get("name", case_id)

    # Build condensed results summary
    parts = []
    for sn, res in skill_results:
        condensed = _truncate_result_for_llm(res, max_chars=800)
        parts.append(f"[{_humanize_key(sn)}]: {condensed}")
    all_results = "\n\n".join(parts)
    if len(all_results) > 6000:
        all_results = all_results[:6000] + "...(截断)"

    # Role-specific executive summary style
    role_style = _ROLE_REPORT_STYLE.get(role, {})
    role_extra = role_style.get("summary_prompt_extra", "")

    system_prompt = (
        f"你是 HydroMAS 水网智能平台的资深{role_name}，正在为{case_name}系统撰写综合分析报告的执行摘要。\n\n"
    )
    if role_extra:
        system_prompt += role_extra + "\n\n"
    system_prompt += (
        "请基于以下多个分析模块的结果，撰写一份 **执行摘要**，要求：\n\n"
        "1. **总体评估**（2-3句）：系统当前运行状态的整体判断\n"
        "2. **关键发现**（3-5条）：每条一句话，标注数据来源模块，突出异常或亮点\n"
        "3. **优先行动项**（2-3条）：按紧急程度排序的具体建议\n"
        "4. **风险提示**（1-2条）：需要关注的潜在问题\n\n"
        "格式要求：\n"
        "- 使用 Markdown 加粗和列表\n"
        "- 引用具体数值\n"
        "- 总长度 400-600 字"
    )

    return call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"以下是{len(skill_results)}个分析模块的结果：\n\n{all_results}"},
        ],
        temperature=0.3,
        max_tokens=1500,
        timeout=60,
    )


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

# 高位水池 24h 水位监测数据 (m) — 模拟正常运行+缓降趋势
_WATER_LEVEL_24H = [
    1.50, 1.48, 1.45, 1.43, 1.40, 1.38, 1.35, 1.33,  # 00:00-07:00
    1.30, 1.28, 1.25, 1.22, 1.20, 1.18, 1.15, 1.13,  # 08:00-15:00
    1.10, 1.08, 1.06, 1.04, 1.02, 1.00, 0.98, 0.96,  # 16:00-23:00
]

_SKILL_DEFAULTS: dict[str, dict] = {
    "four_prediction_loop": {
        "historical_data": _WATER_LEVEL_24H,
        "horizon": 60,
        "model": "linear",
    },
    "forecast_skill": {
        "historical_data": _WATER_LEVEL_24H,
        "horizon": 60,
        "model": "linear",
    },
    "warning_skill": {
        "historical_data": _WATER_LEVEL_24H,
        "horizon": 60,
    },
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


_TANK_SKILL_DEFAULTS: dict[str, dict] = {
    "simulate_tank": {
        "initial_h": 0.5,
        "duration": 300,
        "dt": 1.0,
    },
    "control_system_design": {
        "initial_h": 0.5,
        "duration": 300,
        "setpoint": 1.0,
    },
    "optimization_design": {
        "initial_h": 0.5,
        "duration": 300,
    },
    "data_analysis_predict": {
        "raw_data": [
            1.0, 0.98, 0.95, 0.93, 0.90, 0.88, 0.85, 0.83, 0.82, 0.80,
            0.79, 0.78, 0.77, 0.76, 0.76, 0.75, 0.75, 0.74, 0.74, 0.74,
        ],
        "horizon": 10,
        "model": "linear",
    },
    "odd_assessment": {
        "current_state": {
            "water_level": 0.5,
            "tank_area": 1.0,
            "h_max": 2.0,
        },
    },
    "full_lifecycle": {},
}

# _SKILL_DEFAULTS serves as _ALUMINA_SKILL_DEFAULTS (backward compatible)
_ALUMINA_SKILL_DEFAULTS = _SKILL_DEFAULTS


def _get_skill_defaults(skill_name: str, case_id: str = "alumina") -> dict:
    """Return default parameters for a skill, based on case profile.

    Merges case-level defaults with skill-level defaults.
    """
    if case_id == "tank":
        return _TANK_SKILL_DEFAULTS.get(skill_name, {})
    return _ALUMINA_SKILL_DEFAULTS.get(skill_name, {})


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
        # Build aligned table
        rows = [(_humanize_key(k), _format_value(v)) for k, v in scalars.items()]
        col1_w = max(len(r[0]) for r in rows)
        col2_w = max(len(r[1]) for r in rows)
        col1_w = max(col1_w, 4)  # minimum "指标"
        col2_w = max(col2_w, 2)  # minimum "值"
        lines.append(f"| {'指标':<{col1_w}} | {'值':<{col2_w}} |")
        lines.append(f"|{'-' * (col1_w + 2)}|{'-' * (col2_w + 2)}|")
        for label, val in rows:
            lines.append(f"| {label:<{col1_w}} | {val:<{col2_w}} |")
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
                    avg = sum(v) / len(v)
                    lines.append(f"- **{_humanize_key(k)}**: {len(v)} 个数据点，"
                                 f"范围 [{min(v):.4f}, {max(v):.4f}]，"
                                 f"均值 {avg:.4f}")
                else:
                    lines.append(f"- **{_humanize_key(k)}**: {', '.join(_format_value(x) for x in v)}")
            elif all(isinstance(x, dict) for x in v):
                lines.append(f"{heading} {_humanize_key(k)}")
                lines.append("")
                keys = list(v[0].keys())
                headers = [_humanize_key(kk) for kk in keys]
                # Calculate column widths for alignment
                col_widths = [max(len(h), 6) for h in headers]
                for row in v[:20]:
                    for i, kk in enumerate(keys):
                        cell = _format_value(row.get(kk, ""))
                        col_widths[i] = max(col_widths[i], len(cell))
                # Build table
                lines.append("| " + " | ".join(
                    f"{h:<{col_widths[i]}}" for i, h in enumerate(headers)) + " |")
                lines.append("|" + "|".join(
                    f"{'-' * (w + 2)}" for w in col_widths) + "|")
                for row in v[:20]:
                    cells = [_format_value(row.get(kk, "")) for kk in keys]
                    lines.append("| " + " | ".join(
                        f"{c:<{col_widths[i]}}" for i, c in enumerate(cells)) + " |")
                if len(v) > 20:
                    lines.append(f"| *... 共 {len(v)} 行，显示前 20 行* |")
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


def _build_adaptive_report(message: str, result: dict, skill_name: str | None = None,
                            role: str = "", case_name: str = "") -> str:
    """Build a Markdown report that adapts to any response structure.

    结构：标题 → 报告信息 → 详细数据 → 页脚
    （AI 解读和执行摘要由调用方在外部插入）
    """
    from datetime import datetime
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    role_label = _ROLE_NAMES.get(role, role) if role else ""
    lines = [
        f"# HydroMAS 分析报告",
        "",
    ]
    # Report metadata block
    meta = [f"**问题**: {message}", f"**时间**: {now_str}"]
    if skill_name:
        meta.append(f"**分析类型**: {_humanize_key(skill_name)}")
    if role_label:
        meta.append(f"**角色**: {role_label}")
    if case_name:
        meta.append(f"**案例**: {case_name}")
    for m in meta:
        lines.append(f"> {m}")
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


_TITLE_SKILL_TOPICS = {
    "simulation": "仿真分析",
    "daily_report": "运营日报",
    "four_prediction_loop": "四预闭环",
    "odd_assessment": "ODD评估",
    "water_balance": "水平衡分析",
    "leak_diagnosis": "泄漏诊断",
    "evap_optimization": "蒸发优化",
    "global_dispatch": "全局调度",
    "data_analysis_predict": "数据分析",
    "control_system_design": "控制设计",
    "optimization_design": "优化设计",
}


def _clean_title_fragment(text: str, max_len: int = 20) -> str:
    """Normalize free-form text for concise document titles."""
    cleaned = re.sub(r"[@#][^\s]+", "", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:，。；：")
    if not cleaned:
        return "综合分析"
    if len(cleaned) > max_len:
        return cleaned[:max_len].rstrip() + "..."
    return cleaned


def _resolve_report_skill(message: str, result: dict, skill_name: str | None) -> str:
    """Choose a stable skill label for report history."""
    if skill_name:
        return skill_name
    if isinstance(result, dict):
        intent = result.get("intent", {}) if isinstance(result.get("intent"), dict) else {}
        target = intent.get("target")
        if isinstance(target, str) and target:
            return target
    matched = _find_matching_skill(message)
    if matched:
        return matched
    return "chat"


def _build_report_title(
    message: str,
    role: str,
    case_name: str,
    skill_name: str | None,
    now: str,
) -> str:
    """Build readable, bounded-length title for Feishu docs."""
    role_labels = {"operator": "运维", "researcher": "科研", "designer": "设计"}
    case_short = _clean_title_fragment(case_name or "水网", max_len=10)
    role_short = role_labels.get(role, role)
    topic = _TITLE_SKILL_TOPICS.get(skill_name or "", "")
    if not topic:
        topic = _clean_title_fragment(message, max_len=20)
    return f"HydroMAS · {case_short} · {role_short} · {topic} ({now})"


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
    cli_role = None
    i = 1
    while i < len(args):
        if args[i] == "--folder" and i + 1 < len(args):
            folder_token = args[i + 1]; i += 2
        elif args[i] == "--user-openid" and i + 1 < len(args):
            user_openid = args[i + 1]; i += 2
        elif args[i] == "--role" and i + 1 < len(args):
            cli_role = args[i + 1]; i += 2
        else:
            i += 1

    # Resolve context (role, case, cleaned message, merged params, session)
    role, case_id, cleaned_msg, merged_params, session = _resolve_context(
        message, user_openid, cli_role)

    user_openids = [user_openid] if user_openid else None

    # Check meta commands
    meta_response = _handle_meta_command(cleaned_msg, session)
    if meta_response is not None:
        print(meta_response)
        return

    case_name = CASE_PROFILES.get(case_id, {}).get("name", case_id)

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    skill_name = None
    has_feishu_creds = _print_feishu_credential_status("report")
    skip_publish = os.environ.get("HYDROMAS_SKIP_FEISHU_PUBLISH", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not has_feishu_creds and not skip_publish:
        print(
            "Error: Missing Feishu credentials; set FEISHU_APP_ID/FEISHU_APP_SECRET via env "
            "or .env/AGENTS.md. For local validation, set HYDROMAS_SKIP_FEISHU_PUBLISH=1.",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── Route 1: Tank simulation (uses dedicated rich endpoint) ──
    if _is_simulation_request(cleaned_msg):
        # Build API payload from merged params (case defaults + session + inline)
        api_payload: dict = {"title": cleaned_msg}
        if "initial_h" in merged_params:
            api_payload["initial_h"] = merged_params["initial_h"]
        if "duration" in merged_params:
            api_payload["duration"] = merged_params["duration"]
        if "dt" in merged_params:
            api_payload["dt"] = merged_params["dt"]
        # Build tank_params from merged data
        tank_p = {}
        if "tank_params" in merged_params and isinstance(merged_params["tank_params"], dict):
            tank_p.update(merged_params["tank_params"])
        # Also pick up flat keys from user params
        for flat_key, tank_key in [("tank_area", "area"), ("cd", "cd"),
                                    ("outlet_area", "outlet_area")]:
            if flat_key in merged_params:
                tank_p[tank_key] = merged_params[flat_key]
        if tank_p:
            api_payload["tank_params"] = tank_p
        # q_in from merged params
        if "q_in" in merged_params:
            api_payload["q_in_profile"] = [[0, merged_params["q_in"]]]
        elif "q_in_profile" in merged_params:
            api_payload["q_in_profile"] = merged_params["q_in_profile"]

        result = _post("/api/report/tank-analysis", api_payload)
        if "error" not in result:
            if _TANK_PID_IMPORT_ERROR is not None:
                print(f"Error: tank_pid module unavailable: {_TANK_PID_IMPORT_ERROR}")
                sys.exit(1)
            # Tank sim: use existing rich report format
            md_text = _build_analysis_markdown(result)
            params = result.get("parameters", {})
            sim = result.get("simulation", {})
            (
                tank_cfg,
                sim_cfg,
                seed_gains,
                disturbance_cfg,
                noise_cfg,
                uncertainty_cfg,
                optimizer_method,
                robust_samples,
            ) = _build_dual_tank_pid_inputs(result, merged_params)
            with ThreadPoolExecutor(max_workers=3) as pool:
                f_schem = pool.submit(_generate_tank_schematic, params)
                f_chart = pool.submit(_generate_chart_from_sim, sim, cleaned_msg)
                f_pid = pool.submit(
                    generate_pid_report_artifacts,
                    tank_cfg,
                    sim_cfg,
                    seed_gains,
                    disturbance_cfg,
                    _REPORT_IMAGE_DIR,
                    optimizer_method,
                    noise_cfg,
                    uncertainty_cfg,
                    robust_samples,
                )
                schematic_path = f_schem.result()
                chart_path = f_chart.result()
                pid_artifacts = f_pid.result()

            requested_cases = _extract_report_case_count(cleaned_msg, merged_params)
            suite_images: list[dict] = []
            case_summaries: list[dict] = []
            if requested_cases >= 2:
                best = pid_artifacts["optimization"]["best"]
                best_gains = PIDGains(kp=best["kp"], ki=best["ki"], kd=best["kd"])
                suite_md, suite_images, case_summaries = _build_multi_case_suite(
                    case_count=requested_cases,
                    tank_cfg=tank_cfg,
                    sim_cfg=sim_cfg,
                    seed_gains=seed_gains,
                    best_gains=best_gains,
                    disturbance_cfg=disturbance_cfg,
                    noise_cfg=noise_cfg,
                    uncertainty_cfg=uncertainty_cfg,
                )
                md_text += "\n\n" + suite_md
            else:
                md_text += "\n\n" + build_pid_report_markdown(pid_artifacts)

            history_skill = "simulation"
            title = _build_report_title(cleaned_msg, role, case_name, history_skill, now)
            images = [
                img for img in [
                    {"path": schematic_path, "after_section": "系统概念图"},
                    {"path": chart_path, "after_section": "过程线图"},
                    {
                        "path": pid_artifacts["plots"].get("water_level_vs_setpoint"),
                        "after_section": "水位-设定值叠加对比图",
                    },
                    {
                        "path": pid_artifacts["plots"].get("control_signal"),
                        "after_section": "控制信号叠加图",
                    },
                    {
                        "path": pid_artifacts["plots"].get("disturbance_profile"),
                        "after_section": "扰动曲线图",
                    },
                    {
                        "path": pid_artifacts["plots"].get("optimization_process"),
                        "after_section": "优化过程图",
                    },
                    {
                        "path": pid_artifacts["plots"].get("pareto_tradeoff"),
                        "after_section": "Pareto trade-off 图",
                    },
                    {
                        "path": pid_artifacts["plots"].get("performance_radar"),
                        "after_section": "性能雷达图",
                    },
                ] if img["path"]
            ]
            images.extend(suite_images)
            try:
                if skip_publish:
                    print("[report] HYDROMAS_SKIP_FEISHU_PUBLISH=1, skip Feishu publish.", file=sys.stderr)
                    analysis = result.get("analysis", {})
                    best = pid_artifacts["optimization"]["best"]
                    print("飞书文档: SKIPPED")
                    print(f"摘要: 水位 {analysis.get('initial_h', 0):.2f}m→{analysis.get('final_h', 0):.2f}m "
                          f"(Δ{analysis.get('h_change', 0):+.2f}m)，{analysis.get('response_type', '')}; "
                          f"优化PID Kp={best['kp']:.3f}, Ki={best['ki']:.3f}, Kd={best['kd']:.3f}")
                    _save_session(session)
                    return
                doc_url, doc_tok, written = _publish_report_to_feishu(
                    title, md_text, images, folder_token, user_openids)
                _record_report(user_openid or "", doc_tok, doc_url, title, history_skill)
                analysis = result.get("analysis", {})
                best = pid_artifacts["optimization"]["best"]
                if case_summaries:
                    case_brief = "; ".join(
                        f"{c['name']}: IAE={c['iae']:.3f}, 超调={c['overshoot']:.3f}m"
                        for c in case_summaries
                    )
                    summary_text = (
                        f"已完成{requested_cases}案例与{len(images)}张图。{case_brief}"
                    )
                else:
                    summary_text = (
                        f"水位 {analysis.get('initial_h', 0):.2f}m→{analysis.get('final_h', 0):.2f}m "
                        f"(Δ{analysis.get('h_change', 0):+.2f}m)，{analysis.get('response_type', '')}; "
                        f"优化PID Kp={best['kp']:.3f}, Ki={best['ki']:.3f}, Kd={best['kd']:.3f}"
                    )
                print(f"飞书文档: {doc_url}")
                alt_urls = _doc_url_candidates(doc_tok)[1:]
                if alt_urls:
                    print(f"备用链接: {alt_urls[0]}")
                print(f"摘要: {summary_text}")
                _notify_report_ready(doc_url, summary_text, user_openid=user_openid)
            except Exception as e:
                print(f"飞书文档创建失败: {e}")
                print(f"\n{md_text}")
                sys.exit(1)
            _save_session(session)
            return

    # ── Route 2: Dynamic skill matching (keyword → LLM fallback) ──
    skill_name = _find_matching_skill(cleaned_msg)
    # LLM fallback: if keyword matching fails, try LLM intent classification
    if skill_name is None:
        llm_result = _llm_classify_intent(cleaned_msg, role, case_id)
        if llm_result and llm_result.get("skill_name"):
            skill_name = llm_result["skill_name"]
            print(f"[LLM] 意图识别: {skill_name} "
                  f"(置信度: {llm_result.get('confidence', '?')}, "
                  f"{llm_result.get('explanation', '')})", file=sys.stderr)
    if skill_name:
        # Get skill defaults based on case, then deep-merge user params
        skill_defaults = _get_skill_defaults(skill_name, case_id)
        skill_params = {}
        _deep_merge(skill_params, skill_defaults)
        _deep_merge(skill_params, merged_params)
        result = _post("/api/gateway/skill", {
            "skill_name": skill_name,
            "params": skill_params,
            "role": role,
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
        result = _post("/api/gateway/chat", {
            "message": cleaned_msg, "role": role, "session_id": "",
            "user_id": user_openid or "",
            "params": {
                "case_id": case_id,
                "case_name": case_name,
                "param_overrides": merged_params,
            },
        })

        # Check for chat path tool execution failures
        chat_inner = result.get("result", {})
        if isinstance(chat_inner, dict) and chat_inner.get("status") == "failed":
            failed_tool = chat_inner.get("tool", "unknown")
            failed_error = chat_inner.get("error", "")
            print(f"[WARN] Chat tool '{failed_tool}' failed: {failed_error[:100]}", file=sys.stderr)
            # Wrap the error so we still produce a meaningful report
            result["_chat_failed"] = True
            result["_chat_error_tool"] = failed_tool
            result["_chat_error_msg"] = failed_error

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    # ── Build adaptive report + LLM interpretation + charts (parallel) ──
    md_text = _build_adaptive_report(message, result, skill_name,
                                      role=role, case_name=case_name)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_interpret = pool.submit(
            _llm_interpret_result, message, result, skill_name, role, case_id)
        f_charts = pool.submit(_auto_detect_charts, result)
        ai_interpretation = f_interpret.result()
        chart_paths = f_charts.result()

    if ai_interpretation:
        # Insert "AI 解读" section before the footer line
        ai_section = f"## AI 解读\n\n{ai_interpretation}\n\n"
        if "---\n\n*报告由 HydroMAS" in md_text:
            md_text = md_text.replace(
                "---\n\n*报告由 HydroMAS",
                f"{ai_section}---\n\n*报告由 HydroMAS",
            )
        else:
            md_text += f"\n\n{ai_section}"

    images = [{"path": p, "after_section": ""} for p in chart_paths if p]

    history_skill = _resolve_report_skill(cleaned_msg, result, skill_name)
    title = _build_report_title(cleaned_msg, role, case_name, history_skill, now)
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

    try:
        if skip_publish:
            print("[report] HYDROMAS_SKIP_FEISHU_PUBLISH=1, skip Feishu publish.", file=sys.stderr)
            print("飞书文档: SKIPPED")
            print(f"摘要: {' | '.join(summary_parts) if summary_parts else '分析完成（未发布到飞书）'}")
            _save_session(session)
            return
        if images:
            doc_url, doc_tok, written = _publish_report_to_feishu(
                title, md_text, images, folder_token, user_openids)
        else:
            doc_url, doc_tok, written = _publish_to_feishu(
                title, md_text, chart_path=None, folder_token=folder_token,
                user_openids=user_openids)

        _record_report(user_openid or "", doc_tok, doc_url, title, history_skill)

        summary_text = ' | '.join(summary_parts) if summary_parts else '分析完成'
        print(f"飞书文档: {doc_url}")
        alt_urls = _doc_url_candidates(doc_tok)[1:]
        if alt_urls:
            print(f"备用链接: {alt_urls[0]}")
        print(f"摘要: {summary_text}")
        _notify_report_ready(doc_url, summary_text, user_openid=user_openid)

    except Exception as e:
        print(f"飞书文档创建失败: {e}")
        print(f"\n{md_text}")
        sys.exit(1)

    _save_session(session)


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


EVOLVER_DIR = "/home/admin/evolver"
EVOLVE_MEMORY_DIR = "/home/admin/.openclaw/workspace/memory/evolution"


def cmd_evolve(args: list[str]):
    """EvoMap 演化管理 — run/status/solidify/daemon-start/daemon-stop."""
    import subprocess
    import glob as _glob

    subcmd = args[0] if args else "status"

    if subcmd == "status":
        # Show evolution status summary
        state_file = os.path.join(EVOLVE_MEMORY_DIR, "evolution_state.json")
        solid_file = os.path.join(EVOLVE_MEMORY_DIR, "evolution_solidify_state.json")
        events_file = os.path.join(EVOLVER_DIR, "assets", "gep", "events.jsonl")
        pid_file = os.path.join(EVOLVER_DIR, "evolver.pid")

        print("## EvoMap 演化状态")
        print()

        # Daemon status
        daemon_running = False
        if os.path.exists(pid_file):
            try:
                pid = int(open(pid_file).read().strip())
                os.kill(pid, 0)
                daemon_running = True
                print(f"**守护进程**: 运行中 (PID {pid})")
            except (ProcessLookupError, ValueError):
                print("**守护进程**: 未运行 (残留锁)")
        else:
            print("**守护进程**: 未运行")

        # Cycle count
        if os.path.exists(state_file):
            try:
                st = json.loads(open(state_file).read())
                print(f"**已完成周期**: {st.get('cycleCount', 0)}")
                last_ts = st.get("lastRun", 0)
                if last_ts:
                    from datetime import datetime
                    dt = datetime.fromtimestamp(last_ts / 1000)
                    print(f"**最近运行**: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception:
                pass

        # Events count
        if os.path.exists(events_file):
            with open(events_file) as f:
                lines = [l for l in f if l.strip()]
            evt_count = len(lines)
            print(f"**演化事件**: {evt_count}")
            if lines:
                try:
                    last_evt = json.loads(lines[-1])
                    intent = last_evt.get("intent", "?")
                    genes = last_evt.get("genes_used", ["?"])
                    outcome = last_evt.get("outcome", {}).get("status", "?")
                    print(f"**最近事件**: intent={intent}, gene={genes[0]}, outcome={outcome}")
                except Exception:
                    pass
        else:
            print("**演化事件**: 0")

        # GEP prompts generated
        prompts = sorted(_glob.glob(os.path.join(EVOLVE_MEMORY_DIR, "gep_prompt_*.txt")))
        print(f"**GEP提示**: {len(prompts)} 个")

        # Genes count
        genes_file = os.path.join(EVOLVER_DIR, "assets", "gep", "genes.json")
        if os.path.exists(genes_file):
            try:
                gdata = json.loads(open(genes_file).read())
                genes = gdata.get("genes", [])
                print(f"**基因库**: {len(genes)} 个基因")
                categories = {}
                for g in genes:
                    cat = g.get("category", "unknown")
                    categories[cat] = categories.get(cat, 0) + 1
                cat_str = ", ".join(f"{k}={v}" for k, v in sorted(categories.items()))
                print(f"  分类: {cat_str}")
            except Exception:
                pass

        # HydroMAS health
        try:
            health = _get("/api/gateway/health")
            print(f"**HydroMAS**: {health.get('status', '?')}, Agents={health.get('agents_registered', '?')}")
        except Exception:
            print("**HydroMAS**: 无法连接")

    elif subcmd == "run":
        # Run a single evolution cycle
        print("执行单次演化周期...")
        env = os.environ.copy()
        env["MEMORY_DIR"] = "/home/admin/.openclaw/workspace/memory"
        env["EVOLUTION_DIR"] = EVOLVE_MEMORY_DIR
        env["EVOLVER_LOGS_DIR"] = "/home/admin/.openclaw/workspace/logs"
        env["EVOLVE_STRATEGY"] = env.get("EVOLVE_STRATEGY", "balanced")
        env["EVOLVE_LOAD_MAX"] = "10.0"
        result = subprocess.run(
            ["node", "index.js", "run"],
            cwd=EVOLVER_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Show output
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:
                print(line)
        if result.returncode != 0 and result.stderr:
            print(f"Error: {result.stderr[-500:]}")

        # Show latest prompt if generated
        prompts = sorted(_glob.glob(os.path.join(EVOLVE_MEMORY_DIR, "gep_prompt_*.txt")))
        if prompts:
            latest = prompts[-1]
            print(f"\n最新GEP提示: {latest}")
            try:
                content = open(latest).read()
                # Extract key info
                for line in content.split("\n"):
                    if line.startswith("## Intent") or line.startswith("**Intent"):
                        print(f"  {line.strip()}")
                    elif "gene" in line.lower() and ("selected" in line.lower() or "id" in line.lower()):
                        print(f"  {line.strip()[:100]}")
            except Exception:
                pass

    elif subcmd == "solidify":
        # Solidify the last evolution
        intent = None
        summary = None
        extra_args = []
        i = 0
        while i < len(args[1:]):
            a = args[1 + i]
            if a.startswith("--intent="):
                intent = a.split("=", 1)[1]
            elif a.startswith("--summary="):
                summary = a.split("=", 1)[1]
            elif a == "--dry-run":
                extra_args.append(a)
            i += 1

        cmd_args = ["node", "index.js", "solidify"]
        if intent:
            cmd_args.append(f"--intent={intent}")
        if summary:
            cmd_args.append(f"--summary={summary}")
        cmd_args.extend(extra_args)

        print("固化演化结果...")
        result = subprocess.run(
            cmd_args,
            cwd=EVOLVER_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                print(line)
        if result.returncode != 0:
            print(f"固化失败 (exit={result.returncode})")
            if result.stderr:
                print(result.stderr[-300:])

    elif subcmd == "daemon-start":
        pid_file = os.path.join(EVOLVER_DIR, "evolver.pid")
        if os.path.exists(pid_file):
            try:
                pid = int(open(pid_file).read().strip())
                os.kill(pid, 0)
                print(f"守护进程已在运行 (PID {pid})")
                return
            except (ProcessLookupError, ValueError):
                pass

        env = os.environ.copy()
        env["MEMORY_DIR"] = "/home/admin/.openclaw/workspace/memory"
        env["EVOLUTION_DIR"] = EVOLVE_MEMORY_DIR
        env["EVOLVER_LOGS_DIR"] = "/home/admin/.openclaw/workspace/logs"
        env["EVOLVE_STRATEGY"] = env.get("EVOLVE_STRATEGY", "balanced")
        env["EVOLVE_LOAD_MAX"] = "10.0"
        env["EVOLVER_MIN_SLEEP_MS"] = "30000"
        env["EVOLVER_MAX_SLEEP_MS"] = "600000"

        log_file = "/tmp/evolver-daemon.log"
        with open(log_file, "a") as lf:
            proc = subprocess.Popen(
                ["node", "index.js", "--loop"],
                cwd=EVOLVER_DIR,
                env=env,
                stdout=lf,
                stderr=lf,
                start_new_session=True,
            )
        print(f"演化守护进程已启动 (PID {proc.pid})")
        print(f"日志: {log_file}")

    elif subcmd == "daemon-stop":
        pid_file = os.path.join(EVOLVER_DIR, "evolver.pid")
        if not os.path.exists(pid_file):
            print("守护进程未运行")
            return
        try:
            pid = int(open(pid_file).read().strip())
            os.kill(pid, 15)  # SIGTERM
            print(f"已停止守护进程 (PID {pid})")
            _time.sleep(1)
            try:
                os.remove(pid_file)
            except FileNotFoundError:
                pass
        except ProcessLookupError:
            print("守护进程已不存在，清理锁文件")
            os.remove(pid_file)
        except Exception as e:
            print(f"停止失败: {e}")

    else:
        print("用法: hydromas_call.py evolve [status|run|solidify|daemon-start|daemon-stop]")
        print("  status       — 查看演化状态")
        print("  run          — 执行单次演化周期")
        print("  solidify     — 固化最近演化结果")
        print("  daemon-start — 启动持续演化守护进程")
        print("  daemon-stop  — 停止守护进程")


# ══════════════════════════════════════════════════════════════
# API Skill Wrappers — All endpoints exposed with full params
# ══════════════════════════════════════════════════════════════

# Map: skill_name → {path, method, defaults, description}
_API_SKILLS: dict[str, dict] = {
    # ── Simulation ──
    "simulation_run": {
        "path": "/api/simulation/run",
        "method": "POST",
        "description": "水箱仿真 Tank Simulation",
        "defaults": {
            "duration": 300, "dt": 1.0, "initial_h": 0.5,
            "q_in_profile": [[0, 0.01]],
            "tank_params": {"area": 1.0, "cd": 0.6, "outlet_area": 0.01, "h_max": 2.0},
            "solver": "rk4",
        },
    },
    "simulation_defaults": {
        "path": "/api/simulation/defaults",
        "method": "GET",
        "description": "获取仿真默认参数 Get Simulation Defaults",
        "defaults": {},
    },
    # ── Control ──
    "control_run": {
        "path": "/api/control/run",
        "method": "POST",
        "description": "控制器仿真 Control Simulation (PID/MPC)",
        "defaults": {
            "setpoint": 1.0, "controller_type": "PID",
            "duration": 300, "dt": 1.0, "initial_h": 0.5,
            "params": {"kp": 2.0, "ki": 0.1, "kd": 0.5},
            "tank_params": {"area": 1.0, "cd": 0.6, "outlet_area": 0.01, "h_max": 2.0},
        },
    },
    "control_defaults": {
        "path": "/api/control/defaults",
        "method": "GET",
        "description": "获取控制器默认参数 Get Control Defaults",
        "defaults": {},
    },
    # ── Prediction ──
    "prediction_run": {
        "path": "/api/prediction/run",
        "method": "POST",
        "description": "水位预测 Water Level Prediction",
        "defaults": {
            "historical_data": _WATER_LEVEL_24H,
            "horizon": 60, "model": "linear",
            "lookback": None, "degree": 2,
        },
    },
    "prediction_sample": {
        "path": "/api/prediction/sample-data",
        "method": "GET",
        "description": "获取示例预测数据 Get Sample Prediction Data",
        "defaults": {},
    },
    # ── Scheduling ──
    "scheduling_run": {
        "path": "/api/scheduling/run",
        "method": "POST",
        "description": "调度优化 Scheduling Optimization",
        "defaults": {
            "demand_forecast": [10200, 10400, 10350, 10500, 10380, 10450, 10400],
            "supply_capacity": 10800,
            "method": "lp",
            "constraints": {"min_level": 0.3, "max_level": 1.8},
            "objective": "minimize_cost",
        },
    },
    # ── Evaluation ──
    "evaluation_performance": {
        "path": "/api/evaluation/performance",
        "method": "POST",
        "description": "性能评价 Performance Evaluation",
        "defaults": {
            "observed": [1.0, 0.95, 0.90, 0.85, 0.80, 0.78, 0.76, 0.75, 0.74, 0.74],
            "predicted": [1.0, 0.96, 0.91, 0.86, 0.81, 0.79, 0.77, 0.76, 0.75, 0.74],
            "metrics": ["RMSE", "MAE", "NSE"],
            "time_series": None, "setpoint": None,
        },
    },
    "evaluation_wnal": {
        "path": "/api/evaluation/wnal",
        "method": "POST",
        "description": "WNAL水网自主等级评估 WNAL Assessment",
        "defaults": {
            "capabilities": {
                "sensing": 65, "communication": 70, "modeling": 55,
                "prediction": 60, "control": 50, "odd_monitoring": 45,
                "decision_support": 40,
            },
        },
    },
    # ── Design ──
    "design_sensitivity": {
        "path": "/api/design/sensitivity",
        "method": "POST",
        "description": "参数敏感性分析 Sensitivity Analysis",
        "defaults": {
            "base_params": {"area": 1.0, "cd": 0.6, "outlet_area": 0.01, "q_in": 0.01},
            "param_ranges": {
                "area": [0.5, 2.0], "cd": [0.4, 0.8],
                "outlet_area": [0.005, 0.02], "q_in": [0.005, 0.02],
            },
            "method": "OAT", "n_levels": 10,
        },
    },
    "design_sizing": {
        "path": "/api/design/sizing",
        "method": "POST",
        "description": "水箱容量设计 Tank Sizing",
        "defaults": {
            "demand_peak": 0.03, "duration_hours": 4.0, "safety_factor": 1.2,
        },
    },
    # ── DataClean ──
    "dataclean_outliers": {
        "path": "/api/dataclean/outliers",
        "method": "POST",
        "description": "异常值检测 Outlier Detection",
        "defaults": {
            "data": [1.0, 0.98, 0.95, 5.0, 0.90, 0.88, 0.85, 0.83, 0.80, 0.78],
            "method": "3sigma", "threshold": 3.0,
        },
    },
    "dataclean_interpolate": {
        "path": "/api/dataclean/interpolate",
        "method": "POST",
        "description": "缺失值插值 Gap Interpolation",
        "defaults": {
            "data": [1.0, 0.98, None, 0.93, None, None, 0.85, 0.83, 0.80, 0.78],
            "method": "linear",
        },
    },
    # ── Identification ──
    "identification_run": {
        "path": "/api/identification/run",
        "method": "POST",
        "description": "系统辨识 System Identification",
        "defaults": {
            "observed_h": [0.5, 0.48, 0.46, 0.44, 0.42, 0.41, 0.40, 0.39, 0.38, 0.38],
            "observed_q_out": [0.0042, 0.0041, 0.0040, 0.0039, 0.0038, 0.0038,
                               0.0037, 0.0037, 0.0036, 0.0036],
            "model_type": "nonlinear",
            "initial_guess": None,
        },
    },
    "identification_arx": {
        "path": "/api/identification/arx",
        "method": "POST",
        "description": "ARX模型辨识 ARX Model Identification",
        "defaults": {
            "y": [0.5, 0.48, 0.46, 0.44, 0.42, 0.41, 0.40, 0.39, 0.38, 0.38],
            "u": [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            "na": 2, "nb": 2,
        },
    },
    # ── Water Balance ──
    "water_balance_calc": {
        "path": "/api/water-balance/calc",
        "method": "POST",
        "description": "水平衡计算 Water Balance Calculation",
        "defaults": {
            "nodes_data": _ALUMINA_NODES,
            "edges_data": _ALUMINA_EDGES,
        },
    },
    "water_balance_anomaly": {
        "path": "/api/water-balance/anomaly",
        "method": "POST",
        "description": "水平衡异常检测 Water Balance Anomaly Detection",
        "defaults": {
            "nodes_data": _ALUMINA_NODES,
            "edges_data": _ALUMINA_EDGES,
        },
    },
    # ── Evaporation ──
    "evaporation_predict": {
        "path": "/api/evaporation/predict",
        "method": "POST",
        "description": "蒸发量预测 Evaporation Prediction",
        "defaults": {
            "tower_params": _TOWER_PARAMS,
            "weather": _WEATHER,
        },
    },
    # ── Leak Detection ──
    "leak_detection_detect": {
        "path": "/api/leak-detection/detect",
        "method": "POST",
        "description": "泄漏检测 Leak Detection",
        "defaults": {
            "graph_nodes": [
                {"id": n["node_id"], "q_in": n["q_in"], "q_out": n["q_out"],
                 "q_loss": n["q_loss"]}
                for n in _ALUMINA_NODES
            ],
            "graph_edges": [
                {"source": e[0], "target": e[1], "flow": 100}
                for e in _ALUMINA_EDGES
            ],
            "threshold": 0.95,
        },
    },
    "leak_detection_localize": {
        "path": "/api/leak-detection/localize",
        "method": "POST",
        "description": "泄漏定位 Leak Localization",
        "defaults": {
            "graph_nodes": [
                {"id": n["node_id"], "q_in": n["q_in"], "q_out": n["q_out"],
                 "q_loss": n["q_loss"]}
                for n in _ALUMINA_NODES
            ],
            "graph_edges": [
                {"source": e[0], "target": e[1], "flow": 100}
                for e in _ALUMINA_EDGES
            ],
            "threshold": 0.95,
        },
    },
    # ── Reuse ──
    "reuse_match": {
        "path": "/api/reuse/match",
        "method": "POST",
        "description": "回用水源匹配 Reuse Water Source Matching",
        "defaults": {
            "source_quality": {"tds": 800, "ph": 12, "cod": 50},
            "target_requirements": [
                {"id": "cooling_towers", "flow_m3d": 4200,
                 "quality_req": {"tds_max": 1000, "ph_range": [6, 10]}},
                {"id": "ws_raw_material", "flow_m3d": 400,
                 "quality_req": {"tds_max": 2000}},
            ],
        },
    },
    "reuse_optimize": {
        "path": "/api/reuse/optimize",
        "method": "POST",
        "description": "回用方案优化 Reuse Scheduling Optimization",
        "defaults": {
            "source_quality": {"tds": 800, "ph": 12, "cod": 50},
            "target_requirements": [
                {"id": "cooling_towers", "flow_m3d": 4200,
                 "quality_req": {"tds_max": 1000, "ph_range": [6, 10]}},
                {"id": "ws_raw_material", "flow_m3d": 400,
                 "quality_req": {"tds_max": 2000}},
            ],
        },
    },
    # ── ODD ──
    "odd_check": {
        "path": "/api/odd/check",
        "method": "POST",
        "description": "ODD安全边界检查 ODD Safety Check",
        "defaults": {
            "state": {
                "water_level": 1.2, "inflow_rate": 0.01,
                "outflow_rate": 0.008, "pressure": 101.3,
            },
            "odd_config": None,
        },
    },
    "odd_check_series": {
        "path": "/api/odd/check-series",
        "method": "POST",
        "description": "ODD时序安全检查 ODD Time-Series Check",
        "defaults": {
            "states": [
                {"water_level": 1.2, "inflow_rate": 0.01},
                {"water_level": 1.3, "inflow_rate": 0.01},
                {"water_level": 1.5, "inflow_rate": 0.012},
                {"water_level": 1.7, "inflow_rate": 0.015},
            ],
            "times": [0, 60, 120, 180],
            "odd_config": None,
        },
    },
    "odd_mrc_plan": {
        "path": "/api/odd/mrc-plan",
        "method": "POST",
        "description": "最小风险方案 MRC Plan",
        "defaults": {
            "state": {
                "water_level": 1.9, "inflow_rate": 0.02,
                "outflow_rate": 0.005,
            },
            "odd_config": None,
        },
    },
    "odd_specs": {
        "path": "/api/odd/specs",
        "method": "GET",
        "description": "获取ODD规格 Get ODD Specifications",
        "defaults": {},
    },
    # ── Dispatch ──
    "dispatch_optimize": {
        "path": "/api/dispatch/optimize",
        "method": "POST",
        "description": "全局调度优化 Global Dispatch Optimization",
        "defaults": {
            "demand_forecast": {"total": 10400, "peak": 500, "duration_h": 24},
            "supply_config": {
                "wujiang": {"capacity": 7800},
                "flood_channel": {"capacity": 2600},
            },
            "reuse_config": {"capacity": 2400, "rate": 0.36},
            "method": "lp",
        },
    },
    # ── Report ──
    "report_tank_analysis": {
        "path": "/api/report/tank-analysis",
        "method": "POST",
        "description": "水箱综合分析报告 Tank Analysis Report",
        "defaults": {
            "title": "双容水箱仿真",
            "duration": 300, "dt": 1.0, "initial_h": 0.5,
            "tank_params": {"area": 1.0, "cd": 0.6, "outlet_area": 0.01, "h_max": 2.0},
            "q_in_profile": [[0, 0.01]],
        },
    },
    "report_daily": {
        "path": "/api/report/daily",
        "method": "POST",
        "description": "日运营报告 Daily Operations Report",
        "defaults": {
            "date": "2026-03-01",
            "include_sections": ["balance", "anomaly", "kpi", "evaporation", "reuse"],
        },
    },
    # ── Chart ──
    "chart_render": {
        "path": "/api/chart/render",
        "method": "POST",
        "description": "渲染过程线图 Render Chart",
        "defaults": {
            "time": list(range(0, 301)),
            "water_level": [0.5 * (0.99 ** t) for t in range(301)],
            "outflow": [], "inflow": [],
            "title": "HydroMAS Chart",
        },
    },
    "chart_simulate_and_chart": {
        "path": "/api/chart/simulate-and-chart",
        "method": "POST",
        "description": "仿真+图表一键生成 Simulate & Chart",
        "defaults": {
            "duration": 300, "initial_h": 0.5, "title": "水箱仿真结果",
        },
    },
    "chart_schematic": {
        "path": "/api/chart/schematic",
        "method": "POST",
        "description": "水箱示意图 Tank Schematic",
        "defaults": {
            "tank_area_m2": 1.0, "initial_h_m": 0.5,
            "outlet_area_m2": 0.01, "discharge_coeff": 0.6,
            "q_in_m3s": 0.01, "h_max_m": 2.0,
        },
    },
}


def cmd_api(args: list[str]):
    """Call any HydroMAS API endpoint as a skill.

    Usage:
        hydromas_call.py api <skill_name> ['{...}']
        hydromas_call.py api list
        hydromas_call.py api <skill_name> --show-defaults

    Examples:
        hydromas_call.py api simulation_run '{"initial_h": 1.0, "duration": 600}'
        hydromas_call.py api control_run '{"controller_type": "MPC", "setpoint": 1.5}'
        hydromas_call.py api evaluation_wnal
        hydromas_call.py api odd_check '{"state": {"water_level": 1.8}}'
    """
    if not args or args[0] == "list":
        # List all API skills
        print("## HydroMAS API Skills\n")
        print("| Skill | Endpoint | Description |")
        print("|-------|----------|-------------|")
        for name, info in sorted(_API_SKILLS.items()):
            print(f"| {name} | {info['method']} {info['path']} | {info['description']} |")
        print(f"\n共 {len(_API_SKILLS)} 个 API 技能")
        print("\n用法: hydromas_call.py api <skill_name> ['{\"param\":\"value\"}']")
        print("查看默认参数: hydromas_call.py api <skill_name> --show-defaults")
        return

    skill_name = args[0]
    if skill_name not in _API_SKILLS:
        print(f"Unknown API skill: {skill_name}")
        print(f"Available: {', '.join(sorted(_API_SKILLS.keys()))}")
        sys.exit(1)

    skill_info = _API_SKILLS[skill_name]

    # Show defaults
    if len(args) > 1 and args[1] == "--show-defaults":
        print(f"## {skill_info['description']}")
        print(f"Endpoint: {skill_info['method']} {skill_info['path']}\n")
        print("默认参数:")
        print(json.dumps(skill_info["defaults"], ensure_ascii=False, indent=2))
        return

    # Parse user overrides
    user_params = {}
    if len(args) > 1 and args[1] != "--show-defaults":
        try:
            user_params = json.loads(args[1])
        except json.JSONDecodeError as e:
            print(f"JSON 解析错误: {e}")
            sys.exit(1)

    # Merge: defaults + user overrides
    merged = {}
    _deep_merge(merged, skill_info["defaults"])
    _deep_merge(merged, user_params)

    # Call API
    method = skill_info["method"]
    path = skill_info["path"]

    if method == "GET":
        result = _get(path)
    else:
        result = _post(path, merged)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    # Handle binary results (charts return base64)
    if "chart_base64" in result:
        png_data = base64.b64decode(result["chart_base64"])
        chart_path = _save_chart(png_data, skill_name)
        print(f"Chart saved: {chart_path}")
        # Also print summary if available
        if "summary" in result:
            print(_format_sim_summary(result["summary"]))
        return

    # Format output
    print(f"## {skill_info['description']}\n")
    if isinstance(result, dict):
        print(_format_result(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def _collect_report_images(case_id: str, role: str) -> list[dict]:
    """Collect pre-generated concept and flow diagram images for this role×case."""
    images = []
    img_dir = _REPORT_IMAGE_DIR

    # Nano concept image → after executive summary
    nano_path = os.path.join(img_dir, f"nano_{case_id}_{role}.png")
    if os.path.exists(nano_path):
        images.append({"path": nano_path, "after_section": "执行摘要"})

    # Mermaid flow diagram → after "系统架构" or "分析流程" section
    mermaid_path = os.path.join(img_dir, f"mermaid_{case_id}_{role}.png")
    if os.path.exists(mermaid_path):
        images.append({"path": mermaid_path, "after_section": "分析框架"})

    return images


def cmd_full_report(args: list[str]):
    """Generate a comprehensive multi-skill report for a role×case combination.

    Usage: hydromas_call.py full-report --role operator --case alumina [--folder TOKEN] [--user-openid ID]

    Runs ALL applicable skills for the given case, aggregates results,
    generates role-specific LLM executive summary and per-skill interpretations,
    embeds concept diagrams and flow charts,
    publishes one comprehensive Feishu document.
    """
    role = "operator"
    case_id = "alumina"
    folder_token = None
    user_openid = None

    i = 0
    while i < len(args):
        if args[i] == "--role" and i + 1 < len(args):
            role = args[i + 1]; i += 2
        elif args[i] == "--case" and i + 1 < len(args):
            case_id = args[i + 1]; i += 2
        elif args[i] == "--folder" and i + 1 < len(args):
            folder_token = args[i + 1]; i += 2
        elif args[i] == "--user-openid" and i + 1 < len(args):
            user_openid = args[i + 1]; i += 2
        else:
            i += 1

    if case_id not in CASE_PROFILES:
        print(f"Unknown case: {case_id}. Available: {list(CASE_PROFILES.keys())}")
        sys.exit(1)
    has_feishu_creds = _print_feishu_credential_status("full-report")
    if not has_feishu_creds:
        print(
            "Error: Missing Feishu credentials; set FEISHU_APP_ID/FEISHU_APP_SECRET "
            "via env or .env/AGENTS.md before full-report.",
            file=sys.stderr,
        )
        sys.exit(2)

    profile = CASE_PROFILES[case_id]
    case_name = profile["name"]
    role_name = _ROLE_NAMES.get(role, role)
    role_style = _ROLE_REPORT_STYLE.get(role, {})
    applicable = profile["applicable_skills"]
    user_openids = [user_openid] if user_openid else None

    from datetime import datetime
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    title_suffix = role_style.get("title_suffix", "综合分析报告")
    icon = role_style.get("icon", "")

    print(f"[综合报告] {role_name} × {case_name}，共 {len(applicable)} 个分析场景", file=sys.stderr)

    # ── Run all applicable skills ──
    skill_results: list[tuple[str, dict]] = []
    skill_charts: list[str] = []

    for sn in applicable:
        defaults = _get_skill_defaults(sn, case_id)
        print(f"  → 运行 {sn}...", end="", file=sys.stderr, flush=True)
        res = _post("/api/gateway/skill", {
            "skill_name": sn,
            "params": defaults,
            "role": role,
        })
        if "error" in res:
            print(f" ✗ ({res['error'][:50]})", file=sys.stderr)
            continue
        inner = res.get("result", {})
        if isinstance(inner, dict) and inner.get("success") is False:
            print(f" ✗ (skill failed)", file=sys.stderr)
            continue
        skill_results.append((sn, res))
        charts = _auto_detect_charts(res)
        skill_charts.extend(charts)
        print(f" ✓", file=sys.stderr)

    if not skill_results:
        print("所有技能执行失败，无法生成报告。")
        sys.exit(1)

    print(f"[综合报告] {len(skill_results)}/{len(applicable)} 个场景完成，"
          f"正在生成 AI 分析...", file=sys.stderr)

    # ── Generate LLM executive summary ──
    exec_summary = _llm_executive_summary(role, case_id, skill_results)

    # ── Generate per-skill LLM interpretations (parallel) ──
    interpretations = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        for sn, res in skill_results:
            question = f"{case_name}{_humanize_key(sn)}分析"
            f = pool.submit(_llm_interpret_result, question, res, sn, role, case_id)
            futures[sn] = f
        for sn, f in futures.items():
            try:
                interpretations[sn] = f.result()
            except Exception:
                interpretations[sn] = None

    # ── Build role-specific comprehensive report ──
    report_intro = role_style.get("intro", "")

    lines = [
        f"# {icon} {case_name} · {title_suffix}",
        "",
        f"> **生成时间**: {now_str}",
        f"> **角色视角**: {role_name}",
        f"> **分析案例**: {case_name}",
        f"> **覆盖场景**: {len(skill_results)} 个分析模块",
        "",
    ]

    if report_intro:
        lines += [report_intro, ""]

    lines += ["---", ""]

    # ── Executive summary (conclusion first!) ──
    if exec_summary:
        lines += [
            "## 执行摘要",
            "",
            exec_summary,
            "",
            "---",
            "",
        ]

    # ── Analysis framework section (image placeholder for mermaid) ──
    lines += [
        "## 分析框架",
        "",
        f"本报告基于 HydroMAS 五层架构平台，从{role_name}视角对{case_name}系统进行"
        f"全面分析，覆盖 {len(skill_results)} 个分析模块。下图展示了本报告的分析框架与数据流向：",
        "",
        "*（分析流程图）*",
        "",
        "---",
        "",
    ]

    # ── Per-skill sections with role-specific framing ──
    section_style = role_style.get("section_style", "dashboard")

    for idx, (sn, res) in enumerate(skill_results):
        sn_label = _humanize_key(sn)

        # Role-specific section header
        if section_style == "dashboard":
            lines += [f"## {sn_label}", ""]
        elif section_style == "academic":
            lines += [f"## {idx + 1}. {sn_label}", ""]
        elif section_style == "specification":
            lines += [f"## {sn_label} — 设计分析", ""]
        else:
            lines += [f"## {sn_label}", ""]

        # Per-skill AI interpretation FIRST (conclusion-first for all roles)
        interp = interpretations.get(sn)
        if interp:
            if section_style == "dashboard":
                lines += ["### 运维要点", "", interp, ""]
            elif section_style == "academic":
                lines += ["### 分析结论", "", interp, ""]
            elif section_style == "specification":
                lines += ["### 设计评估", "", interp, ""]
            else:
                lines += ["### AI 解读", "", interp, ""]

        # Skill data detail
        if section_style == "dashboard":
            lines += ["### 详细数据", ""]
        elif section_style == "academic":
            lines += ["### 数据与结果", ""]
        elif section_style == "specification":
            lines += ["### 参数明细", ""]
        else:
            lines += ["### 详细数据", ""]

        sub_lines = []
        data = res
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], dict):
                exec_info = []
                if "steps_completed" in data:
                    exec_info.append(f"完成步骤: {data['steps_completed']}")
                if "execution_time" in data:
                    exec_info.append(f"耗时: {data['execution_time']:.1f}s")
                if exec_info:
                    sub_lines.append(f"*{' | '.join(exec_info)}*")
                    sub_lines.append("")
                data = data["data"]
            elif "result" in data and isinstance(data["result"], dict):
                inner = data["result"]
                data = inner.get("data", inner)

        if isinstance(data, dict):
            if "report_markdown" in data:
                sub_lines.append(data["report_markdown"])
            else:
                data = _trim_large_data(data)
                _render_dict_to_md(data, sub_lines, level=4)
        elif isinstance(data, str):
            sub_lines.append(data)

        lines.extend(sub_lines)
        lines += ["", "---", ""]

    # ── Footer ──
    lines += [
        f"*{icon} 本报告由 HydroMAS 五层架构平台自动生成*",
        f"*{role_name}视角 | {case_name} | {len(skill_results)} 个分析场景 | {now_str}*",
    ]

    md_text = "\n".join(lines)

    # ── Collect all images: concept + flow + charts ──
    images = _collect_report_images(case_id, role)
    images.extend({"path": p, "after_section": ""} for p in skill_charts if p)

    title = f"HydroMAS · {case_name} · {title_suffix} ({now_str})"

    print(f"[综合报告] 准备发布，{len(images)} 张图表", file=sys.stderr)

    # ── Publish to Feishu ──
    try:
        if images:
            doc_url, doc_tok, written = _publish_report_to_feishu(
                title, md_text, images, folder_token, user_openids)
        else:
            doc_url, doc_tok, written = _publish_to_feishu(
                title, md_text, chart_path=None, folder_token=folder_token,
                user_openids=user_openids)
        _record_report(user_openid or "", doc_tok, doc_url, title,
                       f"full_report_{case_id}_{role}")
        summary_text = (
            f"{case_name}·{title_suffix}，{len(skill_results)} 个场景，{len(images)} 张图表"
        )
        print(f"飞书文档: {doc_url}")
        alt_urls = _doc_url_candidates(doc_tok)[1:]
        if alt_urls:
            print(f"备用链接: {alt_urls[0]}")
        print(f"摘要: {summary_text}")
        _notify_report_ready(doc_url, summary_text, user_openid=user_openid)
    except Exception as e:
        print(f"飞书文档创建失败: {e}")
        # Save locally
        local_path = f"/tmp/hydromas_full_{case_id}_{role}.md"
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        print(f"报告已保存到: {local_path}")
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
        "full-report": cmd_full_report,
        "sim": cmd_sim,
        "skill": cmd_skill,
        "skills": cmd_skills,
        "health": cmd_health,
        "roles": cmd_roles,
        "history": cmd_history,
        "evolve": cmd_evolve,
        "api": cmd_api,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    cmd_text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "help"
    notify_target_openid = _resolve_notify_target_openid(sys.argv[1:])
    started_at = _time.time()
    notify_status = "failed"
    notify_summary = f"HydroMAS task failed: {cmd_text}"
    try:
        main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if code == 0:
            notify_status = "success"
            notify_summary = f"HydroMAS task succeeded: {cmd_text}"
        else:
            notify_status = "failed"
            notify_summary = f"HydroMAS task failed (exit={code}): {cmd_text}"
        raise
    except Exception as exc:
        notify_status = "failed"
        notify_summary = f"HydroMAS task failed ({type(exc).__name__}): {cmd_text}"
        raise
    else:
        notify_status = "success"
        notify_summary = f"HydroMAS task succeeded: {cmd_text}"
    finally:
        duration_sec = _time.time() - started_at
        notify_feishu(
            notify_status,
            notify_summary,
            duration_sec=duration_sec,
            user_openid=notify_target_openid,
        )
