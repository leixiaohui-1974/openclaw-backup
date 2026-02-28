#!/usr/bin/env python3
"""
Feishu Document Publisher
=========================
完整工作流：Markdown → 飞书文档（写正文 + 插图 + 授权）

用法：
  python3 feishu_doc_publisher.py <config.json>
  python3 feishu_doc_publisher.py --sample

配置文件格式见末尾 sample_config()。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import requests

FEISHU_BASE = "https://open.feishu.cn/open-apis"

# ── Feishu Block Types (docx v1 API) ──
BT_TEXT = 2
BT_H1 = 3
BT_H2 = 4
BT_H3 = 5
BT_H4 = 6
BT_BULLET = 12
BT_ORDERED = 13
BT_CODE = 14
BT_QUOTE = 15
BT_DIVIDER = 22
BT_IMAGE = 27


# ══════════════════════════════════════════════════════════════
# Feishu API helpers
# ══════════════════════════════════════════════════════════════

def feishu_token(app_id, app_secret):
    r = requests.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": app_id, "app_secret": app_secret})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Auth failed: {d}")
    return d["tenant_access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_blocks(token, doc_token, parent_id, blocks, index=-1):
    """Create child blocks. Returns list of created block dicts."""
    body = {"children": blocks}
    if index >= 0:
        body["index"] = index
    r = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{parent_id}/children",
        headers=_headers(token), json=body)
    d = r.json()
    if d.get("code") != 0:
        return None, d
    return d["data"]["children"], None


def get_children(token, doc_token):
    """Get all top-level child blocks (paginated)."""
    all_blocks = []
    page_token = None
    while True:
        params = {"page_size": 50}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(
            f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
            headers=_headers(token), params=params)
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Get children failed: {d}")
        all_blocks.extend(d["data"].get("items", []))
        if not d["data"].get("has_more"):
            break
        page_token = d["data"].get("page_token")
    return all_blocks


def upload_image(token, block_id, image_path):
    """Upload image to Feishu drive, returns file_token."""
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{FEISHU_BASE}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": os.path.basename(image_path),
                "parent_type": "docx_image",
                "parent_node": block_id,
                "size": str(os.path.getsize(image_path)),
            },
            files={"file": (os.path.basename(image_path), f, "image/png")})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Upload failed: {d}")
    return d["data"]["file_token"]


def patch_image(token, doc_token, block_id, file_token):
    r = requests.patch(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{block_id}",
        headers=_headers(token),
        json={"replace_image": {"token": file_token}})
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Patch image failed: {d}")


def grant_permission(token, doc_token, openid, perm="full_access"):
    r = requests.post(
        f"{FEISHU_BASE}/drive/v1/permissions/{doc_token}/members?type=docx",
        headers=_headers(token),
        json={"member_type": "openid", "member_id": openid, "perm": perm})
    d = r.json()
    return d.get("code") == 0


def get_raw_content(token, doc_token):
    """Get document raw text content."""
    r = requests.get(
        f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/raw_content",
        headers=_headers(token))
    d = r.json()
    if d.get("code") != 0:
        return ""
    return d["data"].get("content", "")


# ══════════════════════════════════════════════════════════════
# Markdown → Feishu blocks
# ══════════════════════════════════════════════════════════════

def _text_elements(text):
    """Parse inline Markdown (bold, links) into Feishu elements."""
    elements = []
    # Pattern matches **bold** and [text](url)
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
        elif re.match(r'\[([^\]]+)\]\(([^)]+)\)', p):
            m = re.match(r'\[([^\]]+)\]\(([^)]+)\)', p)
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
    """Helper to create a standard text-bearing block."""
    return {"block_type": block_type, field_name: {"elements": _text_elements(text)}}


def markdown_to_blocks(md_text):
    """Convert Markdown text into list of Feishu block dicts."""
    lines = md_text.split('\n')
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Skip H1 title (already the doc title)
        if re.match(r'^#\s+[^#]', stripped):
            i += 1
            continue

        # Divider ---
        if stripped in ('---', '***', '___'):
            blocks.append({"block_type": BT_DIVIDER, "divider": {}})
            i += 1
            continue

        # H2
        if stripped.startswith('## '):
            blocks.append(_make_block(BT_H2, "heading2", stripped[3:]))
            i += 1
            continue

        # H3
        if stripped.startswith('### '):
            blocks.append(_make_block(BT_H3, "heading3", stripped[4:]))
            i += 1
            continue

        # H4
        if stripped.startswith('#### '):
            blocks.append(_make_block(BT_H4, "heading4", stripped[5:]))
            i += 1
            continue

        # Code block
        if stripped.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # skip closing ```
            code_text = '\n'.join(code_lines) or " "
            blocks.append({
                "block_type": BT_CODE,
                "code": {
                    "elements": [{"text_run": {"content": code_text, "text_element_style": {}}}],
                    "style": {"language": 1}  # 1 = PlainText
                }
            })
            continue

        # Blockquote >
        if stripped.startswith('> '):
            quote_text = stripped[2:]
            blocks.append(_make_block(BT_QUOTE, "quote", quote_text))
            i += 1
            continue

        # Table lines → convert each row to a text block (Feishu table API is complex)
        if stripped.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            rows = []
            for tl in table_lines:
                if re.match(r'^\|[-:\s|]+\|$', tl):
                    continue  # separator
                cells = [c.strip() for c in tl.strip('|').split('|')]
                rows.append(cells)
            if rows:
                # First row as bold header
                blocks.append({"block_type": BT_TEXT, "text": {"elements": [
                    {"text_run": {"content": " │ ".join(rows[0]), "text_element_style": {"bold": True}}}
                ]}})
                for row in rows[1:]:
                    blocks.append({"block_type": BT_TEXT, "text": {
                        "elements": _text_elements(" │ ".join(row))
                    }})
            continue

        # Unordered list -
        if stripped.startswith('- '):
            blocks.append(_make_block(BT_BULLET, "bullet", stripped[2:]))
            i += 1
            continue

        # Ordered list 1. 2. etc
        m = re.match(r'^(\d+)\.\s+(.+)', stripped)
        if m:
            blocks.append(_make_block(BT_ORDERED, "ordered", m.group(2)))
            i += 1
            continue

        # Italic line *...*
        if stripped.startswith('*') and stripped.endswith('*') and not stripped.startswith('**'):
            text = stripped.strip('*')
            blocks.append({"block_type": BT_TEXT, "text": {"elements": [
                {"text_run": {"content": text, "text_element_style": {"italic": True}}}
            ]}})
            i += 1
            continue

        # Regular paragraph
        blocks.append({"block_type": BT_TEXT, "text": {
            "elements": _text_elements(stripped)
        }})
        i += 1

    return blocks


# ══════════════════════════════════════════════════════════════
# Image insertion
# ══════════════════════════════════════════════════════════════

def find_section_end(blocks, keyword):
    """Find the block_id at the end of a section that starts with a heading containing keyword.
    Returns (block_id, index) or (None, None)."""
    heading_types = {BT_H1, BT_H2, BT_H3, BT_H4}
    heading_fields = {3: "heading1", 4: "heading2", 5: "heading3", 6: "heading4"}
    found_idx = None

    for idx, b in enumerate(blocks):
        bt = b["block_type"]
        if bt in heading_types:
            text = ""
            field = heading_fields.get(bt)
            if field and field in b:
                for el in b[field].get("elements", []):
                    if "text_run" in el:
                        text += el["text_run"]["content"]
            if keyword in text:
                found_idx = idx
            elif found_idx is not None:
                # Reached next heading, return block before it (skip trailing dividers)
                target = idx - 1
                while target > found_idx and blocks[target]["block_type"] == BT_DIVIDER:
                    target -= 1
                return blocks[target]["block_id"], target

    # Section extends to end of doc
    if found_idx is not None:
        target = len(blocks) - 1
        while target > found_idx and blocks[target]["block_type"] == BT_DIVIDER:
            target -= 1
        return blocks[target]["block_id"], target

    return None, None


def insert_image(token, doc_token, after_block_id, image_path, all_blocks):
    """Insert an image after a given block. Returns new block_id or None."""
    # Find index of after_block_id
    target_index = -1
    for ci, cb in enumerate(all_blocks):
        if cb["block_id"] == after_block_id:
            target_index = ci + 1
            break

    # Create empty image block
    created, err = create_blocks(token, doc_token, doc_token,
                                 [{"block_type": BT_IMAGE, "image": {}}],
                                 index=target_index)
    if err:
        print(f"    ❌ Create image block failed: {err.get('msg', '')}")
        return None

    img_block_id = created[0]["block_id"]

    # Upload
    file_token = upload_image(token, img_block_id, image_path)

    # Patch
    patch_image(token, doc_token, img_block_id, file_token)
    return img_block_id


# ══════════════════════════════════════════════════════════════
# Main flow
# ══════════════════════════════════════════════════════════════

def run(config):
    feishu = config["feishu"]
    doc_token = config["doc_token"]
    article_path = config["article_path"]
    images = config.get("images", [])
    user_openid = config.get("user_openid", "")
    skip_content = config.get("skip_content", False)
    strip_trailing_info = config.get("strip_trailing_info", True)

    print("=" * 60)
    print("Feishu Document Publisher")
    print("=" * 60)

    # 1. Auth
    print("\n[1/5] Authenticating...")
    token = feishu_token(feishu["app_id"], feishu["app_secret"])
    print("  ✅ Token OK")

    # 2. Check doc content
    print("\n[2/5] Checking document...")
    raw = get_raw_content(token, doc_token)
    raw_len = len(raw.strip())
    print(f"  Document raw content: {raw_len} chars")

    # 3. Write content (if empty or forced)
    content_written = 0
    if skip_content:
        print("  ⏭️  skip_content=true, skipping content write")
    elif raw_len > 50:
        print(f"  ⏭️  Document already has content ({raw_len} chars), skipping write")
    else:
        print("\n[3/5] Writing article content...")
        with open(article_path, "r") as f:
            md_text = f.read()

        if strip_trailing_info:
            md_text = re.sub(r'\n\*本文基于作者在.*$', '', md_text, flags=re.DOTALL)

        blocks = markdown_to_blocks(md_text)
        print(f"  Parsed {len(blocks)} blocks")

        # Write in small batches (飞书 API 对批量创建有限制)
        batch_size = 20
        for start in range(0, len(blocks), batch_size):
            batch = blocks[start:start + batch_size]
            created, err = create_blocks(token, doc_token, doc_token, batch, index=-1)
            if err:
                # Retry one by one
                for bi, block in enumerate(batch):
                    c, e = create_blocks(token, doc_token, doc_token, [block], index=-1)
                    if c:
                        content_written += 1
                    else:
                        print(f"    ⚠️ Block {start+bi} failed: {e.get('msg','')[:40]}")
            else:
                content_written += len(created)
            time.sleep(0.3)

        print(f"  ✅ {content_written}/{len(blocks)} blocks written")

    # 4. Insert images
    if not images:
        print("\n[4/5] No images configured, skipping")
    else:
        print(f"\n[4/5] Inserting {len(images)} images...")
        time.sleep(0.5)
        all_blocks = get_children(token, doc_token)
        print(f"  Document now has {len(all_blocks)} blocks")

        # Collect targets (heading keyword → block_id)
        targets = []
        for img in images:
            fn = img["filename"]
            kw = img.get("insert_after_heading", "")
            desc = img.get("description", fn)
            path = os.path.join(config.get("images_dir", "."), fn)

            if not os.path.exists(path):
                print(f"  ❌ {fn}: file not found at {path}")
                continue

            if kw:
                bid, bidx = find_section_end(all_blocks, kw)
                if bid:
                    targets.append((fn, desc, path, bid, bidx))
                else:
                    print(f"  ⚠️ {fn}: heading '{kw}' not found, appending at end")
                    targets.append((fn, desc, path, None, len(all_blocks)))
            else:
                targets.append((fn, desc, path, None, len(all_blocks)))

        # Insert from bottom to top to preserve indices
        targets.sort(key=lambda x: x[4], reverse=True)
        inserted = 0
        for fn, desc, path, after_bid, _ in targets:
            size_mb = os.path.getsize(path) / 1024 / 1024
            print(f"  📷 {fn} ({size_mb:.1f}MB)")
            try:
                # Re-read blocks (insertion changes indices)
                current_blocks = get_children(token, doc_token)
                if after_bid:
                    bid = insert_image(token, doc_token, after_bid, path, current_blocks)
                else:
                    bid = insert_image(token, doc_token, current_blocks[-1]["block_id"], path, current_blocks)
                if bid:
                    print(f"    ✅ {desc}")
                    inserted += 1
                time.sleep(1)
            except Exception as e:
                print(f"    ❌ {e}")

        print(f"  ✅ {inserted}/{len(images)} images inserted")

    # 5. Grant permissions
    if user_openid:
        print("\n[5/5] Granting permissions...")
        ok = grant_permission(token, doc_token, user_openid)
        print(f"  {'✅' if ok else '⚠️'} full_access → {user_openid}")
    else:
        print("\n[5/5] No user_openid, skipping permissions")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"✅ Done!")
    raw2 = get_raw_content(token, doc_token)
    print(f"  Content: {len(raw2)} chars")
    print(f"  Doc URL: https://leixiaohui1974.feishu.cn/docx/{doc_token}")
    print(f"{'=' * 60}")
    return True


def sample_config():
    return json.dumps({
        "feishu": {
            "app_id": "cli_a915cc56d5f89cb1",
            "app_secret": "FROM_AGENT_CONFIG"
        },
        "doc_token": "FEISHU_DOC_TOKEN",
        "article_path": "/path/to/article.md",
        "images_dir": "/home/admin/workspace/workspace/articles/images",
        "user_openid": "ou_607e1555930b5636c8b88b176b9d3bf2",
        "skip_content": False,
        "strip_trailing_info": True,
        "images": [
            {
                "filename": "002-ai-evolution-cn.png",
                "insert_after_heading": "一个意外的平行",
                "description": "AI 进化路线图"
            }
        ]
    }, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Feishu Document Publisher")
    parser.add_argument("config", nargs="?", help="Config JSON file")
    parser.add_argument("--sample", action="store_true", help="Print sample config")
    parser.add_argument("--skip-content", action="store_true", help="Skip content writing")
    args = parser.parse_args()

    if args.sample:
        print(sample_config())
        sys.exit(0)

    if not args.config:
        parser.print_help()
        sys.exit(1)

    with open(args.config) as f:
        cfg = json.load(f)

    if args.skip_content:
        cfg["skip_content"] = True

    try:
        run(cfg)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
