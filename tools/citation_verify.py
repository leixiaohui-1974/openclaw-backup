#!/usr/bin/env python3
"""
citation_verify.py - 多源文献验证工具
基于研究发现：74%的AI生成引用是幻觉，必须交叉验证

数据源：
1. verified-refs.md（本地知识库，最高优先级）
2. Semantic Scholar API（2.25亿+论文，免费，1000 req/sec）
3. OpenAlex API（2.4亿+论文，CC0，免费）
4. CrossRef API（备用）

用法：
  python3 citation_verify.py verify chapter6.md --db verified-refs.md
  python3 citation_verify.py batch chapters/ --db verified-refs.md --output report.md
  python3 citation_verify.py enrich "Lei Xiaohui" --output new-refs.md
"""

import re
import sys
import json
import time
import os
from pathlib import Path

# ---- API配置 ----
S2_BASE = "https://api.semanticscholar.org/graph/v1"
OA_BASE = "https://api.openalex.org"
CR_BASE = "https://api.crossref.org/works"

# Semantic Scholar每秒100请求，OpenAlex不限速
S2_DELAY = 0.02
OA_DELAY = 0.01

def extract_citations(text):
    """从Markdown文本中提取所有引用"""
    citations = []
    
    # 格式1: (Author, Year) 或 (Author et al., Year)
    pattern1 = r'\(([A-Z][a-zà-ü]+(?:\s+(?:et\s+al\.|and|&)\s+[A-Z][a-zà-ü]+)?),?\s*(\d{4})\)'
    for m in re.finditer(pattern1, text):
        citations.append({"author": m.group(1), "year": m.group(2), "raw": m.group(0)})
    
    # 格式2: Author (Year) 或 Author et al. (Year)
    pattern2 = r'([A-Z][a-zà-ü]+(?:\s+(?:et\s+al\.|and|&)\s+[A-Z][a-zà-ü]+)?)\s*\((\d{4})\)'
    for m in re.finditer(pattern2, text):
        citations.append({"author": m.group(1), "year": m.group(2), "raw": m.group(0)})
    
    # 格式3: 中文 雷晓辉等(2019) 或 雷晓辉(2019)
    pattern3 = r'([\u4e00-\u9fff]{2,4}(?:等)?)\s*[（(](\d{4})[）)]'
    for m in re.finditer(pattern3, text):
        citations.append({"author": m.group(1), "year": m.group(2), "raw": m.group(0)})
    
    # 格式4: [编号] 参考文献列表项
    pattern4 = r'^\[(\d+)\]\s*(.+?)[\.,]\s*(\d{4})'
    for m in re.finditer(pattern4, text, re.MULTILINE):
        citations.append({"author": m.group(2).strip(), "year": m.group(3), "raw": m.group(0), "ref_num": m.group(1)})
    
    # 去重
    seen = set()
    unique = []
    for c in citations:
        key = f"{c['author']}_{c['year']}"
        if key not in seen:
            seen.add(key)
            unique.append(c)
    
    return unique

def check_local_db(citation, db_path):
    """在verified-refs.md中查找"""
    if not os.path.exists(db_path):
        return None
    
    with open(db_path, 'r') as f:
        db_text = f.read()
    
    author = citation["author"].split(" ")[0]  # 取姓
    year = citation["year"]
    
    # 姓+年份双重匹配
    for line in db_text.split("\n"):
        if author.lower() in line.lower() and year in line:
            return {"source": "local_db", "status": "✅", "match": line.strip()[:120]}
    
    return None

def check_semantic_scholar(citation):
    """Semantic Scholar API验证"""
    try:
        import urllib.request
        import urllib.parse
        
        query = f"{citation['author']} {citation['year']}"
        params = urllib.parse.urlencode({
            "query": query,
            "limit": 3,
            "fields": "title,authors,year,externalIds,citationCount"
        })
        url = f"{S2_BASE}/paper/search?{params}"
        
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "CHS-Research-Bot/1.0")
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        
        if data.get("data"):
            for paper in data["data"]:
                if str(paper.get("year", "")) == citation["year"]:
                    authors = [a.get("name", "") for a in paper.get("authors", [])]
                    return {
                        "source": "semantic_scholar",
                        "status": "✅",
                        "title": paper["title"],
                        "authors": ", ".join(authors[:3]),
                        "year": paper["year"],
                        "citations": paper.get("citationCount", 0),
                        "doi": paper.get("externalIds", {}).get("DOI", "")
                    }
        
        time.sleep(S2_DELAY)
        return None
    except Exception as e:
        return {"source": "semantic_scholar", "status": "⚠️", "error": str(e)}

def check_openalex(citation):
    """OpenAlex API验证"""
    try:
        import urllib.request
        import urllib.parse
        
        author = citation['author'].split(" ")[0]
        query = f"{author}"
        params = urllib.parse.urlencode({
            "search": query,
            "filter": f"publication_year:{citation['year']}",
            "per_page": 3,
            "mailto": "lxh@iwhr.com"  # OpenAlex推荐提供email获得更高限速
        })
        url = f"{OA_BASE}/works?{params}"
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        
        if data.get("results"):
            for work in data["results"]:
                return {
                    "source": "openalex",
                    "status": "✅",
                    "title": work.get("title", ""),
                    "doi": work.get("doi", ""),
                    "cited_by": work.get("cited_by_count", 0),
                    "oa_id": work.get("id", "")
                }
        
        time.sleep(OA_DELAY)
        return None
    except Exception as e:
        return {"source": "openalex", "status": "⚠️", "error": str(e)}

