#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_TOPIC = "调度员会被AI取代吗？水网协同真相"
DEFAULT_DOC_TOKEN = ""
DEFAULT_USER_OPENID = "ou_607e1555930b5636c8b88b176b9d3bf2"

RUNNER_STATE_FILE = "job_state.json"
RUN_REPORT_FILE = "run_report.json"

RUN_SCRIPT = Path.home() / ".openclaw/workspace/skills/wechat-article-writing/scripts/run.py"
GEN_IMAGES_SCRIPT = Path.home() / ".openclaw/workspace/skills/wx-nano-image-pack/scripts/generate_wx_images.py"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _classify_failure(text: str) -> str:
    t = (text or "").lower()
    if "timed out" in t or "timeout" in t:
        return "timeout"
    if "429" in t or "rate limit" in t:
        return "rate_limit"
    if "401" in t or "403" in t or "permission" in t or "unauthorized" in t:
        return "auth_or_permission"
    if "connection" in t or "econnrefused" in t or "temporarily unavailable" in t:
        return "network"
    return "unknown"


def _run_cmd(cmd: List[str], timeout_s: int) -> Tuple[bool, str]:
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s)
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    return p.returncode == 0, out


def _base_run_cmd(args, output_dir: Path) -> List[str]:
    cmd = [
        "python3", str(RUN_SCRIPT),
        "--topic", args.topic,
        "--doc-token", args.doc_token,
        "--output-dir", str(output_dir),
        "--user-openid", args.user_openid,
        "--image-model-strategy", args.image_model_strategy,
        "--image-resolution", args.image_resolution,
    ]
    if args.feishu_app_id:
        cmd += ["--feishu-app-id", args.feishu_app_id]
    if args.feishu_app_secret:
        cmd += ["--feishu-app-secret", args.feishu_app_secret]
    return cmd


