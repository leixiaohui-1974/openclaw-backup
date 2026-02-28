#!/usr/bin/env python3
"""
ref_search.py - 中英文学术文献检索与验证工具
三源交叉确认（CrossRef + Semantic Scholar + OpenAlex），动态更新参考文献库。
确保每条入库文献都是正式出版、可检索的。

用法：
  python3 ref_search.py search "model predictive control water" --limit 10
  python3 ref_search.py author "Lei Xiaohui" --limit 20
  python3 ref_search.py verify --doi "10.1061/xxx"
  python3 ref_search.py verify --title "..." --year 2019
  python3 ref_search.py import --doi "10.1061/xxx" --id T02 --db verified-refs.md
  python3 ref_search.py enrich "Lei Xiaohui" --db verified-refs.md
  python3 ref_search.py status --db verified-refs.md
"""

import re
import sys
import json
import time
import os
import urllib.request
import urllib.parse
from datetime import datetime

# ---- API 配置 ----
CR_BASE = "https://api.crossref.org/works"
S2_BASE = "https://api.semanticscholar.org/graph/v1"
OA_BASE = "https://api.openalex.org"

# 限速
CR_DELAY = 0.1
S2_DELAY = 0.05
OA_DELAY = 0.02

MAILTO = "lxh@iwhr.com"
UA = "CHS-RefSearch/1.0 (mailto:{})".format(MAILTO)

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "..", "knowledge-base", "refs", "verified-refs.md")

# ---- HTTP 工具 ----

def _get(url, timeout=15):
    """发送 GET 请求，返回 JSON"""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

# ---- CrossRef API ----

def search_crossref(query, limit=10):
    """CrossRef 搜索"""
    params = urllib.parse.urlencode({
        "query": query,
        "rows": limit,
        "mailto": MAILTO,
        "select": "DOI,title,author,published-print,published-online,container-title,is-referenced-by-count,type"
    })
    data = _get(f"{CR_BASE}?{params}")
    if "error" in data:
        return []
    results = []
    for item in data.get("message", {}).get("items", []):
        title = item.get("title", [""])[0] if item.get("title") else ""
        authors = []
        for a in item.get("author", []):
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                authors.append(name)
        pub = item.get("published-print") or item.get("published-online") or {}
        parts = pub.get("date-parts", [[None]])[0]
        year = str(parts[0]) if parts and parts[0] else ""
        results.append({
            "title": title,
            "authors": authors,
            "year": year,
            "journal": ", ".join(item.get("container-title", [])),
            "doi": item.get("DOI", ""),
            "citations": item.get("is-referenced-by-count", 0),
            "source": "crossref",
            "type": item.get("type", "")
        })
    time.sleep(CR_DELAY)
    return results

def verify_crossref_doi(doi):
    """通过 DOI 精确查询 CrossRef"""
    encoded = urllib.parse.quote(doi, safe="")
    data = _get(f"{CR_BASE}/{encoded}?mailto={MAILTO}")
    if "error" in data or "message" not in data:
        return None
    item = data["message"]
    title = item.get("title", [""])[0] if item.get("title") else ""
    authors = []
    for a in item.get("author", []):
        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
        if name:
            authors.append(name)
    pub = item.get("published-print") or item.get("published-online") or {}
    parts = pub.get("date-parts", [[None]])[0]
    year = str(parts[0]) if parts and parts[0] else ""
    time.sleep(CR_DELAY)
    return {
        "title": title,
        "authors": authors,
        "year": year,
        "journal": ", ".join(item.get("container-title", [])),
        "doi": item.get("DOI", ""),
        "citations": item.get("is-referenced-by-count", 0),
        "source": "crossref"
    }

# ---- Semantic Scholar API ----

