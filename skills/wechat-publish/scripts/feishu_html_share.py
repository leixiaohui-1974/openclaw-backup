#!/usr/bin/env python3
"""
Feishu Document to HTML Export & Share Pipeline
================================================
从飞书文档导出内容 → 转换为微信公众号风格 HTML → 通过飞书消息发送给用户

用法：
  python3 feishu_html_share.py <config.json>
  python3 feishu_html_share.py --sample

配置文件格式见 generate_sample_config()
"""

import argparse
import json
import os
import sys
import requests
from datetime import datetime

# ── Feishu API ──────────────────────────────────────────

FEISHU_BASE = "https://open.feishu.cn/open-apis"


def feishu_get_tenant_token(app_id, app_secret):
    """获取飞书 tenant_access_token"""
    resp = requests.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal", json={
        "app_id": app_id,
        "app_secret": app_secret,
    })
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取飞书 token 失败：{data}")
    return data["tenant_access_token"]


def feishu_get_blocks(token, doc_token, page_token=None):
    """获取飞书文档的所有块"""
    params = {"document_id": doc_token, "page_size": 500}
    if page_token:
        params["page_token"] = page_token
    resp = requests.get(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取文档块失败：{data}")
    items = data["data"].get("items", [])
    has_more = data["data"].get("has_more", False)
    next_token = data["data"].get("page_token")
    if has_more and next_token:
        items.extend(feishu_get_blocks(token, doc_token, next_token))
    return items


def feishu_send_text_message(token, user_id, text):
    """发送飞书文本消息给用户"""
    # 飞书 v1 API - receive_id_type 作为 query 参数
    content = {"text": text}
    
    resp = requests.post(
        f"{FEISHU_BASE}/im/v1/messages?receive_id_type=open_id",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "receive_id": user_id,
            "msg_type": "text",
            "content": json.dumps(content, ensure_ascii=False),
        },
    )
    data = resp.json()
    print(f"  消息发送响应：{data}")
    return data


# ── Feishu → HTML 转换 ────────────────────────────────────

def blocks_to_markdown(blocks):
    """将飞书文档块转换为 Markdown"""
    lines = []
    block_map = {b["block_id"]: b for b in blocks}

    for block in blocks:
        bt = block.get("block_type", 0)

        # Page block - skip
        if bt == 1:
            continue

        # Text block
        elif bt == 2:
            text = _elements_to_text(block.get("text", {}).get("elements", []))
            if text.strip():
                lines.append(text)

        # Heading blocks
        elif 3 <= bt <= 5:
            level = bt - 2
            text = _elements_to_text(block.get(f"heading{level}", {}).get("elements", []))
            if text.strip():
                lines.append(f"{'#' * level} {text}")

        # Bullet list
        elif bt == 12:
            text = _elements_to_text(block.get("bullet", {}).get("elements", []))
            if text.strip():
                lines.append(f"- {text}")

        # Ordered list
        elif bt == 13:
            text = _elements_to_text(block.get("ordered", {}).get("elements", []))
            if text.strip():
                lines.append(f"1. {text}")

        # Code block
        elif bt == 14:
            text = _elements_to_text(block.get("code", {}).get("elements", []))
            lines.append(f"```\n{text}\n```")

        # Quote block
        elif bt == 15:
            text = _elements_to_text(block.get("quote", {}).get("elements", []))
            if text.strip():
                lines.append(f"> {text}")

        # Divider
        elif bt == 22:
            lines.append("---")

        # Image block
        elif bt == 27:
            lines.append("[图片]")

        # Callout block
        elif bt == 19:
            children_ids = block.get("children", [])
            for child_id in children_ids:
                child_block = block_map.get(child_id, {})
                child_text = _elements_to_text(child_block.get("text", {}).get("elements", []))
                if child_text.strip():
                    lines.append(f"> 💡 {child_text}")

    return "\n\n".join(lines)


def _elements_to_text(elements):
    """将飞书富文本元素转为纯文本"""
    parts = []
    for elem in elements:
        if "text_run" in elem:
            parts.append(elem["text_run"].get("content", ""))
        elif "mention_user" in elem:
            parts.append(elem["mention_user"].get("user_name", "@user"))
        elif "equation" in elem:
            parts.append(elem["equation"].get("content", ""))
    return "".join(parts)


