---
name: feishu-doc-publisher
description: |
  Write Markdown articles to Feishu documents and insert images. Use when user asks to:
  - publish/write article to Feishu document
  - insert images into Feishu doc
  - populate empty Feishu document with content
  - "写入飞书", "发布到飞书", "文档配图", "写文档加图片"
homepage: https://open.feishu.cn/
metadata:
  openclaw:
    emoji: "📝"
    requires:
      bins: [python3]
---

# Feishu Document Publisher

一站式完成：Markdown 文章 → 飞书文档正文 + 自动插图 + 权限授予。

## 与 feishu-image-pipeline 的区别

| | feishu-image-pipeline | feishu-doc-publisher |
|---|---|---|
| **功能** | AI 生成图片 + 插入已有文档 | 写入文档正文 + 插入已有图片 |
| **前提** | 文档必须有内容（需要 block_id） | 文档可以为空 |
| **图片来源** | Gemini AI 生成 | 本地已有图片文件 |
| **适用场景** | AI 配图 | 文章首次发布到飞书 |

## 典型使用场景

1. OpenClaw agent 写完文章 markdown + 生成好图片后，调用本 skill 一键发布到飞书
2. 文档已有内容时自动跳过写入，只插图

## Usage

### Step 1: 准备配置文件

```json
{
  "feishu": {
    "app_id": "cli_a915cc56d5f89cb1",
    "app_secret": "t4fBWSGN56TEzZrNXvvYTbYWOMlZFjxR"
  },
  "doc_token": "飞书文档token",
  "article_path": "/path/to/article.md",
  "images_dir": "/home/admin/workspace/workspace/articles/images",
  "user_openid": "ou_607e1555930b5636c8b88b176b9d3bf2",
  "strip_trailing_info": true,
  "images": [
    {
      "filename": "002-ai-evolution-cn.png",
      "insert_after_heading": "一个意外的平行",
      "description": "AI 进化路线图"
    }
  ]
}
```

### Step 2: 运行

```bash
python3 {baseDir}/scripts/feishu_doc_publisher.py <config.json>
```

Options:
- `--sample` : 输出示例配置
- `--skip-content` : 跳过写正文，只插图

## 工作流程

```
1. 认证 → 获取飞书 tenant_access_token
2. 读取文档结构 → 获取 top-level blocks
3. 覆盖正文 → 默认先清空正文 blocks（可保留标题）再批量写入
4. 插图 → 根据 insert_after_heading 定位章节末尾，插入图片
5. 校验+授权 → 校验写入长度，再给 user_openid 添加 full_access
```

## 支持的 Markdown 元素

| 元素 | 飞书 block_type | 状态 |
|------|----------------|------|
| `## H2` | heading2 (4) | ✅ |
| `### H3` | heading3 (5) | ✅ |
| `#### H4` | heading4 (6) | ✅ |
| 段落 | text (2) | ✅ |
| `- 列表` | bullet (12) | ✅ |
| `1. 有序列表` | ordered (13) | ✅ |
| ` ```代码块``` ` | code (14) | ✅ |
| `> 引用` | quote (15) | ✅ |
| `---` 分割线 | divider (22) | ✅ |
| `**加粗**` | bold 样式 | ✅ |
| `[链接](url)` | link 样式 | ✅ |
| `*斜体*` | italic 样式 | ✅ |
| 表格 `| |` | 原生表格 (31) | ✅ |

## Config Reference

| Field | Required | Description |
|-------|----------|-------------|
| `feishu.app_id` | Yes | 飞书 App ID |
| `feishu.app_secret` | Yes | 飞书 App Secret |
| `doc_token` | Yes | 目标文档 token |
| `article_path` | Yes | Markdown 文件路径 |
| `images_dir` | No | 图片目录（默认当前目录） |
| `user_openid` | No | 授权用户 OpenID |
| `skip_content` | No | 跳过写正文（默认 false） |
| `overwrite_content` | No | 是否覆盖正文（默认 true） |
| `keep_title_block` | No | 覆盖时保留标题块（默认 true） |
| `strip_trailing_info` | No | 去除末尾个人信息（默认 true） |
| `images[].filename` | Yes | 图片文件名 |
| `images[].insert_after_heading` | Yes | 在此标题的章节末尾插图 |
| `images[].description` | No | 图片描述 |

## Notes

- 默认强制覆盖正文（先清空再写），避免“只保留标题/旧正文未更新”
- 图片按从后往前的顺序插入，避免索引偏移
- 每次插图前重新读取文档结构，确保索引准确
- 写入后会做长度校验，防止正文写入不完整
- 表格因飞书 API 复杂性，转为纯文本行（用 │ 分隔）