def _parse_indices(s: str) -> List[int]:
    out = []
    for p in s.split(","):
        p = p.strip()
        if not p:
            continue
        if not p.isdigit():
            continue
        out.append(int(p))
    return sorted(set(out))


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable wechat article workflow runner")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--doc-token", default=DEFAULT_DOC_TOKEN)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--user-openid", default=DEFAULT_USER_OPENID)
    parser.add_argument("--feishu-app-id", default="")
    parser.add_argument("--feishu-app-secret", default="")
    parser.add_argument("--image-model-strategy", default="banana2,banana3")
    parser.add_argument("--image-resolution", default="2K", choices=["1K", "2K", "4K"])
    parser.add_argument("--image-indices", default="1,2,3,4,5")
    parser.add_argument("--image-retries", type=int, default=2)
    parser.add_argument("--timeout-text", type=int, default=600)
    parser.add_argument("--timeout-image", type=int, default=240)
    parser.add_argument("--timeout-publish", type=int, default=900)
    parser.add_argument("--resume", action="store_true", help="Resume from existing job_state.json")
    parser.add_argument("--force-restart", action="store_true", help="Ignore previous state and rerun all")
    args = parser.parse_args()

    output_dir = Path(args.output_dir.strip()) if args.output_dir.strip() else Path(
        f"/home/admin/workspace/articles/wx_job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / RUNNER_STATE_FILE

    if args.force_restart:
        state = {}
    elif args.resume:
        state = _read_json(state_path)
    else:
        state = _read_json(state_path) or {}

    state.setdefault("topic", args.topic)
    state.setdefault("output_dir", str(output_dir))
    state.setdefault("started_at", now())
    state.setdefault("stages", {})
    state.setdefault("images", {"done": [], "failed": {}})
    _write_json(state_path, state)

    # Stage 1: text
    revised_existing = (output_dir / "03_revised.md").exists()
    if args.resume and revised_existing and state["stages"].get("text") != "done":
        state["stages"]["text"] = "done"
        _write_json(state_path, state)
    if state["stages"].get("text") != "done":
        print(f"[{now()}] stage=text start", flush=True)
        cmd = _base_run_cmd(args, output_dir) + ["--image-mode", "skip", "--stop-after", "text"]
        ok, out = _run_cmd(cmd, timeout_s=args.timeout_text)
        if not ok:
            state["stages"]["text"] = "failed"
            state["last_error"] = _classify_failure(out)
            state["last_output"] = out[-4000:]
            _write_json(state_path, state)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            sys.exit(1)
        state["stages"]["text"] = "done"
        _write_json(state_path, state)
        print(f"[{now()}] stage=text done", flush=True)
    else:
        print(f"[{now()}] stage=text skip (already done)", flush=True)

    # Stage 2: images (one-by-one)
    revised = output_dir / "03_revised.md"
    if not revised.exists():
        state["stages"]["images"] = "failed"
        state["last_error"] = "missing_revised"
        _write_json(state_path, state)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        sys.exit(1)

    wanted = _parse_indices(args.image_indices)
    img_dir = output_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    all_done = True
    for idx in wanted:
        img_path = img_dir / f"wx_{idx:02d}.png"
        if img_path.exists():
            if idx not in state["images"]["done"]:
                state["images"]["done"].append(idx)
                _write_json(state_path, state)
            print(f"[{now()}] image[{idx}] skip (exists)", flush=True)
            continue

        success = False
        for attempt in range(1, args.image_retries + 2):
            print(f"[{now()}] image[{idx}] attempt {attempt}", flush=True)
            cmd = [
                "python3", str(GEN_IMAGES_SCRIPT),
                "--article", str(revised),
                "--output-dir", str(img_dir),
                "--resolution", args.image_resolution,
                "--model-strategy", args.image_model_strategy,
                "--indices", str(idx),
            ]
            ok, out = _run_cmd(cmd, timeout_s=args.timeout_image)
            if ok and img_path.exists():
                success = True
                break
            state["images"]["failed"][str(idx)] = {
                "attempt": attempt,
                "reason": _classify_failure(out),
                "tail": out[-2000:],
            }
            _write_json(state_path, state)
            time.sleep(1)

        if success:
            if idx not in state["images"]["done"]:
                state["images"]["done"].append(idx)
            state["images"]["failed"].pop(str(idx), None)
            _write_json(state_path, state)
            print(f"[{now()}] image[{idx}] done", flush=True)
        else:
            all_done = False
            print(f"[{now()}] image[{idx}] failed", flush=True)

    state["images"]["done"] = sorted(set(state["images"]["done"]))
    state["stages"]["images"] = "done" if all_done else "partial_failed"
    _write_json(state_path, state)

    # Stage 3: publish (use generated subset)
    done_indices = ",".join(str(i) for i in state["images"]["done"])
    if not done_indices:
        img_mode = "skip"
    else:
        img_mode = "auto"

    print(f"[{now()}] stage=publish start (mode={img_mode}, indices={done_indices or 'none'})", flush=True)
    cmd = _base_run_cmd(args, output_dir) + [
        "--reuse-existing-text",
        "--reuse-existing-titles",
        "--skip-image-generation",
        "--image-mode", img_mode,
        "--stop-after", "all",
    ]
    if done_indices:
        cmd += ["--image-indices", done_indices]
    ok, out = _run_cmd(cmd, timeout_s=args.timeout_publish)
    if not ok:
        state["stages"]["publish"] = "failed"
        state["last_error"] = _classify_failure(out)
        state["last_output"] = out[-4000:]
        _write_json(state_path, state)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        sys.exit(1)

    state["stages"]["publish"] = "done"
    state["finished_at"] = now()
    report = _read_json(output_dir / RUN_REPORT_FILE)
    state["final_report"] = report
    state["status"] = "completed" if state["stages"]["images"] == "done" else "completed_with_partial_images"
    _write_json(state_path, state)

    print(json.dumps({
        "status": state["status"],
        "output_dir": str(output_dir),
        "state_file": str(state_path),
        "doc_url": report.get("doc_url", ""),
        "title_a": report.get("title_a", ""),
        "title_b": report.get("title_b", ""),
        "images_done": state["images"]["done"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