def generate_simple_html(title, author, doc_token, content_md):
    """生成简洁的 HTML 预览"""
    # 将 Markdown 简单转换为 HTML
    html_body = content_md.replace("\n\n", "</p><p>")
    html_body = html_body.replace("\n", "<br/>")
    html_body = html_body.replace("# ", "<h1>")
    html_body = html_body.replace("## ", "<h2>")
    html_body = html_body.replace("### ", "<h3>")
    html_body = html_body.replace("- ", "<li>")
    html_body = html_body.replace("> ", "<blockquote>")
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ max-width: 680px; margin: 0 auto; padding: 20px; font-family: -apple-system, sans-serif; line-height: 1.8; }}
        h1 {{ font-size: 24px; text-align: center; }}
        h2 {{ font-size: 20px; border-bottom: 1px solid #eee; }}
        img {{ max-width: 100%; }}
        blockquote {{ border-left: 4px solid #ddd; padding-left: 1em; color: #666; }}
        .meta {{ text-align: center; color: #999; font-size: 14px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <p class="meta">作者：{author} | 导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
    <hr/>
    <p>{html_body[:5000]}...</p>
    <hr/>
    <p class="meta"><a href="https://feishu.cn/docx/{doc_token}">查看完整原文档 →</a></p>
</body>
</html>"""


# ── Pipeline ────────────────────────────────────────────────

def run_pipeline(config):
    """运行飞书文档导出 → 发送预览消息给用户"""
    feishu = config["feishu"]
    doc_token = config["doc_token"]
    title = config.get("title", "")
    author = config.get("author", "")
    user_id = config.get("user_id", "")
    auto_send = config.get("auto_send", True)

    print("=" * 60)
    print("飞书文档 → HTML 导出 & 分享流水线")
    print("=" * 60)
    print(f"文档：{doc_token}")
    print(f"标题：{title}")
    print(f"作者：{author}")
    print(f"接收用户：{user_id}")

    # Step 1: 获取飞书文档
    print("\n[1/3] 获取飞书文档内容...")
    feishu_token = feishu_get_tenant_token(feishu["app_id"], feishu["app_secret"])
    blocks = feishu_get_blocks(feishu_token, doc_token)
    print(f"  文档共 {len(blocks)} 个块")

    # 提取标题
    if not title:
        for b in blocks:
            bt = b.get("block_type", 0)
            if 3 <= bt <= 5:
                heading_key = {3: "heading1", 4: "heading2", 5: "heading3"}
                elems = b.get(heading_key.get(bt, "heading1"), {}).get("elements", [])
                for e in elems:
                    if "text_run" in e:
                        title += e["text_run"].get("content", "")
                if title:
                    break
    print(f"  标题：{title}")

    # Step 2: 转换为 Markdown 预览
    print("\n[2/3] 生成内容预览...")
    content_md = blocks_to_markdown(blocks)
    # 截取前 1000 字符作为预览
    preview_text = content_md[:1000].replace("\n\n", "\n")
    print(f"  内容长度：{len(content_md)} 字符")
    
    # 统计图片数量
    image_count = sum(1 for b in blocks if b.get("block_type") == 27)
    print(f"  图片数量：{image_count}")

    # Step 3: 发送消息给用户
    if auto_send and user_id:
        print("\n[3/3] 发送消息给用户...")
        
        # 构建消息内容
        doc_url = f"https://feishu.cn/docx/{doc_token}"
        message_text = f"""📄 文档导出完成

标题：{title}
作者：{author}

文档共 {len(blocks)} 个区块，包含 {image_count} 张图片。

内容预览：
{preview_text}

---
👉 查看完整文档：{doc_url}"""
        
        message_result = feishu_send_text_message(feishu_token, user_id, message_text)
        print(f"  消息发送结果：{message_result}")
    else:
        print("\n[SKIP] 未发送消息（auto_send=false 或 user_id 未指定）")

    print("\n" + "=" * 60)
    print("完成!")
    print(f"  文档链接：https://feishu.cn/docx/{doc_token}")
    if auto_send and user_id:
        print(f"  消息已发送给用户：{user_id}")
    print("=" * 60)

    return {
        "doc_token": doc_token,
        "doc_url": f"https://feishu.cn/docx/{doc_token}",
        "block_count": len(blocks),
        "image_count": image_count,
    }


def generate_sample_config():
    """生成示例配置"""
    return {
        "feishu": {
            "app_id": "cli_a915cc56d5f89cb1",
            "app_secret": "YOUR_APP_SECRET",
        },
        "doc_token": "FEISHU_DOC_TOKEN",
        "title": "",
        "author": "雷晓辉",
        "user_id": "ou_xxx",
        "auto_send": True,
    }


# ── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="飞书文档 → HTML 导出 & 分享")
    parser.add_argument("config", nargs="?", help="配置文件路径 (JSON)")
    parser.add_argument("--sample", action="store_true", help="输出示例配置")
    parser.add_argument("--nosend", action="store_true", help="不发送消息，仅生成预览")
    args = parser.parse_args()

    if args.sample:
        print(json.dumps(generate_sample_config(), indent=2, ensure_ascii=False))
        return

    if not args.config:
        parser.print_help()
        return

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    if args.nosend:
        config["auto_send"] = False

    run_pipeline(config)


if __name__ == "__main__":
    main()