def search_semantic_scholar(query, limit=10):
    """Semantic Scholar 搜索"""
    params = urllib.parse.urlencode({
        "query": query,
        "limit": limit,
        "fields": "title,authors,year,externalIds,citationCount,venue,publicationTypes"
    })
    data = _get(f"{S2_BASE}/paper/search?{params}")
    if "error" in data:
        return []
    results = []
    for paper in data.get("data", []):
        authors = [a.get("name", "") for a in paper.get("authors", [])]
        doi = paper.get("externalIds", {}).get("DOI", "")
        results.append({
            "title": paper.get("title", ""),
            "authors": authors,
            "year": str(paper.get("year", "")),
            "journal": paper.get("venue", ""),
            "doi": doi,
            "citations": paper.get("citationCount", 0),
            "source": "semantic_scholar",
            "types": paper.get("publicationTypes", [])
        })
    time.sleep(S2_DELAY)
    return results

def search_s2_by_author(author_name, limit=50):
    """Semantic Scholar 按作者搜索"""
    params = urllib.parse.urlencode({"query": author_name, "limit": 1})
    data = _get(f"{S2_BASE}/author/search?{params}")
    if "error" in data or not data.get("data"):
        return [], None
    author_id = data["data"][0]["authorId"]
    author_full = data["data"][0]["name"]
    params = urllib.parse.urlencode({
        "fields": "title,year,venue,citationCount,externalIds,publicationTypes",
        "limit": limit
    })
    data = _get(f"{S2_BASE}/author/{author_id}/papers?{params}")
    if "error" in data:
        return [], author_full
    papers = []
    for p in data.get("data", []):
        doi = p.get("externalIds", {}).get("DOI", "")
        papers.append({
            "title": p.get("title", ""),
            "authors": [author_full],
            "year": str(p.get("year", "")),
            "journal": p.get("venue", ""),
            "doi": doi,
            "citations": p.get("citationCount", 0),
            "source": "semantic_scholar"
        })
    time.sleep(S2_DELAY)
    return sorted(papers, key=lambda x: int(x.get("year") or 0), reverse=True), author_full

# ---- OpenAlex API ----

def search_openalex(query, limit=10):
    """OpenAlex 搜索"""
    params = urllib.parse.urlencode({
        "search": query,
        "per_page": limit,
        "mailto": MAILTO
    })
    data = _get(f"{OA_BASE}/works?{params}")
    if "error" in data:
        return []
    results = []
    for work in data.get("results", []):
        authors = []
        for auth in work.get("authorships", []):
            name = auth.get("author", {}).get("display_name", "")
            if name:
                authors.append(name)
        doi_raw = work.get("doi", "") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""
        results.append({
            "title": work.get("title", ""),
            "authors": authors,
            "year": str(work.get("publication_year", "")),
            "journal": work.get("primary_location", {}).get("source", {}).get("display_name", "") if work.get("primary_location") else "",
            "doi": doi,
            "citations": work.get("cited_by_count", 0),
            "source": "openalex"
        })
    time.sleep(OA_DELAY)
    return results

# ---- 置信度评分 ----

def verify_single(doi=None, title=None, author=None, year=None):
    """多源交叉验证单条文献，返回置信度"""
    confidence = 0.0
    sources = []
    metadata = {}

    # CrossRef 验证
    if doi:
        cr = verify_crossref_doi(doi)
        if cr:
            confidence += 0.50
            sources.append("crossref")
            metadata = cr
    else:
        query_parts = []
        if title:
            query_parts.append(title)
        if author:
            query_parts.append(author)
        query = " ".join(query_parts)
        cr_results = search_crossref(query, limit=3)
        for r in cr_results:
            if _match_result(r, title, author, year):
                confidence += 0.50
                sources.append("crossref")
                metadata = r
                break

    # Semantic Scholar 验证
    query_parts = []
    if title:
        query_parts.append(title[:80])
    elif author:
        query_parts.append(author)
    if year:
        query_parts.append(str(year))
    s2_query = " ".join(query_parts)
    if s2_query.strip():
        s2_results = search_semantic_scholar(s2_query, limit=3)
        for r in s2_results:
            if _match_result(r, title, author, year):
                confidence += 0.25
                sources.append("semantic_scholar")
                if not metadata:
                    metadata = r
                elif not metadata.get("doi") and r.get("doi"):
                    metadata["doi"] = r["doi"]
                break

    # OpenAlex 验证
    oa_query = s2_query
    if oa_query.strip():
        oa_results = search_openalex(oa_query, limit=3)
        for r in oa_results:
            if _match_result(r, title, author, year):
                confidence += 0.25
                sources.append("openalex")
                if not metadata:
                    metadata = r
                elif not metadata.get("doi") and r.get("doi"):
                    metadata["doi"] = r["doi"]
                break

    # DOI 精确匹配加分
    if doi and metadata.get("doi") and _normalize_doi(doi) == _normalize_doi(metadata["doi"]):
        confidence = max(confidence, 0.80)

    # 判定等级
    if confidence >= 0.70:
        level = "VERIFIED"
    elif confidence >= 0.40:
        level = "PROBABLE"
    else:
        level = "UNVERIFIED"

    return {
        "confidence": round(confidence, 2),
        "level": level,
        "sources": sources,
        "metadata": metadata
    }

