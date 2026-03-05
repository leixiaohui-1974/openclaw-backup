#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

OPENCLAW_CFG = Path.home() / ".openclaw" / "openclaw.json"
SKILL_DIR = Path.home() / ".openclaw" / "workspace" / "skills" / "wx-nano-image-pack"
IMG_SCRIPT = SKILL_DIR / "scripts" / "generate_wx_images.py"
FEISHU_PUBLISHER = Path.home() / ".openclaw" / "workspace" / "skills" / "feishu-doc-publisher" / "scripts" / "feishu_doc_publisher.py"


def load_openclaw_config() -> Dict[str, Any]:
    if not OPENCLAW_CFG.exists():
        return {}
    return json.loads(OPENCLAW_CFG.read_text(encoding="utf-8"))


def resolve_feishu_credentials(cfg: Dict[str, Any], app_id: str, app_secret: str) -> Tuple[str, str]:
    if app_id and app_secret:
        return app_id, app_secret
    acc = (
        cfg.get("channels", {})
        .get("feishu", {})
        .get("accounts", {})
        .get("default", {})
    )
    aid = app_id or acc.get("appId", "")
    sec = app_secret or acc.get("appSecret", "")
    if not aid or not sec:
        raise RuntimeError("Missing Feishu app_id/app_secret (args or ~/.openclaw/openclaw.json)")
    return aid, sec


def resolve_llm_provider(cfg: Dict[str, Any]) -> Tuple[str, str, str]:
    providers = cfg.get("models", {}).get("providers", {})
    # Prefer providers with non-empty keys; default to dashscope first for local stability.
    if "dashscope" in providers:
        p = providers["dashscope"]
        if p.get("apiKey", ""):
            model = (p.get("models") or [{}])[0].get("id", "qwen-plus")
            return p.get("baseUrl", "https://dashscope.aliyuncs.com/compatible-mode/v1"), p.get("apiKey", ""), model
    if "openai" in providers:
        p = providers["openai"]
        if p.get("apiKey", ""):
            model = (p.get("models") or [{}])[0].get("id", "gpt-4o-mini")
            return p.get("baseUrl", "https://api.openai.com/v1"), p.get("apiKey", ""), model
    if "dashscope" in providers:
        p = providers["dashscope"]
        model = (p.get("models") or [{}])[0].get("id", "qwen-plus")
        return p.get("baseUrl", "https://dashscope.aliyuncs.com/compatible-mode/v1"), p.get("apiKey", ""), model
    raise RuntimeError("No compatible LLM provider found in ~/.openclaw/openclaw.json")


def llm_chat(base_url: str, api_key: str, model: str, system_prompt: str, user_prompt: str, temperature: float = 0.4) -> str:
    if not api_key:
        raise RuntimeError("LLM API key is empty")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    last_err = None
    for attempt in range(1, 6):
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        if r.status_code < 300:
            d = r.json()
            choices = d.get("choices", [])
            if not choices:
                raise RuntimeError(f"LLM empty response: {d}")
            return choices[0].get("message", {}).get("content", "").strip()

        # Retry transient throttling/server errors.
        if r.status_code in (429, 500, 502, 503, 504):
            last_err = f"{r.status_code} {r.text[:500]}"
            time.sleep(min(20, attempt * 3))
            continue
        raise RuntimeError(f"LLM request failed: {r.status_code} {r.text[:500]}")

    raise RuntimeError(f"LLM request failed after retries: {last_err}")


def strip_fence(text: str) -> str:
    m = re.match(r"^```(?:json|markdown|md)?\s*([\s\S]*?)\s*```$", text.strip(), re.IGNORECASE)
    return m.group(1).strip() if m else text


def ensure_five_image_slots(md: str) -> str:
    slots = re.findall(r"【配图建议\s*(\d+)：[^】]+】", md)
    if len(slots) == 5:
        return md
    # Normalize by appending missing slots at end.
    existing = set(int(s) for s in slots)
    add = []
    defaults = {
        1: "问题场景图",
        2: "流程对照图",
        3: "架构示意图",
        4: "案例时间线",
        5: "岗位迁移图",
    }
    for i in range(1, 6):
        if i not in existing:
            add.append(f"\n【配图建议 {i}：{defaults[i]}】")
    return md + "\n" + "\n".join(add) if add else md


def inject_images(md_text: str, rel_dir: str = "./images") -> str:
    def repl(m):
        idx = int(m.group(1))
        desc = m.group(2).strip()
        return f"![图{idx}：{desc}]({rel_dir}/wx_{idx:02d}.png)"
    return re.sub(r"【配图建议\s*(\d+)：([^】]+)】", repl, md_text)


def inject_placeholders_no_images(md_text: str) -> str:
    """Replace image placeholders with readable quote placeholders."""
    def repl(m):
        idx = int(m.group(1))
        desc = m.group(2).strip()
        return f"> [图片占位 {idx}] {desc}"
    return re.sub(r"【配图建议\s*(\d+)：([^】]+)】", repl, md_text)


