---
name: feishu-image-pipeline
description: |
  Generate AI images and insert them into Feishu documents. Use when user asks to:
  - add/insert/generate images for a Feishu article or document
  - run image pipeline for an article
  - batch generate illustrations and upload to Feishu
  - "给文章生成图片", "插入配图", "图片pipeline"
homepage: https://open.feishu.cn/
metadata:
  openclaw:
    emoji: "\U0001F5BC"
    requires:
      bins: [uv, python3]
      env: [GEMINI_API_KEY]
    primaryEnv: GEMINI_API_KEY
---

# Feishu Image Pipeline

Batch-generate AI images (via Gemini 3 Pro Image / nano-banana-pro) and insert them into Feishu documents at specified positions.

## Workflow

1. **Prepare config** - Create a JSON config file specifying document token, images (filename, prompt, insert position)
2. **Run pipeline** - Execute the pipeline script
3. **Grant permissions** - Use `feishu_perm` tool to grant user edit access

## Usage

### Step 1: Create pipeline config

Create a JSON file (e.g., `pipeline_002.json`) with this structure:

```json
{
  "feishu": {
    "app_id": "cli_a915cc56d5f89cb1",
    "app_secret": "FROM_ENV_OR_CONFIG"
  },
  "doc_token": "FEISHU_DOC_TOKEN",
  "gemini_api_key": "FROM_ENV",
  "force_chinese_text": true,
  "output_dir": "/home/admin/.openclaw/workspace/workspace/.openclaw/feishu-images",
  "resolution": "2K",
  "skip_generate": false,
  "images": [
    {
      "filename": "002-image-name.png",
      "prompt": "Detailed image description for AI generation...",
      "insert_after_block": "doxcnXXXXX",
      "description": "Human-readable image description"
    }
  ]
}
```

### Step 2: Find document block IDs

Use `feishu_doc` tool to read the document structure and find the block IDs where images should be inserted after:

```
feishu_doc read <doc_token>
```

### Step 3: Run the pipeline

```bash
python3 {baseDir}/scripts/feishu_image_pipeline.py <config.json>
```

Options:
- `--skip-generate` : Skip image generation, use existing image files
- `--sample` : Output a sample config file

### Step 4: Grant permissions (optional)

After pipeline completes, use `feishu_perm` to grant the user edit access:
- Action: `add`
- Token: the doc_token
- Type: `docx`
- Permission: `edit` or `full_access`

## Config Reference

| Field | Required | Description |
|-------|----------|-------------|
| `feishu.app_id` | Yes | Feishu app ID |
| `feishu.app_secret` | Yes | Feishu app secret |
| `doc_token` | Yes | Target document token (from URL) |
| `gemini_api_key` | No | Gemini API key（优先） |
| `api_key` | No | Gemini API key 别名（与 `gemini_api_key` 二选一） |
| `nano_api_key` | No | Gemini API key 别名（与 `gemini_api_key` 二选一） |
| `force_chinese_text` | No | 是否强制图片中的文字为中文（默认 true） |
| `output_dir` | No | Image output directory (default: `~/.openclaw/workspace/workspace/.openclaw/feishu-images`) |
| `resolution` | No | Image resolution: 1K, 2K, 4K (default: 2K) |
| `skip_generate` | No | Skip generation, use existing files (default: false) |
| `degrade_to_existing_images_on_generate_failure` | No | 生成失败时是否自动降级为“仅插入已有图片”（默认 true） |
| `images[].filename` | Yes | Output image filename |
| `images[].prompt` | Yes | AI image generation prompt (English recommended) |
| `images[].insert_after_block` | Yes | Block ID to insert image after |
| `images[].description` | No | Human-readable description |

## Notes

- 该 skill 强制通过 nano-banana-pro 生成图片（Gemini 3 Pro Image）
- 默认会自动给每个 prompt 追加“图中文字必须是简体中文”的约束
- 如需关闭中文约束，可在配置中设置 `force_chinese_text=false`
- 不要用 `message --media <本地路径>` 发送图片；应让脚本直接写入飞书文档，再只回复文档链接
- Use 2K resolution for good quality/size balance
- Pipeline processes images in reverse order to preserve insertion indices
- The script 优先使用 `~/.openclaw/workspace/skills/nano-banana-pro/scripts/generate_image.py`
- Each image takes ~10-30 seconds to generate
- 脚本会在生成前做预检（`uv`、nano脚本、API key、已有图片数），避免“看起来在执行但实际没跑”
- 当生成链路异常且已有图片存在时，默认自动降级为“跳过生成、继续插入”
