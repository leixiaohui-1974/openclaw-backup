---
name: mcp-academic-search
description: "学术文献MCP搜索集成。当需要搜索学术论文、验证DOI、查找中国知网文献、OpenAlex全球文献时触发。封装4个MCP服务器的使用方法：CNKI知网、OpenAlex(PaperMCP)、Google Scholar、CrossRef DOI验证。"
version: 1.0.0
tags: [chs, mcp, academic, search, cnki, crossref, openalex]
---

# 学术文献MCP搜索集成

封装4个外部学术搜索MCP服务器的使用方法和配置。

## MCP服务器清单

| 服务器 | 用途 | 数据源 | 语言 |
|--------|------|--------|------|
| cnki-mcp | 中国知网论文搜索 | CNKI | 中文为主 |
| paper-mcp | 全球学术文献搜索 | OpenAlex (2.4亿+) | 中英文 |
| google-scholar | Google学术搜索 | Google Scholar | 多语言 |
| crossref-mcp | DOI验证与元数据 | CrossRef | 英文为主 |

## 使用场景

### 1. 验证参考文献真实性
```
优先级: verified-refs.md → CrossRef (DOI) → OpenAlex → Google Scholar
```

### 2. 搜索中文论文
```
优先级: CNKI → OpenAlex (filter: CN) → Google Scholar
```

### 3. 搜索英文论文
```
优先级: OpenAlex → Google Scholar → CrossRef
```

### 4. 获取DOI和元数据
```
CrossRef: 精确DOI查询，返回完整引用信息
OpenAlex: 按标题/作者搜索，返回引用计数
```

## 服务器端配置

在运行Claude Code的服务器上，将以下内容添加到 `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "cnki-mcp": {
      "command": "python",
      "args": ["<path>/cnki_mcp_server.py"],
      "description": "CNKI知网论文检索"
    },
    "paper-mcp": {
      "command": "node",
      "args": ["<path>/paper-mcp/build/index.js"],
      "description": "OpenAlex全球学术文献搜索"
    },
    "google-scholar": {
      "command": "python",
      "args": ["<path>/google_scholar_server.py"],
      "description": "Google Scholar搜索"
    },
    "crossref-mcp": {
      "command": "crossref-mcp",
      "args": [],
      "description": "CrossRef DOI验证"
    }
  }
}
```

## 安装依赖

### cnki-mcp (Python + Selenium)
```bash
pip install selenium webdriver-manager mcp
# 需要Chrome浏览器
```

### paper-mcp (Node.js)
```bash
cd mcp-servers/paper-mcp && npm install && npm run build
```

### google-scholar (Python)
```bash
pip install scholarly mcp
```

### crossref-mcp (npm全局)
```bash
npm install -g crossref-mcp
```

## 备选方案（无MCP时）

如果运行环境不支持MCP，可使用:
- `tools/citation_verify.py` — 直接调用CrossRef/S2/OpenAlex API的Python脚本
- `skills/ref-search/scripts/ref_search.py` — 三源交叉验证脚本

## MCP源码位置

源码保存在 `scripts/` 子目录供参考和部署。