def strip_image_placeholders(md_text: str) -> str:
    """Remove placeholder lines like: 【配图建议 N：...】 before Feishu publish."""
    lines = []
    for line in md_text.splitlines():
        if re.match(r"^\s*【配图建议\s*\d+：[^】]+】\s*$", line.strip()):
            continue
        lines.append(line)
    # Collapse accidental 3+ blank lines caused by removals.
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def build_image_heading_mapping(md_text: str, max_images: int = 5) -> List[Dict[str, str]]:
    """Map each image slot to its nearest preceding section heading."""
    lines = md_text.splitlines()
    current_heading = ""
    first_heading = ""
    mapping: List[Dict[str, str]] = []
    slot_re = re.compile(r"【配图建议\s*(\d+)：([^】]+)】")

    for line in lines:
        s = line.strip()
        hm = re.match(r"^(#+)\s+(.+)$", s)
        if hm:
            # Use section headings (## / ### / ####) for image anchor.
            current_heading = hm.group(2).strip()
            if not first_heading:
                first_heading = current_heading
            continue
        sm = slot_re.search(s)
        if sm:
            idx = int(sm.group(1))
            mapping.append({
                "index": idx,
                "description": sm.group(2).strip(),
                "insert_after_heading": current_heading,
            })

    mapping.sort(key=lambda x: x["index"])
    # Ensure the first image has a stable anchor.
    if mapping and not mapping[0]["insert_after_heading"]:
        mapping[0]["insert_after_heading"] = first_heading
    return mapping[:max_images]


def extract_json_object(text: str) -> Dict[str, Any]:
    s = strip_fence(text)
    try:
        return json.loads(s)
    except Exception:
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            return json.loads(s[start:end + 1])
        raise


def run_cmd(cmd: List[str], env: Dict[str, str] = None, timeout: int | None = None) -> None:
    # Stream child output to avoid long silent periods that trigger upstream timeouts.
    p = subprocess.run(cmd, text=True, env=env, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)} (exit={p.returncode})")