def _normalize_doi(doi):
    """标准化 DOI"""
    return doi.strip().lower().replace("https://doi.org/", "")

def _normalize_text(text):
    """标准化文本用于比较"""
    if not text:
        return ""
    return re.sub(r'[^\w\s]', '', text.lower()).strip()

def _match_result(result, title=None, author=None, year=None):
    """检查搜索结果是否匹配"""
    if year and result.get("year") and str(result["year"]) != str(year):
        return False
    if title:
        r_title = _normalize_text(result.get("title", ""))
        q_title = _normalize_text(title)
        if not r_title or not q_title:
            return False
        # 计算简单相似度：共有词 / 总词数
        r_words = set(r_title.split())
        q_words = set(q_title.split())
        if not q_words:
            return False
        overlap = len(r_words & q_words) / len(q_words)
        if overlap < 0.5:
            return False
    if author and not title:
        author_lower = author.lower().split()[0] if author else ""
        result_authors = " ".join(result.get("authors", [])).lower()
        if author_lower and author_lower not in result_authors:
            return False
    return True

# ---- 数据库操作 ----

def load_db(db_path):
    """解析 verified-refs.md，返回条目列表"""
    if not os.path.exists(db_path):
        return []
    with open(db_path, 'r', encoding='utf-8') as f:
        text = f.read()
    entries = []
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith('|') or line.startswith('|--') or line.startswith('| ID'):
            continue
        parts = [p.strip() for p in line.split('|')]
        parts = [p for p in parts if p]
        if len(parts) >= 6:
            entry = {
                "id": parts[0],
                "authors": parts[1],
                "year": parts[2],
                "title": parts[3],
                "journal": parts[4],
                "doi": parts[5] if len(parts) > 5 else "",
                "verified": parts[6] if len(parts) > 6 else ""
            }
            if entry["id"] and entry["id"] not in ("ID", "---"):
                entries.append(entry)
    return entries

def is_duplicate(entry, db_entries):
    """检查是否重复"""
    doi = _normalize_doi(entry.get("doi", ""))
    title = _normalize_text(entry.get("title", ""))
    year = str(entry.get("year", ""))

    for e in db_entries:
        # DOI 精确匹配
        e_doi = _normalize_doi(e.get("doi", ""))
        if doi and e_doi and doi == e_doi:
            return True, e["id"]
        # 标题+年份模糊匹配
        e_title = _normalize_text(e.get("title", ""))
        if title and e_title and year and e.get("year") == year:
            t_words = set(title.split())
            e_words = set(e_title.split())
            if t_words and e_words:
                overlap = len(t_words & e_words) / max(len(t_words), 1)
                if overlap > 0.8:
                    return True, e["id"]
    return False, None

