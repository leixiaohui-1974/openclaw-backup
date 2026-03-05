#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run wechat-article-writing full workflow")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--doc-token", required=True)
    parser.add_argument("--output-dir", default="/home/admin/workspace/articles/wx_workflow_latest")
    parser.add_argument("--user-openid", default="ou_607e1555930b5636c8b88b176b9d3bf2")
    parser.add_argument("--feishu-app-id", default="")
    parser.add_argument("--feishu-app-secret", default="")
    args = parser.parse_args()

    target = Path.home() / ".openclaw/workspace/skills/wx-nano-image-pack/scripts/wx_full_workflow.py"
    if not target.exists():
        print(f"Missing workflow script: {target}", file=sys.stderr)
        sys.exit(1)

    cmd = [
        "python3", str(target),
        "--topic", args.topic,
        "--doc-token", args.doc_token,
        "--output-dir", args.output_dir,
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