def verify_file(filepath, db_path, verbose=True):
    """验证单个文件中的所有引用"""
    with open(filepath, 'r') as f:
        text = f.read()
    
    citations = extract_citations(text)
    results = []
    
    for i, c in enumerate(citations):
        result = {"citation": c, "checks": []}
        
        # 第1步：本地知识库
        local = check_local_db(c, db_path)
        if local:
            result["checks"].append(local)
            result["final_status"] = "✅ 知识库已有"
        else:
            # 第2步：Semantic Scholar
            s2 = check_semantic_scholar(c)
            if s2 and s2.get("status") == "✅":
                result["checks"].append(s2)
                result["final_status"] = "✅ S2验证"
            else:
                # 第3步：OpenAlex
                oa = check_openalex(c)
                if oa and oa.get("status") == "✅":
                    result["checks"].append(oa)
                    result["final_status"] = "✅ OA验证"
                else:
                    result["final_status"] = "❌ 未验证 (可能是幻觉)"
                    if s2: result["checks"].append(s2)
                    if oa: result["checks"].append(oa)
        
        results.append(result)
        
        if verbose:
            status = result["final_status"]
            print(f"  [{i+1}/{len(citations)}] {status} | {c['raw'][:60]}")
    
    return results

def generate_report(results, filepath):
    """生成验证报告"""
    verified = sum(1 for r in results if "✅" in r["final_status"])
    failed = sum(1 for r in results if "❌" in r["final_status"])
    total = len(results)
    
    report = f"""# 文献验证报告

**文件**: {filepath}
**日期**: {time.strftime('%Y-%m-%d %H:%M')}
**统计**: {total}条引用 | ✅{verified}条验证 | ❌{failed}条未验证

## 验证率: {verified/total*100:.1f}%

{"⚠️ **警告**: 验证率低于90%，建议人工复查未验证引用" if verified/total < 0.9 else "✅ 验证率良好"}

## 详细结果

| # | 引用 | 状态 | 来源 |
|---|------|------|------|
"""
    for i, r in enumerate(results):
        c = r["citation"]
        status = r["final_status"]
        source = r["checks"][0]["source"] if r["checks"] else "无"
        report += f"| {i+1} | {c['raw'][:50]} | {status} | {source} |\n"
    
    if failed > 0:
        report += "\n## ❌ 未验证引用（需人工处理）\n\n"
        for r in results:
            if "❌" in r["final_status"]:
                c = r["citation"]
                report += f"- **{c['raw']}** — 在Semantic Scholar和OpenAlex中均未找到匹配\n"
                report += f"  建议：用web_search搜索完整标题，或确认是否为AI幻觉\n\n"
    
    return report

def enrich_author(author_name, output_path=None):
    """通过作者名从Semantic Scholar获取完整论文列表"""
    try:
        import urllib.request
        import urllib.parse
        
        # 搜索作者
        params = urllib.parse.urlencode({"query": author_name, "limit": 1})
        url = f"{S2_BASE}/author/search?{params}"
        
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "CHS-Research-Bot/1.0")
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        
        if not data.get("data"):
            print(f"未找到作者: {author_name}")
            return
        
        author_id = data["data"][0]["authorId"]
        author_full = data["data"][0]["name"]
        print(f"找到作者: {author_full} (ID: {author_id})")
        
        # 获取论文列表
        params = urllib.parse.urlencode({
            "fields": "title,year,venue,citationCount,externalIds",
            "limit": 100
        })
        url = f"{S2_BASE}/author/{author_id}/papers?{params}"
        
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "CHS-Research-Bot/1.0")
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        papers = sorted(data.get("data", []), key=lambda x: x.get("year", 0), reverse=True)
        
        output = f"# {author_full} 论文列表（Semantic Scholar）\n\n"
        output += f"共 {len(papers)} 篇\n\n"
        
        for p in papers:
            doi = p.get("externalIds", {}).get("DOI", "")
            output += f"- [{p.get('year', '?')}] {p.get('title', 'N/A')} | {p.get('venue', '')} | 被引{p.get('citationCount', 0)} | DOI:{doi}\n"
        
        if output_path:
            with open(output_path, 'w') as f:
                f.write(output)
            print(f"已保存到 {output_path}")
        else:
            print(output)
            
    except Exception as e:
        print(f"错误: {e}")

# ---- CLI ----
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 citation_verify.py verify <文件> --db <verified-refs.md>")
        print("  python3 citation_verify.py batch <目录> --db <verified-refs.md> --output report.md")
        print("  python3 citation_verify.py enrich <作者名> --output new-refs.md")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "verify":
        filepath = sys.argv[2]
        db_path = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--db" else "knowledge-base/refs/verified-refs.md"
        
        print(f"\n📖 验证文件: {filepath}")
        print(f"📚 知识库: {db_path}\n")
        
        results = verify_file(filepath, db_path)
        report = generate_report(results, filepath)
        
        report_path = filepath.replace(".md", "_citation_report.md")
        with open(report_path, 'w') as f:
            f.write(report)
        print(f"\n📋 报告已保存: {report_path}")
    
    elif cmd == "batch":
        dirpath = sys.argv[2]
        db_path = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--db" else "knowledge-base/refs/verified-refs.md"
        
        md_files = list(Path(dirpath).glob("*.md"))
        print(f"\n📂 批量验证: {dirpath} ({len(md_files)}个文件)")
        
        all_results = {}
        for f in md_files:
            print(f"\n--- {f.name} ---")
            all_results[f.name] = verify_file(str(f), db_path)
        
        # 汇总报告
        total = sum(len(r) for r in all_results.values())
        verified = sum(1 for r in sum(all_results.values(), []) if "✅" in r["final_status"])
        print(f"\n📊 汇总: {total}条引用, ✅{verified}条验证, 验证率{verified/total*100:.1f}%")
    
    elif cmd == "enrich":
        author = sys.argv[2]
        output = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--output" else None
        enrich_author(author, output)
    
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
