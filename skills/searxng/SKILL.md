---
name: searxng
description: |
  Self-hosted SearXNG metasearch engine for private web searching. Use when:
  - Need to search the web without tracking
  - web_search tool is unavailable or rate-limited
  - Need search results in structured JSON format
  - "搜索", "search", "查一下", "帮我搜"
homepage: https://docs.searxng.org/
metadata:
  openclaw:
    emoji: "🔍"
    requires:
      bins: [curl]
---

# SearXNG 元搜索引擎

自托管 SearXNG 实例，运行在本服务器 Docker 中，提供隐私友好的网络搜索。

## Usage

### JSON API 搜索
```bash
curl -s "http://localhost:8080/search?q=<关键词>&format=json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for r in data['results'][:10]:
    print(f\"- {r['title']}\")
    print(f\"  {r['url']}\")
    print(f\"  {r.get('content','')[:100]}\")
    print()
"
```

### 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `q` | 搜索关键词 | `q=water+informatics` |
| `format` | 输出格式 | `format=json` |
| `language` | 搜索语言 | `language=zh-CN` |
| `categories` | 搜索分类 | `categories=science` |
| `time_range` | 时间范围 | `time_range=year` |
| `pageno` | 页码 | `pageno=2` |

### 可用分类
- `general` — 通用搜索
- `science` — 学术搜索
- `it` — IT/技术
- `images` — 图片搜索
- `news` — 新闻

## 服务管理

```bash
# 状态检查
docker ps --filter name=searxng

# 重启
docker restart searxng

# 配置文件
~/.openclaw/workspace/skills/searxng/scripts/config/settings.yml
```

## Notes

- 服务运行在 `http://localhost:8080`
- JSON API 已启用
- 无需 API Key
- 支持 30+ 搜索引擎聚合
