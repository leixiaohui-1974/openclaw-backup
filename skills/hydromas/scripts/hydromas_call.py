#!/usr/bin/env python3
"""HydroMAS CLI — OpenClaw 技能调用脚本。

用法:
    python3 hydromas_call.py chat "自然语言问题" [--role operator|researcher|designer]
    python3 hydromas_call.py skill <技能名> ['{"param":"value"}']
    python3 hydromas_call.py skills [--role operator]
    python3 hydromas_call.py health
    python3 hydromas_call.py roles
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
TIMEOUT = 120


def _post(path: str, data: dict) -> dict:
    """POST JSON to HydroMAS API."""
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


def _get(path: str) -> dict:
    """GET from HydroMAS API."""
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"error": str(e)}


def _format_result(data: dict, indent: int = 0) -> str:
    """Format dict as readable Markdown."""
    if "error" in data:
        return f"**Error**: {data['error']}"
    lines = []
    for k, v in data.items():
        prefix = "  " * indent
        if isinstance(v, dict):
            lines.append(f"{prefix}**{k}**:")
            lines.append(_format_result(v, indent + 1))
        elif isinstance(v, list):
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


def cmd_chat(args: list[str]):
    """Natural language chat with HydroMAS."""
    if not args:
        print("Usage: hydromas_call.py chat \"your question\" [--role operator|researcher|designer]")
        sys.exit(1)

    message = args[0]
    role = "operator"

    for i, a in enumerate(args[1:], 1):
        if a == "--role" and i < len(args):
            role = args[i + 1] if i + 1 < len(args) else "operator"

    result = _post("/api/gateway/chat", {
        "message": message,
        "role": role,
        "session_id": "",
        "params": {},
    })

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    # Format output
    print(f"## HydroMAS ({role})\n")
    if isinstance(result.get("response"), str):
        print(result["response"])
    elif isinstance(result.get("result"), dict):
        print(_format_result(result["result"]))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


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


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "chat": cmd_chat,
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