def main():
    parser = argparse.ArgumentParser(description="WX full workflow: draft->review->revise->images->AB title->Feishu")
    parser.add_argument("--topic", required=True, help="Article topic")
    parser.add_argument("--doc-token", required=True, help="Feishu doc token")
    parser.add_argument("--output-dir", default="/home/admin/workspace/articles/wx_workflow_latest", help="Output directory")
    parser.add_argument("--user-openid", default="ou_607e1555930b5636c8b88b176b9d3bf2", help="Feishu user openid")
    parser.add_argument("--feishu-app-id", default="", help="Feishu app id override")
    parser.add_argument("--feishu-app-secret", default="", help="Feishu app secret override")
    parser.add_argument("--image-mode", default="auto", choices=["auto", "skip"], help="auto=try generate images, fallback on failure; skip=publish without image generation")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    img_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_openclaw_config()
    feishu_app_id, feishu_app_secret = resolve_feishu_credentials(cfg, args.feishu_app_id, args.feishu_app_secret)
    llm_base, llm_key, llm_model = resolve_llm_provider(cfg)

    print("[1/7] drafting...", flush=True)
    # 1) Draft
    draft_prompt = (
        "你是微信公众号写作专家。请写一篇 1500-2200 字中文公众号文章，风格专业但亲切，手机端易读。"
        "要求：开头3行抓人；最多6个二级标题；段落短；必须包含且仅包含 5 个配图占位符，"
        "格式严格为【配图建议 1：...】到【配图建议 5：...】；结尾要互动提问。"
        f"主题：{args.topic}"
    )
    draft = llm_chat(llm_base, llm_key, llm_model, "输出 Markdown 正文，不要解释。", draft_prompt, temperature=0.55)
    draft = ensure_five_image_slots(strip_fence(draft))
    (out_dir / "01_draft.md").write_text(draft, encoding="utf-8")

    print("[2/7] reviewing...", flush=True)
    # 2) Review
    review_prompt = (
        "请严格评审下面公众号稿，输出 JSON："
        "{\"score\":0-10,\"major_issues\":[...],\"minor_issues\":[...],\"rewrite_instructions\":[...]}\n\n"
        + draft
    )
    review_raw = llm_chat(llm_base, llm_key, llm_model, "你是公众号总编，只输出 JSON。", review_prompt, temperature=0.2)
    review = extract_json_object(review_raw)
    (out_dir / "02_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[3/7] revising...", flush=True)
    # 3) Revise
    revise_prompt = (
        "根据评审意见重写并输出最终 Markdown。保留 5 个配图占位符格式不变。\n\n"
        "[原稿]\n" + draft + "\n\n[评审]\n" + json.dumps(review, ensure_ascii=False)
    )
    revised = llm_chat(llm_base, llm_key, llm_model, "你是资深编辑，只输出 Markdown 正文。", revise_prompt, temperature=0.45)
    revised = ensure_five_image_slots(strip_fence(revised))
    (out_dir / "03_revised.md").write_text(revised, encoding="utf-8")

    print("[4/7] image stage...", flush=True)
    # 4) Generate images (nano) with graceful fallback
    images_enabled = args.image_mode != "skip"
    if images_enabled:
        image_timeout_s = int(os.environ.get("WX_IMAGE_STAGE_TIMEOUT", "180"))
        try:
            run_cmd([
                "python3", str(IMG_SCRIPT),
                "--article", str(out_dir / "03_revised.md"),
                "--output-dir", str(img_dir),
                "--resolution", "2K",
            ], timeout=image_timeout_s)
        except Exception as e:
            (out_dir / "image_stage_error.log").write_text(str(e), encoding="utf-8")
            images_enabled = False

    print("[5/7] composing markdown...", flush=True)
    # 5) Build local preview markdown
    with_images = inject_images(revised, rel_dir="./images") if images_enabled else inject_placeholders_no_images(revised)
    (out_dir / "04_with_images.md").write_text(with_images, encoding="utf-8")

    print("[6/7] generating title A/B...", flush=True)
    # 6) Generate title A/B
    title_prompt = (
        "为以下文章生成两个 15-22 字公众号标题。输出 JSON："
        "{\"title_a\":\"...\",\"title_b\":\"...\"}\n\n" + with_images[:4000]
    )
    titles_raw = llm_chat(llm_base, llm_key, llm_model, "你是新媒体主编，只输出 JSON。", title_prompt, temperature=0.7)
    titles = extract_json_object(titles_raw)
    title_a = (titles.get("title_a") or "智能调度新范式：人机协作进入实战").strip()
    title_b = (titles.get("title_b") or "水网 AI 不是替代，而是调度员升级").strip()
    (out_dir / "05_titles.json").write_text(json.dumps({"title_a": title_a, "title_b": title_b}, ensure_ascii=False, indent=2), encoding="utf-8")

    # Apply title A as final H1 (publish content keeps placeholder anchors)
    final_md = revised
    if re.search(r"^#\s+", final_md, flags=re.MULTILINE):
        final_md = re.sub(r"^#\s+.*$", f"# {title_a}", final_md, count=1, flags=re.MULTILINE)
    else:
        final_md = f"# {title_a}\n\n" + final_md
    final_path = out_dir / "06_final.md"
    final_path.write_text(final_md, encoding="utf-8")

    # Publish version strips placeholder text; images are inserted by API.
    publish_md = strip_image_placeholders(final_md)
    publish_path = out_dir / "06_final_publish.md"
    publish_path.write_text(publish_md, encoding="utf-8")

    # Build image insertion targets from placeholder positions.
    images_cfg = []
    if images_enabled:
        image_mapping = build_image_heading_mapping(final_md, max_images=5)
        for item in image_mapping:
            idx = item["index"]
            images_cfg.append({
                "filename": f"wx_{idx:02d}.png",
                "insert_after_heading": item["insert_after_heading"],
                "description": item["description"] or f"图{idx}",
            })

    print("[7/7] publishing to feishu...", flush=True)
    # 7) Publish to Feishu doc (overwrite body)
    pub_cfg = {
        "feishu": {"app_id": feishu_app_id, "app_secret": feishu_app_secret},
        "doc_token": args.doc_token,
        "article_path": str(publish_path),
        "images_dir": str(img_dir),
        "user_openid": args.user_openid,
        "skip_content": False,
        "overwrite_content": True,
        "keep_title_block": False,
        "strip_trailing_info": False,
        "images": images_cfg,
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(pub_cfg, tf, ensure_ascii=False, indent=2)
        cfg_path = tf.name

    try:
        run_cmd(["python3", str(FEISHU_PUBLISHER), cfg_path])
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass

    report = {
        "topic": args.topic,
        "doc_token": args.doc_token,
        "doc_url": f"https://leixiaohui1974.feishu.cn/docx/{args.doc_token}",
        "title_a": title_a,
        "title_b": title_b,
        "output_dir": str(out_dir),
        "artifacts": {
            "draft": str(out_dir / "01_draft.md"),
            "review": str(out_dir / "02_review.json"),
            "revised": str(out_dir / "03_revised.md"),
            "with_images": str(out_dir / "04_with_images.md"),
            "titles": str(out_dir / "05_titles.json"),
            "final": str(final_path),
            "final_publish": str(publish_path),
            "images_manifest": str(img_dir / "manifest.json"),
        },
        "image_mode": args.image_mode,
        "images_enabled": images_enabled,
    }
    (out_dir / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
