#!/usr/bin/env python3
"""
Feishu Document Image Pipeline
===============================
通用流程：生成图片（nano-banana-pro）→ 上传飞书 → 插入文档指定位置

用法：
  1. 编辑 pipeline_config.json 配置文件
  2. python3 feishu_image_pipeline.py pipeline_config.json

配置文件格式见 generate_sample_config()
"""

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import requests

# ── Feishu API ──────────────────────────────────────────────

FEISHU_BASE = "https://open.feishu.cn/open-apis"
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/workspace/.openclaw/feishu-images")


def feishu_get_token(app_id, app_secret):
    """获取飞书 tenant_access_token"""
    resp = requests.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal", json={
        "app_id": app_id,
        "app_secret": app_secret,
    })
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取飞书 token 失败: {data}")
    return data["tenant_access_token"]


def feishu_get_children(token, doc_token):
    """获取文档顶层 block 列表"""
    resp = requests.get(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取文档结构失败: {data}")
    return data["data"]["block"]["children"]


def feishu_create_image_block(token, doc_token, index=-1):
    """在文档中创建空图片块"""
    body = {"children": [{"block_type": 27, "image": {}}]}
    if index >= 0:
        body["index"] = index
    resp = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"创建图片块失败: {data}")
    return data["data"]["children"][0]["block_id"]


def feishu_upload_image(token, block_id, image_path):
    """上传图片到飞书"""
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "application/octet-stream"
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{FEISHU_BASE}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": os.path.basename(image_path),
                "parent_type": "docx_image",
                "parent_node": block_id,
                "size": str(os.path.getsize(image_path)),
            },
            files={"file": (os.path.basename(image_path), f, mime_type)},
        )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"上传图片失败: {data}")
    return data["data"]["file_token"]


def feishu_patch_image(token, doc_token, block_id, file_token):
    """用上传的图片填充图片块"""
    resp = requests.patch(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{block_id}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"replace_image": {"token": file_token}},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"填充图片块失败: {data}")


def feishu_delete_block(token, doc_token, block_id):
    """删除文档中的一个顶层块（通过 children/batch_delete）"""
    children = feishu_get_children(token, doc_token)
    try:
        idx = children.index(block_id)
    except ValueError:
        return False

    resp = requests.delete(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children/batch_delete",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"start_index": idx, "end_index": idx + 1},
    )
    data = resp.json()
    return data.get("code", -1) == 0


# ── Image Generation (nano-banana-pro) ──────────────────────

CHINESE_TEXT_RULE = (
    "All visible text in the image must be in Simplified Chinese only. "
    "Do not use English words, letters, or romanization in labels."
)


def load_api_key_from_openclaw_env() -> str:
    """从 ~/.openclaw/.env 读取 Gemini/Nano API Key。"""
    env_path = os.path.expanduser("~/.openclaw/.env")
    if not os.path.exists(env_path):
        return ""

    wanted = ("GEMINI_API_KEY", "NANO_BANANA_API_KEY")
    values = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    except Exception:
        return ""

    for key in wanted:
        val = values.get(key, "")
        if val:
            return val
    return ""


def load_api_key_from_openclaw_config() -> str:
    """从 openclaw.json 读取 Gemini/Nano API Key。"""
    cfg_path = os.environ.get("OPENCLAW_CONFIG_PATH", os.path.expanduser("~/.openclaw/openclaw.json"))
    if not os.path.exists(cfg_path):
        return ""
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return ""

    # 1) skills.nano-banana-pro.*
    skills = cfg.get("skills") or {}
    nano = skills.get("nano-banana-pro") or {}
    if isinstance(nano.get("apiKey"), str) and nano.get("apiKey"):
        return nano["apiKey"]
    nano_env = nano.get("env") or {}
    if isinstance(nano_env.get("GEMINI_API_KEY"), str) and nano_env.get("GEMINI_API_KEY"):
        return nano_env["GEMINI_API_KEY"]

    # 2) top-level env
    env_cfg = cfg.get("env") or {}
    for key in ("GEMINI_API_KEY", "NANO_BANANA_API_KEY"):
        val = env_cfg.get(key)
        if isinstance(val, str) and val:
            return val

    # 3) models.providers.gemini.apiKey
    providers = ((cfg.get("models") or {}).get("providers") or {})
    gemini = providers.get("gemini") or {}
    if isinstance(gemini.get("apiKey"), str) and gemini.get("apiKey"):
        return gemini["apiKey"]
    return ""