def next_id(db_entries, prefix="NEW"):
    """生成下一个 ID"""
    max_num = 0
    pattern = re.compile(rf'^{prefix}-?(\d+)$')
    for e in db_entries:
        m = pattern.match(e.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-{max_num + 1:03d}"

def save_to_db(entry, db_path, entry_id=None):
    """追加条目到 verified-refs.md 的 NEW 区域"""
    db_entries = load_db(db_path)
    dup, dup_id = is_duplicate(entry, db_entries)
    if dup:
        return False, f"已存在: {dup_id}"

    if not entry_id:
        entry_id = next_id(db_entries, "NEW")

    authors_str = entry.get("authors", "")
    if isinstance(authors_str, list):
        if len(authors_str) > 3:
            authors_str = f"{authors_str[0]}, et al."
        else:
            authors_str = ", ".join(authors_str)

    doi = entry.get("doi", "") or "—"
    today = datetime.now().strftime("%Y-%m-%d")
    sources = entry.get("sources", ["api"])
    source_str = "/".join(sources) if isinstance(sources, list) else str(sources)
    verified_str = f"✅ {source_str} {today}"

    new_line = f"| {entry_id} | {authors_str} | {entry.get('year', '')} | {entry.get('title', '')} | {entry.get('journal', '')} | {doi} | {verified_str} |"

    with open(db_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 插入到 <!-- 由 ref-checker 注释之前
    marker = "<!-- 由 ref-checker"
    if marker in content:
        content = content.replace(marker, new_line + "\n" + marker)
    else:
        # 插入到文件末尾
        content = content.rstrip() + "\n" + new_line + "\n"

    with open(db_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return True, entry_id

# ---- CLI 命令实现 ----

def cmd_search(args):
    """搜索文献"""
    query = args[0] if args else ""
    limit = 10
    lang = "both"
    i = 1
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--lang" and i + 1 < len(args):
            lang = args[i + 1]
            i += 2
        else:
            i += 1

    if not query:
        print("用法: ref_search.py search \"关键词\" [--limit N] [--lang en|cn|both]")
        sys.exit(1)

    print(f"\n🔍 搜索: \"{query}\" (limit={limit}, lang={lang})\n")

    all_results = []

    # CrossRef
    print("  [1/3] CrossRef...", end=" ", flush=True)
    cr = search_crossref(query, limit)
    print(f"{len(cr)} 条")
    for r in cr:
        r["_from"] = "CR"
    all_results.extend(cr)

    # Semantic Scholar
    print("  [2/3] Semantic Scholar...", end=" ", flush=True)
    s2 = search_semantic_scholar(query, limit)
    print(f"{len(s2)} 条")
    for r in s2:
        r["_from"] = "S2"
    all_results.extend(s2)

    # OpenAlex
    print("  [3/3] OpenAlex...", end=" ", flush=True)
    oa = search_openalex(query, limit)
    print(f"{len(oa)} 条")
    for r in oa:
        r["_from"] = "OA"
    all_results.extend(oa)

    # 去重合并
    merged = _merge_results(all_results)
    merged.sort(key=lambda x: x.get("citations", 0), reverse=True)

    print(f"\n📊 合并去重后: {len(merged)} 条\n")
    print("-" * 100)
    for i, r in enumerate(merged[:limit]):
        sources = r.get("_sources", set())
        src_str = ",".join(sorted(sources))
        doi_str = f"DOI:{r['doi']}" if r.get("doi") else "无DOI"
        authors = r.get("authors", [])
        auth_str = ", ".join(authors[:3])
        if len(authors) > 3:
            auth_str += " et al."
        print(f"  [{i+1}] [{r.get('year', '?')}] {r.get('title', 'N/A')[:80]}")
        print(f"      {auth_str}")
        print(f"      {r.get('journal', '')} | 被引:{r.get('citations', 0)} | {doi_str} | 来源:[{src_str}]")
        print()

def cmd_author(args):
    """按作者搜索"""
    author = args[0] if args else ""
    limit = 50
    i = 1
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            i += 1

    if not author:
        print("用法: ref_search.py author \"作者名\" [--limit N]")
        sys.exit(1)

    print(f"\n👤 搜索作者: \"{author}\" (limit={limit})\n")

    papers, full_name = search_s2_by_author(author, limit)
    if full_name:
        print(f"  找到作者: {full_name}")

    # 补充 OpenAlex
    print(f"  Semantic Scholar: {len(papers)} 篇")
    oa_params = urllib.parse.urlencode({
        "search": author,
        "per_page": 5,
        "mailto": MAILTO
    })
    oa_data = _get(f"{OA_BASE}/authors?{oa_params}")
    oa_papers = []
    if not oa_data.get("error") and oa_data.get("results"):
        oa_author = oa_data["results"][0]
        oa_id = oa_author.get("id", "").split("/")[-1]
        if oa_id:
            works_params = urllib.parse.urlencode({
                "filter": f"author.id:{oa_id}",
                "per_page": limit,
                "sort": "publication_year:desc",
                "mailto": MAILTO
            })
            works_data = _get(f"{OA_BASE}/works?{works_params}")
            if not works_data.get("error"):
                for w in works_data.get("results", []):
                    doi_raw = w.get("doi", "") or ""
                    doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""
                    oa_papers.append({
                        "title": w.get("title", ""),
                        "year": str(w.get("publication_year", "")),
                        "journal": w.get("primary_location", {}).get("source", {}).get("display_name", "") if w.get("primary_location") else "",
                        "doi": doi,
                        "citations": w.get("cited_by_count", 0),
                        "source": "openalex"
                    })
    print(f"  OpenAlex: {len(oa_papers)} 篇")

    # 合并
    all_papers = []
    seen_dois = set()
    seen_titles = set()
    for p in papers + oa_papers:
        doi = _normalize_doi(p.get("doi", ""))
        title_key = _normalize_text(p.get("title", ""))[:50]
        if doi and doi in seen_dois:
            continue
        if title_key and title_key in seen_titles:
            continue
        if doi:
            seen_dois.add(doi)
        if title_key:
            seen_titles.add(title_key)
        all_papers.append(p)

    all_papers.sort(key=lambda x: int(x.get("year") or 0), reverse=True)

    print(f"\n📊 合并去重: {len(all_papers)} 篇\n")
    print("-" * 100)
    for i, p in enumerate(all_papers[:limit]):
        doi_str = f"DOI:{p['doi']}" if p.get("doi") else "无DOI"
        print(f"  [{i+1}] [{p.get('year', '?')}] {p.get('title', 'N/A')[:80]}")
        print(f"      {p.get('journal', '')} | 被引:{p.get('citations', 0)} | {doi_str}")
        print()

def cmd_verify(args):
    """验证单条文献"""
    doi = None
    title = None
    author = None
    year = None
    i = 0
    while i < len(args):
        if args[i] == "--doi" and i + 1 < len(args):
            doi = args[i + 1]
            i += 2
        elif args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif args[i] == "--author" and i + 1 < len(args):
            author = args[i + 1]
            i += 2
        elif args[i] == "--year" and i + 1 < len(args):
            year = args[i + 1]
            i += 2
        else:
            i += 1

    if not doi and not title:
        print("用法: ref_search.py verify --doi \"10.xxx\" 或 --title \"...\" [--author \"...\"] [--year 2024]")
        sys.exit(1)

    print(f"\n🔬 验证文献:")
    if doi:
        print(f"  DOI: {doi}")
    if title:
        print(f"  标题: {title}")
    if author:
        print(f"  作者: {author}")
    if year:
        print(f"  年份: {year}")
    print()

    result = verify_single(doi=doi, title=title, author=author, year=year)

    conf = result["confidence"]
    level = result["level"]
    sources = result["sources"]
    meta = result["metadata"]

    if level == "VERIFIED":
        icon = "✅"
    elif level == "PROBABLE":
        icon = "⚠️"
    else:
        icon = "❌"

    print(f"  {icon} 置信度: {conf:.2f} ({level})")
    print(f"  验证来源: {', '.join(sources) if sources else '无'}")

    if meta:
        print(f"\n  📄 元数据:")
        print(f"     标题: {meta.get('title', 'N/A')}")
        auth = meta.get("authors", [])
        if isinstance(auth, list):
            auth_str = ", ".join(auth[:5])
        else:
            auth_str = str(auth)
        print(f"     作者: {auth_str}")
        print(f"     年份: {meta.get('year', 'N/A')}")
        print(f"     期刊: {meta.get('journal', 'N/A')}")
        print(f"     DOI:  {meta.get('doi', 'N/A')}")
        print(f"     被引: {meta.get('citations', 'N/A')}")

    if level == "VERIFIED":
        print(f"\n  ✅ 该文献可入库。运行 import 命令导入。")
    elif level == "PROBABLE":
        print(f"\n  ⚠️ 该文献可能存在但需人工确认。")
    else:
        print(f"\n  ❌ 该文献无法验证，可能不存在或为幻觉引用。禁止入库。")

    return result

def cmd_import(args):
    """验证并导入文献到数据库"""
    doi = None
    title = None
    author = None
    year = None
    entry_id = None
    db_path = DEFAULT_DB
    i = 0
    while i < len(args):
        if args[i] == "--doi" and i + 1 < len(args):
            doi = args[i + 1]
            i += 2
        elif args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif args[i] == "--author" and i + 1 < len(args):
            author = args[i + 1]
            i += 2
        elif args[i] == "--year" and i + 1 < len(args):
            year = args[i + 1]
            i += 2
        elif args[i] == "--id" and i + 1 < len(args):
            entry_id = args[i + 1]
            i += 2
        elif args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        else:
            i += 1

    if not doi and not title:
        print("用法: ref_search.py import --doi \"10.xxx\" [--id T02] [--db path]")
        sys.exit(1)

    # 先验证
    result = verify_single(doi=doi, title=title, author=author, year=year)
    if result["level"] == "UNVERIFIED":
        print(f"\n❌ 验证失败 (置信度={result['confidence']:.2f})。文献不满足入库标准（≥0.70），拒绝导入。")
        sys.exit(1)

    if result["level"] == "PROBABLE":
        print(f"\n⚠️ 置信度={result['confidence']:.2f}，仅达 PROBABLE 级别。")
        print("  建议提供更多信息（如 DOI）后重试，或使用 --force 强制导入。")
        if "--force" not in args:
            sys.exit(1)

    meta = result["metadata"]
    if not meta:
        print("\n❌ 验证通过但未获取元数据，无法入库。")
        sys.exit(1)

    meta["sources"] = result["sources"]

    # 导入
    db_path = os.path.abspath(db_path)
    success, msg = save_to_db(meta, db_path, entry_id)
    if success:
        print(f"\n✅ 已导入: {msg}")
        print(f"   → {db_path}")
        m = meta
        print(f"   标题: {m.get('title', '')[:60]}")
        print(f"   DOI: {m.get('doi', 'N/A')}")
        print(f"   置信度: {result['confidence']:.2f} ({result['level']})")
    else:
        print(f"\n⚠️ 未导入: {msg}")

def cmd_enrich(args):
    """批量搜索作者论文并导入已验证的"""
    author = args[0] if args else ""
    db_path = DEFAULT_DB
    limit = 20
    i = 1
    while i < len(args):
        if args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            i += 1

    if not author:
        print("用法: ref_search.py enrich \"作者名\" [--db path] [--limit N]")
        sys.exit(1)

    db_path = os.path.abspath(db_path)
    db_entries = load_db(db_path)

    print(f"\n🔬 批量验证作者论文: \"{author}\"")
    print(f"   数据库: {db_path} ({len(db_entries)} 条已有)")
    print()

    papers, full_name = search_s2_by_author(author, limit)
    if full_name:
        print(f"  找到作者: {full_name} ({len(papers)} 篇)")
    else:
        print(f"  ❌ 未找到作者: {author}")
        return

    added = 0
    skipped = 0
    failed = 0

    for idx, p in enumerate(papers[:limit]):
        doi = p.get("doi", "")
        title = p.get("title", "")
        print(f"\n  [{idx+1}/{min(len(papers), limit)}] {title[:60]}...")

        # 检查去重
        dup, dup_id = is_duplicate(p, db_entries)
        if dup:
            print(f"    ⏭️ 已存在 ({dup_id})")
            skipped += 1
            continue

        # CrossRef 交叉验证
        if doi:
            cr = verify_crossref_doi(doi)
            if cr:
                p["sources"] = ["crossref", "semantic_scholar"]
                success, msg = save_to_db(p, db_path)
                if success:
                    print(f"    ✅ 入库 ({msg}) DOI:{doi}")
                    added += 1
                    db_entries = load_db(db_path)  # 刷新
                else:
                    print(f"    ⚠️ {msg}")
                    skipped += 1
                continue

        # 无 DOI 或 CrossRef 未找到
        print(f"    ⚠️ 无法交叉验证（{'无DOI' if not doi else 'CrossRef未找到'}），跳过")
        failed += 1

    print(f"\n📊 enrich 完成:")
    print(f"   ✅ 新入库: {added}")
    print(f"   ⏭️ 已存在: {skipped}")
    print(f"   ❌ 未通过: {failed}")

def cmd_status(args):
    """显示数据库统计"""
    db_path = DEFAULT_DB
    i = 0
    while i < len(args):
        if args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        else:
            i += 1

    db_path = os.path.abspath(db_path)
    entries = load_db(db_path)

    team = [e for e in entries if e["id"].startswith("T")]
    classic = [e for e in entries if e["id"].startswith("C")]
    new = [e for e in entries if e["id"].startswith("NEW")]

    with_doi = [e for e in entries if e.get("doi") and e["doi"] != "—"]

    print(f"\n📚 参考文献库状态")
    print(f"   路径: {db_path}")
    print(f"\n   总条目: {len(entries)}")
    print(f"   ├─ 团队论文 (T): {len(team)}")
    print(f"   ├─ 经典文献 (C): {len(classic)}")
    print(f"   └─ 新入库 (NEW): {len(new)}")
    print(f"\n   有 DOI: {len(with_doi)}/{len(entries)} ({len(with_doi)/max(len(entries),1)*100:.0f}%)")

    if entries:
        years = [int(e["year"]) for e in entries if e.get("year") and e["year"].isdigit()]
        if years:
            print(f"   年份范围: {min(years)}-{max(years)}")

# ---- 工具函数 ----

def _merge_results(results):
    """合并多源结果，去重"""
    merged = {}
    for r in results:
        doi = _normalize_doi(r.get("doi", ""))
        title_key = _normalize_text(r.get("title", ""))[:50]
        key = doi if doi else title_key
        if not key:
            continue
        if key in merged:
            merged[key]["_sources"].add(r.get("_from", "?"))
            if not merged[key].get("doi") and r.get("doi"):
                merged[key]["doi"] = r["doi"]
            if r.get("citations", 0) > merged[key].get("citations", 0):
                merged[key]["citations"] = r["citations"]
        else:
            r["_sources"] = {r.pop("_from", "?")}
            merged[key] = r
    return list(merged.values())

# ---- CLI 入口 ----

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("""ref_search.py — 中英文学术文献检索与验证

用法:
  ref_search.py search "关键词"          搜索文献（三源交叉）
  ref_search.py author "作者名"          按作者检索论文
  ref_search.py verify --doi "10.xxx"   验证单条文献
  ref_search.py import --doi "10.xxx"   验证并导入数据库
  ref_search.py enrich "作者名"          批量验证作者论文并入库
  ref_search.py status                  显示数据库统计

选项:
  --limit N     结果数量（默认10）
  --db PATH     数据库路径（默认 knowledge-base/refs/verified-refs.md）
  --lang LANG   搜索语言: en/cn/both（默认 both）
  --id ID       导入时指定 ID（如 T02）
  --year YEAR   验证时指定年份
  --title TEXT  验证时指定标题
  --author NAME 验证时指定作者
  --force       强制导入 PROBABLE 级别文献
""")
        sys.exit(0)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "search":
        cmd_search(rest)
    elif cmd == "author":
        cmd_author(rest)
    elif cmd == "verify":
        cmd_verify(rest)
    elif cmd == "import":
        cmd_import(rest)
    elif cmd == "enrich":
        cmd_enrich(rest)
    elif cmd == "status":
        cmd_status(rest)
    else:
        print(f"未知命令: {cmd}")
        print("可用命令: search, author, verify, import, enrich, status")
        sys.exit(1)
