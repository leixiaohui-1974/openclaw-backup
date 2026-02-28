---
name: wechat-publish
description: |
  Publish Feishu documents to WeChat Official Account (微信公众号) OR export as HTML and share via Feishu.
  Use when user asks to:
  - publish/push article to WeChat / 公众号
  - send Feishu doc to WeChat official account
  - "发到公众号", "发布到微信公众号", "推送公众号文章"
  - export Feishu document as HTML and send to user
  - "把飞书文档转 HTML 发给我"
homepage: https://mp.weixin.qq.com/
metadata:
  openclaw:
    emoji: "\U0001F4F1"
---

# WeChat Official Account Publisher & Feishu HTML Export

Two modes:
1. **WeChat Publish**: Export Feishu doc → WeChat HTML → Create draft
2. **Feishu HTML Share**: Export Feishu doc → HTML with embedded images → Send via Feishu message

## Mode 1: WeChat Publish

### Workflow

1. Read Feishu document content (all blocks)
2. Convert to WeChat-compatible HTML (with inline styles)
3. Migrate images: download from Feishu → upload to WeChat
4. Create draft in WeChat Official Account
5. Optionally auto-publish

### Usage

```json
{
  "mode": "wechat",
  "feishu": {
    "app_id": "cli_a915cc56d5f89cb1",
    "app_secret": "FROM_CONFIG"
  },
  "wechat": {
    "app_id": "wxec3f615e70666460",
    "app_secret": "FROM_CONFIG"
  },
  "doc_token": "FEISHU_DOC_TOKEN",
  "title": "",
  "author": "作者名",
  "auto_publish": false
}
```

```bash
python3 {baseDir}/scripts/wechat_publish.py <config.json>
```

## Mode 2: Feishu HTML Share (Recommended)

### Workflow

1. Read Feishu document content (all blocks)
2. Convert to HTML with embedded images (base64)
3. Upload HTML file to Feishu Drive
4. Send Feishu card message + file message to user

### Usage

```json
{
  "mode": "feishu_html",
  "feishu": {
    "app_id": "cli_a915cc56d5f89cb1",
    "app_secret": "FROM_CONFIG"
  },
  "doc_token": "FEISHU_DOC_TOKEN",
  "title": "",
  "author": "雷晓辉",
  "user_id": "ou_xxx",
  "auto_send": true
}
```

```bash
python3 {baseDir}/scripts/feishu_html_share.py <config.json>
```

Options:
- `--nosend` : 仅生成 HTML 文件，不发送消息
- `--sample` : 输出示例配置

## Config Reference

| Field | Required | Description |
|-------|----------|-------------|
| `feishu.app_id` | Yes | 飞书 App ID |
| `feishu.app_secret` | Yes | 飞书 App Secret |
| `wechat.app_id` | WeChat mode | 微信公众号 App ID |
| `wechat.app_secret` | WeChat mode | 微信公众号 App Secret |
| `doc_token` | Yes | 飞书文档 token |
| `title` | No | 文章标题（留空自动提取） |
| `author` | No | 作者名 |
| `user_id` | Feishu mode | 接收消息的飞书用户 ID |
| `auto_send` | Feishu mode | 是否自动发送（默认 true） |

## Notes

**WeChat Publish:**
- 微信公众号文章不支持外链图片，所有图片都会自动从飞书下载后重新上传到微信
- HTML 使用内联样式（微信不支持外部 CSS）
- 复杂表格和数学公式可能需要手动调整
- 建议先创建草稿，在公众号后台预览确认后再发布

**Feishu HTML Share:**
- ✅ 图片嵌入 HTML（base64 编码），离线也可查看
- ✅ 自动上传到飞书云盘，发送卡片消息 + 文件消息
- ✅ 无需公众号权限，个人用户即可使用
- ✅ 支持移动端和桌面端查看
- 生成的 HTML 文件包含完整样式，可直接在浏览器打开