def _mask_secret(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _classify_generate_error(msg: str) -> str:
    s = (msg or "").lower()
    if "no api key provided" in s or "gemini_api_key" in s:
        return "missing_api_key"
    if "找不到 nano-banana-pro" in s or "generate_image.py" in s:
        return "missing_script"
    if "no such file or directory" in s and "uv" in s:
        return "missing_uv"
    if "timeout" in s:
        return "timeout"
    if "403" in s or "permission" in s or "unauthorized" in s:
        return "auth_or_permission"
    if "quota" in s or "429" in s:
        return "quota_or_rate_limit"
    return "unknown"


def _preflight_generation(skip_generate: bool, image_dir: str, images: list, gemini_key: str) -> dict:
    """生成前健康检查，避免进入伪执行状态。"""
    uv_path = shutil.which("uv")
    script_path = _find_nano_banana_script()
    key_present = bool(gemini_key)
    existing_count = 0
    for img in images:
        fp = os.path.join(image_dir, img.get("filename", ""))
        if fp and os.path.exists(fp):
            existing_count += 1

    result = {
        "skip_generate": bool(skip_generate),
        "uv_path": uv_path or "",
        "script_path": script_path or "",
        "key_present": key_present,
        "existing_count": existing_count,
        "total_images": len(images),
    }
    return result


def ensure_chinese_text_prompt(prompt: str, force_chinese_text: bool = True) -> str:
    """确保图中文字约束为中文。"""
    prompt = (prompt or "").strip()
    if not force_chinese_text:
        return prompt

    lower = prompt.lower()
    if "all visible text in the image must be in simplified chinese only" in lower:
        return prompt
    if not prompt:
        return CHINESE_TEXT_RULE
    return f"{prompt}\n\n{CHINESE_TEXT_RULE}"


def generate_image(prompt, output_path, resolution="2K", gemini_api_key=None):
    """用 nano-banana-pro (Gemini 3 Pro Image) 生成图片"""
    script = _find_nano_banana_script()
    if not script:
        raise Exception("找不到 nano-banana-pro 的 generate_image.py 脚本")

    env = os.environ.copy()
    if gemini_api_key:
        env["GEMINI_API_KEY"] = gemini_api_key

    cmd = [
        "uv", "run", script,
        "--prompt", prompt,
        "--filename", output_path,
        "--resolution", resolution,
    ]
    print(f"    执行: uv run generate_image.py --resolution {resolution}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise Exception(f"图片生成失败 (exit {result.returncode}):\n{stderr or stdout}")

    if not os.path.exists(output_path):
        # 检查是否输出了 MEDIA: 行，里面可能有实际路径
        for line in result.stdout.split("\n"):
            if line.startswith("MEDIA:"):
                actual_path = line.split("MEDIA:", 1)[1].strip()
                if os.path.exists(actual_path):
                    os.rename(actual_path, output_path)
                    break
    if not os.path.exists(output_path):
        raise Exception(f"图片生成后文件不存在: {output_path}\nstdout: {result.stdout[:500]}")

    size_kb = os.path.getsize(output_path) / 1024
    print(f"    生成完成: {output_path} ({size_kb:.0f} KB)")


def _find_nano_banana_script():
    """查找 nano-banana-pro 的生成脚本"""
    import glob
    candidates = [
        os.path.expanduser("~/.openclaw/workspace/skills/nano-banana-pro/scripts/generate_image.py"),
        os.path.expanduser("~/.codex/skills/nano-banana-pro/scripts/generate_image.py"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    patterns = [
        os.path.expanduser("~/.local/share/pnpm/global/*/.pnpm/openclaw@*/node_modules/openclaw/skills/nano-banana-pro/scripts/generate_image.py"),
        os.path.expanduser("~/.local/share/pnpm/global/*/node_modules/openclaw/skills/nano-banana-pro/scripts/generate_image.py"),
        "/home/admin/.local/share/pnpm/global/5/.pnpm/openclaw@*/node_modules/openclaw/skills/nano-banana-pro/scripts/generate_image.py",
    ]
    all_matches = []
    for pat in patterns:
        all_matches.extend(glob.glob(pat))
    if all_matches:
        all_matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return all_matches[0]
    return None


# ── Pipeline ────────────────────────────────────────────────

def run_pipeline(config):
    """运行完整流水线"""
    # 解析配置
    feishu = config["feishu"]
    doc_token = config["doc_token"]
    images = config["images"]
    image_dir = config.get("output_dir", DEFAULT_OUTPUT_DIR)
    resolution = config.get("resolution", "2K")
    gemini_key = (
        config.get("gemini_api_key")
        or config.get("api_key")
        or config.get("nano_api_key")
        or os.environ.get("GEMINI_API_KEY", "")
        or os.environ.get("NANO_BANANA_API_KEY", "")
        or load_api_key_from_openclaw_env()
        or load_api_key_from_openclaw_config()
    )
    force_chinese_text = config.get("force_chinese_text", True)
    skip_generate = config.get("skip_generate", False)
    auto_degrade = config.get("degrade_to_existing_images_on_generate_failure", True)

    os.makedirs(image_dir, exist_ok=True)

    print("=" * 60)
    print("飞书文档图片流水线")
    print("=" * 60)
    print(f"文档: {doc_token}")
    print(f"图片数: {len(images)}")
    print(f"分辨率: {resolution}")
    print(f"输出目录: {image_dir}")
    print(f"跳过生成: {skip_generate}")
    print(f"强制中文文案: {force_chinese_text}")

    preflight = _preflight_generation(skip_generate, image_dir, images, gemini_key)
    print(
        "生成预检:"
        f" uv={'OK' if preflight['uv_path'] else 'MISSING'}"
        f", script={'OK' if preflight['script_path'] else 'MISSING'}"
        f", key={'OK' if preflight['key_present'] else 'MISSING'}"
        f", existing={preflight['existing_count']}/{preflight['total_images']}"
    )
    if preflight["key_present"]:
        print(f"  API key: {_mask_secret(gemini_key)}")

    generation_ready = bool(preflight["uv_path"] and preflight["script_path"] and preflight["key_present"])
    if not skip_generate and not generation_ready:
        if auto_degrade and preflight["existing_count"] > 0:
            print("  !! 生成链路不可用，自动降级：跳过生成，仅使用已有图片继续插入")
            skip_generate = True
        else:
            raise Exception(
                "生成预检失败：缺少 uv/脚本/API key，且无可用已有图片可降级。"
                "请检查 uv、nano-banana-pro 脚本路径和 GEMINI_API_KEY。"
            )

    # Step 1: 获取飞书 token
    print("\n[1/4] 获取飞书访问令牌...")
    token = feishu_get_token(feishu["app_id"], feishu["app_secret"])
    print(f"  OK: {token[:20]}...")

    # Step 2: 生成图片
    print(f"\n[2/4] 生成图片 ({len(images)} 张)...")
    for i, img in enumerate(images):
        filename = img["filename"]
        filepath = os.path.join(image_dir, filename)
        img["_filepath"] = filepath

        if skip_generate and os.path.exists(filepath):
            print(f"  [{i+1}/{len(images)}] 跳过 (已存在): {filename}")
            continue

        print(f"  [{i+1}/{len(images)}] 生成: {img.get('description', filename)}")
        try:
            prompt = ensure_chinese_text_prompt(img.get("prompt", ""), force_chinese_text)
            generate_image(prompt, filepath, resolution, gemini_key)
        except Exception as e:
            print(f"    !! 失败: {e}")
            img["_error"] = str(e)
            img["_error_type"] = _classify_generate_error(str(e))
            if auto_degrade and os.path.exists(filepath):
                print(f"    -> 自动降级: 使用已有文件 {filename}")
                img["_degraded_to_existing"] = True
                continue
            continue

        time.sleep(1)  # 避免 API 限流

    # Step 3: 获取文档结构并插入图片块
    print(f"\n[3/4] 插入图片到文档...")
    children = feishu_get_children(token, doc_token)
    print(f"  文档当前有 {len(children)} 个顶层块")

    # 从后往前插入以保持索引稳定
    successful = []
    for i, img in enumerate(reversed(images)):
        idx = len(images) - 1 - i
        filepath = img.get("_filepath", "")

        if not os.path.exists(filepath):
            print(f"  [{idx+1}] 跳过 (无文件): {img['filename']}")
            continue

        insert_after = img.get("insert_after_block")
        if not insert_after:
            print(f"  [{idx+1}] 跳过 (无目标位置): {img['filename']}")
            continue

        print(f"  [{idx+1}] {img.get('description', img['filename'])}")

        # 查找插入位置
        block_index = -1
        for j, child_id in enumerate(children):
            if child_id == insert_after:
                block_index = j + 1
                break

        if block_index < 0:
            print(f"    !! 目标块 {insert_after} 不存在，追加到末尾")

        try:
            # 创建图片块
            new_block = feishu_create_image_block(token, doc_token, block_index)
            print(f"    创建块: {new_block}")
            time.sleep(0.5)

            # 上传图片
            file_token = feishu_upload_image(token, new_block, filepath)
            print(f"    上传完成: {file_token}")
            time.sleep(0.3)

            # 填充图片
            feishu_patch_image(token, doc_token, new_block, file_token)
            print(f"    插入完成 ✓")

            img["_block_id"] = new_block
            img["_file_token"] = file_token
            successful.append(img)

            # 刷新 children
            children = feishu_get_children(token, doc_token)
            time.sleep(0.3)

        except Exception as e:
            print(f"    !! 失败: {e}")

    # Step 4: 汇总
    print(f"\n[4/4] 完成")
    print("=" * 60)
    print(f"成功: {len(successful)}/{len(images)} 张图片")
    for img in successful:
        print(f"  ✓ {img.get('description', img['filename'])} -> {img.get('_block_id', '?')}")
    failed = [img for img in images if "_error" in img or "_block_id" not in img]
    if failed:
        print(f"失败: {len(failed)} 张")
        for img in failed:
            print(f"  ✗ {img.get('description', img['filename'])}: {img.get('_error', '未知错误')}")
    print("=" * 60)


def generate_sample_config():
    """生成示例配置文件"""
    return {
        "feishu": {
            "app_id": "cli_a915cc56d5f89cb1",
            "app_secret": "YOUR_APP_SECRET",
        },
        "doc_token": "Hk4md9l25ojaaMxtK6tcumWonRc",
        "gemini_api_key": "YOUR_GEMINI_API_KEY",
        "force_chinese_text": True,
        "output_dir": DEFAULT_OUTPUT_DIR,
        "resolution": "2K",
        "skip_generate": False,
        "degrade_to_existing_images_on_generate_failure": True,
        "images": [
            {
                "filename": "001-web-browser-vs-cli.png",
                "prompt": "Clean infographic comparing web browser AI chat vs command-line terminal AI tool...",
                "insert_after_block": "doxcnS6BbSUg8BkrTOfBNOex5Hf",
                "description": "网页浏览器 vs 命令行终端对比图",
            },
        ],
    }


# ── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="飞书文档图片流水线")
    parser.add_argument("config", nargs="?", help="配置文件路径 (JSON)")
    parser.add_argument("--sample", action="store_true", help="输出示例配置文件")
    parser.add_argument("--skip-generate", action="store_true", help="跳过图片生成（使用已有图片）")
    args = parser.parse_args()

    if args.sample:
        print(json.dumps(generate_sample_config(), indent=2, ensure_ascii=False))
        return

    if not args.config:
        parser.print_help()
        return

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    if args.skip_generate:
        config["skip_generate"] = True

    run_pipeline(config)


if __name__ == "__main__":
    main()
