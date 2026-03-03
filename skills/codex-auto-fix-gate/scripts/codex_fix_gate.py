#!/usr/bin/env python3
import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


STATE_PATH = Path.home() / ".openclaw" / "workspace" / ".state" / "codex-auto-fix-gate-state.json"
LOCK_PATH = Path.home() / ".openclaw" / "workspace" / ".state" / "codex-auto-fix-gate.lock"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(ts: dt.datetime) -> str:
    return ts.isoformat()


def parse_iso(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "calls_today": {"date": utcnow().date().isoformat(), "count": 0},
            "last_called_at": None,
            "consecutive_failures": 0,
            "circuit_open_until": None,
            "recent": [],
        }
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "calls_today": {"date": utcnow().date().isoformat(), "count": 0},
            "last_called_at": None,
            "consecutive_failures": 0,
            "circuit_open_until": None,
            "recent": [],
        }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_daily_counter_if_needed(state: dict) -> None:
    today = utcnow().date().isoformat()
    if (state.get("calls_today") or {}).get("date") != today:
        state["calls_today"] = {"date": today, "count": 0}


def build_fingerprint(payload: dict) -> str:
    basis = {
        "task": payload.get("task", ""),
        "severity": payload.get("severity", "medium"),
        "cwd": payload.get("cwd", ""),
        "changed_files": int(payload.get("changed_files", 0) or 0),
        "failing_tests": int(payload.get("failing_tests", 0) or 0),
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def complexity_score(payload: dict) -> int:
    severity = str(payload.get("severity", "medium")).lower().strip()
    severity_score = {"low": 1, "medium": 2, "high": 4, "critical": 6}.get(severity, 2)
    changed_files = max(0, int(payload.get("changed_files", 0) or 0))
    failing_tests = max(0, int(payload.get("failing_tests", 0) or 0))
    has_stacktrace = bool(payload.get("has_stacktrace", False))
    recent_failures = max(0, int(payload.get("recent_failures", 0) or 0))

    score = severity_score
    score += min(4, changed_files)  # max +4
    score += min(6, failing_tests * 2)  # max +6
    score += 1 if has_stacktrace else 0
    score += min(2, recent_failures)
    return score


def evaluate(payload: dict, state: dict, cfg: dict) -> dict:
    now = utcnow()
    reset_daily_counter_if_needed(state)

    if os.environ.get("OPENCLAW_CODEX_GATE_ACTIVE") == "1":
        return {"should_call": False, "reason": "recursion_guard"}

    codex_bin = cfg["codex_bin"]
    if not shutil.which(codex_bin):
        return {"should_call": False, "reason": f"codex_cli_missing:{codex_bin}"}

    # Busy lock to avoid parallel codex runs and background pile-up.
    if LOCK_PATH.exists():
        try:
            lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            pid = int(lock.get("pid", 0) or 0)
            if pid > 0:
                os.kill(pid, 0)
                return {"should_call": False, "reason": "codex_busy", "pid": pid}
        except ProcessLookupError:
            try:
                LOCK_PATH.unlink()
            except Exception:
                pass
        except Exception:
            pass

    # Circuit breaker
    open_until = parse_iso(state.get("circuit_open_until") or "")
    if open_until and now < open_until:
        return {
            "should_call": False,
            "reason": "circuit_open",
            "circuit_open_until": iso(open_until),
        }

    # Daily budget
    count_today = int((state.get("calls_today") or {}).get("count", 0))
    if count_today >= cfg["daily_budget"]:
        return {
            "should_call": False,
            "reason": "daily_budget_exceeded",
            "calls_today": count_today,
            "daily_budget": cfg["daily_budget"],
        }

    # Cooldown
    last_called = parse_iso(state.get("last_called_at") or "")
    if last_called:
        elapsed_min = int((now - last_called).total_seconds() // 60)
        if elapsed_min < cfg["cooldown_minutes"]:
            return {
                "should_call": False,
                "reason": "cooldown_active",
                "elapsed_minutes": elapsed_min,
                "cooldown_minutes": cfg["cooldown_minutes"],
            }

    # Duplicate suppression window
    fingerprint = build_fingerprint(payload)
    dedupe_hours = cfg["duplicate_window_hours"]
    for rec in state.get("recent", []):
        if rec.get("fingerprint") != fingerprint:
            continue
        ts = parse_iso(rec.get("ts", ""))
        if not ts:
            continue
        age_hours = (now - ts).total_seconds() / 3600.0
        if age_hours <= dedupe_hours and str(payload.get("severity", "medium")).lower() not in ("high", "critical"):
            return {
                "should_call": False,
                "reason": "duplicate_suppressed",
                "fingerprint": fingerprint,
                "age_hours": round(age_hours, 2),
            }

    score = complexity_score(payload)
    severity = str(payload.get("severity", "medium")).lower()
    threshold = cfg["complexity_threshold"]
    should_call = score >= threshold or severity in ("high", "critical")
    if not should_call:
        return {
            "should_call": False,
            "reason": "complexity_below_threshold",
            "score": score,
            "threshold": threshold,
        }

    return {
        "should_call": True,
        "reason": "allowed",
        "score": score,
        "threshold": threshold,
        "fingerprint": fingerprint,
    }


def append_recent(state: dict, fingerprint: str, status: str, detail: str = "") -> None:
    now = iso(utcnow())
    recent = state.get("recent") or []
    recent.append({"ts": now, "fingerprint": fingerprint, "status": status, "detail": detail[:200]})
    state["recent"] = recent[-80:]


def record_result(state: dict, allowed_eval: dict, success: bool, detail: str, cfg: dict) -> None:
    now = utcnow()
    reset_daily_counter_if_needed(state)
    state["last_called_at"] = iso(now)
    state["calls_today"]["count"] = int(state["calls_today"]["count"]) + 1

    fp = allowed_eval.get("fingerprint", "unknown")
    if success:
        state["consecutive_failures"] = 0
        state["circuit_open_until"] = None
        append_recent(state, fp, "success", detail)
    else:
        fails = int(state.get("consecutive_failures", 0)) + 1
        state["consecutive_failures"] = fails
        append_recent(state, fp, "failure", detail)
        if fails >= cfg["failure_breaker_threshold"]:
            state["circuit_open_until"] = iso(now + dt.timedelta(minutes=cfg["breaker_minutes"]))


def load_payload(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "task" not in data:
        raise ValueError("input JSON must contain field: task")
    return data


def get_cfg(args) -> dict:
    return {
        "codex_bin": args.codex_bin,
        "cooldown_minutes": args.cooldown_minutes,
        "daily_budget": args.daily_budget,
        "failure_breaker_threshold": args.failure_breaker_threshold,
        "breaker_minutes": args.breaker_minutes,
        "complexity_threshold": args.complexity_threshold,
        "duplicate_window_hours": args.duplicate_window_hours,
    }


def cmd_status(_args) -> int:
    state = load_state()
    reset_daily_counter_if_needed(state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_decide(args) -> int:
    payload = load_payload(args.input)
    state = load_state()
    cfg = get_cfg(args)
    result = evaluate(payload, state, cfg)
    out = {"decision": result, "policy": cfg}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if result.get("should_call") else 2


def cmd_run(args) -> int:
    payload = load_payload(args.input)
    state = load_state()
    cfg = get_cfg(args)
    decision = evaluate(payload, state, cfg)

    if not decision.get("should_call"):
        print(json.dumps({"executed": False, "decision": decision}, ensure_ascii=False, indent=2))
        return 0

    prompt = ""
    if args.prompt:
        prompt = args.prompt
    elif args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    else:
        prompt = (
            "Fix the reported code issue with minimal safe changes, run targeted validation, "
            "and summarize changed files + why."
        )

    cwd = payload.get("cwd") or os.getcwd()
    cmd = [
        cfg["codex_bin"],
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "--json",
        "--color",
        "never",
        "-C",
        str(cwd),
        prompt,
    ]
    env = os.environ.copy()
    env["OPENCLAW_CODEX_GATE_ACTIVE"] = "1"
    env["CI"] = env.get("CI", "1")
    env["TERM"] = env.get("TERM", "dumb")

    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        LOCK_PATH.write_text(json.dumps({"pid": proc.pid, "ts": iso(utcnow())}), encoding="utf-8")
        timeout_s = int(args.max_runtime_seconds)
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
            returncode = proc.returncode
            ok = returncode == 0
            detail = (stderr or stdout or "").strip()
        except subprocess.TimeoutExpired:
            ok = False
            detail = f"codex_timeout_after_{timeout_s}s"
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                stdout, stderr = proc.communicate(timeout=8)
            except Exception:
                stdout, stderr = "", detail
            returncode = 124
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass

        record_result(state, decision, ok, detail, cfg)
        save_state(state)
        print(
            json.dumps(
                {
                    "executed": True,
                    "ok": ok,
                    "returncode": returncode,
                    "timeout_seconds": int(args.max_runtime_seconds),
                    "decision": decision,
                    "command": cmd,
                    "stdout_tail": (stdout or "")[-2000:],
                    "stderr_tail": (stderr or "")[-2000:],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if ok else 1
    except Exception as e:
        record_result(state, decision, False, str(e), cfg)
        save_state(state)
        print(json.dumps({"executed": True, "ok": False, "decision": decision, "error": str(e)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        try:
            if LOCK_PATH.exists():
                LOCK_PATH.unlink()
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Gate Codex auto-fix calls with cooldown/budget/breaker policy.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_policy_args(sp):
        sp.add_argument("--codex-bin", default="codex")
        sp.add_argument("--cooldown-minutes", type=int, default=30)
        sp.add_argument("--daily-budget", type=int, default=4)
        sp.add_argument("--failure-breaker-threshold", type=int, default=2)
        sp.add_argument("--breaker-minutes", type=int, default=90)
        sp.add_argument("--complexity-threshold", type=int, default=6)
        sp.add_argument("--duplicate-window-hours", type=int, default=6)

    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)

    d = sub.add_parser("decide")
    d.add_argument("--input", required=True, help="Path to fix_request.json")
    add_policy_args(d)
    d.set_defaults(fn=cmd_decide)

    r = sub.add_parser("run")
    r.add_argument("--input", required=True, help="Path to fix_request.json")
    r.add_argument("--prompt", help="Inline Codex prompt")
    r.add_argument("--prompt-file", help="Prompt file path")
    r.add_argument("--max-runtime-seconds", type=int, default=1200, help="Hard timeout for codex exec process.")
    add_policy_args(r)
    r.set_defaults(fn=cmd_run)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
