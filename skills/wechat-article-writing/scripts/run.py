#!/usr/bin/env python3
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_TOPIC = "调度员会被AI取代吗？水网协同真相"
DEFAULT_DOC_TOKEN = "F1yfdz69Jo8k2kxIzshcMrFknVd"


def main():
    parser = argparse.ArgumentParser(description="Run wechat-article-writing full workflow")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--doc-token", default=DEFAULT_DOC_TOKEN)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--user-openid", default="ou_607e1555930b5636c8b88b176b9d3bf2")
    parser.add_argument("--feishu-app-id", default="")
    parser.add_argument("--feishu-app-secret", default="")
    args = parser.parse_args()

    target = Path.home() / ".openclaw/workspace/skills/wx-nano-image-pack/scripts/wx_full_workflow.py"
    if not target.exists():
        print(f"Missing workflow script: {target}", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir.strip()
    if not output_dir:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"/home/admin/workspace/articles/wx_workflow_auto_{ts}"

    cmd = [
        "python3", str(target),
        "--topic", args.topic,
        "--doc-token", args.doc_token,
        "--output-dir", output_dir,
        "--user-openid", args.user_openid,
    ]
    if args.feishu_app_id:
        cmd += ["--feishu-app-id", args.feishu_app_id]
    if args.feishu_app_secret:
        cmd += ["--feishu-app-secret", args.feishu_app_secret]

    p = subprocess.run(cmd)
    sys.exit(p.returncode)


if __name__ == "__main__":
    main()
