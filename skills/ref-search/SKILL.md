---
name: ref-search
description: 中英文学术文献检索与验证，三源交叉确认（CrossRef + Semantic Scholar + OpenAlex），动态更新参考文献库。确保每条入库文献都是正式出版、可检索的。
metadata:
  clawdbot:
    requires:
      bins: [python3]
---

# ref-search — 学术文献检索与验证

三源交叉确认，确保每条文献都是正式出版、可检索的。

## 数据源

| API | 覆盖量 | 用途 | 置信度加分 |
|-----|--------|------|-----------|
| CrossRef | DOI 金标准 | DOI 验证、期刊元数据 | +0.50 |
| Semantic Scholar | 2.25 亿+ | 论文搜索、作者消歧、引用数 | +0.25 |
| OpenAlex | 2.4 亿+ | 中文覆盖最好、CC0 | +0.25 |

## 命令

```bash
SCRIPT=~/.openclaw/workspace/skills/ref-search/scripts/ref_search.py

# 搜索文献
python3 $SCRIPT search "model predictive control water" --limit 10

# 按作者检索
python3 $SCRIPT author "Lei Xiaohui" --limit 20

# 验证单条（DOI 或 标题+年份）
python3 $SCRIPT verify --doi "10.1061/(ASCE)WR.1943-5452.0001092"
python3 $SCRIPT verify --title "Model predictive control for water distribution" --year 2019

# 验证并导入数据库
python3 $SCRIPT import --doi "10.1061/xxx" --id T02 --db path/to/verified-refs.md

# 批量验证作者论文并入库
python3 $SCRIPT enrich "Lei Xiaohui" --db path/to/verified-refs.md

# 查看数据库统计
python3 $SCRIPT status --db path/to/verified-refs.md
```

## 置信度评分

| 等级 | 分数 | 含义 |
|------|------|------|
| VERIFIED | >= 0.70 | 多源确认，可自动入库 |
| PROBABLE | 0.40-0.69 | 单源确认，需人工复查 |
| UNVERIFIED | < 0.40 | 无法确认，禁止入库 |

## 注意

- 仅依赖 Python 标准库（urllib），无需安装额外包
- 入库前自动去重（DOI 匹配 / 标题+年份模糊匹配）
- UNVERIFIED 文献**绝对不入库**，避免幻觉引用
- 默认数据库路径：`knowledge-base/refs/verified-refs.md`
