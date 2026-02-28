# TOOLS.md - 环境与工具速查

## 服务器环境

- Alibaba Cloud ECS: 47.252.80.72
- OS: Linux (alinux3)
- Python: 3.x + uv
- Node.js: npm/npx 可用
- FFmpeg: 8.0.1 (linuxbrew)
- Go: 已安装（blogwatcher依赖）
- 中文字体: NotoSansCJK (`/usr/share/fonts/google-noto-cjk/`)
- Docker: 运行中（SearXNG）

## MCP 服务器（~/.mcp.json）

| Server | 用途 | 启动方式 |
|--------|------|----------|
| paper-search | 多源论文搜索(arXiv/PubMed/S2/CrossRef) | uv run |
| academic-search | Semantic Scholar + CrossRef | uv run |
| google-scholar | Google Scholar | uv run |
| google-scholar-cn | Google Scholar + 中文翻译 | uv run |
| cnki | 中国知网(Selenium+Chrome) | uv run |
| crossref | DOI验证与元数据 | crossref-mcp |
| playwright | 浏览器自动化(headless Chromium) | playwright-mcp --headless |
| fetch | URL内容抓取→Markdown | mcp-server-fetch |
| github | GitHub仓库/Issue/PR管理 | npx @modelcontextprotocol/server-github |

## TTS

- Engine: Edge TTS (免费，无需 API key)
- 默认语音: `zh-CN-YunxiNeural` (男，标准讲述)
- 其他: YunyangNeural(新闻), XiaoxiaoNeural(温暖), XiaoyiNeural(活力)

## AI 图片生成

- Engine: Gemini 3 Pro Image (nano-banana-pro)
- API Key: 从 openclaw.json gemini provider 读取（旧 key 已失效，需更换）
- 分辨率: 1K/2K(推荐)/4K

## 关键目录

- 工作区: `~/.openclaw/workspace/`
- 技能: `~/.openclaw/workspace/skills/`
- MCP源码: `~/.openclaw/workspace/tools/`
- 文章源文件: `/home/admin/workspace/workspace/articles/`
- 文章图片: `/home/admin/workspace/workspace/articles/images-new/`
- 视频输出: `/home/admin/workspace/workspace/articles/video/`
- Pipeline配置: `~/pipeline_*.json`, `~/video_*.json`
- OSS挂载: `/home/admin/oss-workspace/`

## 飞书凭据

- App ID: `cli_a915cc56d5f89cb1`
- App Secret: `t4fBWSGN56TEzZrNXvvYTbYWOMlZFjxR`

## 微信公众号凭据

- App ID: `wxec3f615e70666460`
- App Secret: `c3cbe57bc9c2e840ab14d2fc417a1c2f`

## 存储管理

```bash
python3 ~/.openclaw/workspace/tools/storage_manager.py status   # 磁盘状态
python3 ~/.openclaw/workspace/tools/storage_manager.py archive  # 归档到OSS
python3 ~/.openclaw/workspace/tools/storage_manager.py clean-cache  # 清理缓存
```
