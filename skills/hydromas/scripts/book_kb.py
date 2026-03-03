#!/usr/bin/env python3
"""GitHub 书稿 -> 飞书文档 + 本地知识库索引/查询。

用法:
  # 从 GitHub 目录同步到知识库 + 飞书（默认）
  python3 book_kb.py sync \
    --github-url "https://github.com/leixiaohui-1974/books/tree/main/books/T2_revision" \
    --user-openid "ou_xxx"

  # 仅构建知识库，不发布飞书
  python3 book_kb.py sync --github-url "..." --no-feishu

  # 查询知识库
  python3 book_kb.py query "四预闭环"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import tempfile
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests

GITHUB_API = "https://api.github.com"
FEISHU_BASE = "https://open.feishu.cn/open-apis"

BASE_DIR = pathlib.Path(__file__).resolve().parent
KB_DIR = pathlib.Path("/home/admin/hydromas/data/book_kb")
KB_INDEX_FILE = KB_DIR / "chunks.jsonl"
KB_META_FILE = KB_DIR / "meta.json"
API_DOC_OUT = BASE_DIR.parent / "docs" / "HYDROMAS_API_DOCS.md"
FEISHU_DOC_PUBLISHER = pathlib.Path("/home/admin/.openclaw/workspace/skills/feishu-doc-publisher/scripts/feishu_doc_publisher.py")
BOOK_TITLES = {
    "T2a": "《水系统控制论：建模与控制》",
    "T2b": "《水系统控制论：智能与自主》",
}


def _read_simple_env_file(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return out
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if not k:
                continue
            out[k] = v.strip().strip('"').strip("'")
    except Exception:
        return out
    return out


def load_feishu_config() -> dict[str, str]:
    vals = {
        "FEISHU_APP_ID": os.environ.get("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": os.environ.get("FEISHU_APP_SECRET", ""),
        "FEISHU_DOC_DOMAIN": os.environ.get("FEISHU_DOC_DOMAIN", "docs.feishu.cn"),
    }
    for p in [BASE_DIR / ".env", BASE_DIR.parent / ".env", pathlib.Path.cwd() / ".env"]:
        env_vals = _read_simple_env_file(p)
        for k in vals:
            if not vals[k] and env_vals.get(k):
                vals[k] = env_vals[k]

    openclaw_json = pathlib.Path.home() / ".openclaw" / "openclaw.json"
    if openclaw_json.exists() and (not vals["FEISHU_APP_ID"] or not vals["FEISHU_APP_SECRET"]):
        try:
            data = json.loads(openclaw_json.read_text(encoding="utf-8"))
            accts = (
                data.get("channels", {})
                .get("feishu", {})
                .get("accounts", {})
            )
            candidates: list[dict[str, Any]] = []
            if isinstance(accts.get("default"), dict):
                candidates.append(accts["default"])
            for k, v in accts.items():
                if k != "default" and isinstance(v, dict):
                    candidates.append(v)
            for acc in candidates:
                if not vals["FEISHU_APP_ID"] and acc.get("appId"):
                    vals["FEISHU_APP_ID"] = str(acc.get("appId"))
                if not vals["FEISHU_APP_SECRET"] and acc.get("appSecret"):
                    vals["FEISHU_APP_SECRET"] = str(acc.get("appSecret"))
                if vals["FEISHU_APP_ID"] and vals["FEISHU_APP_SECRET"]:
                    break
        except Exception:
            pass

    if vals["FEISHU_DOC_DOMAIN"].strip().lower() == "open.feishu.cn":
        vals["FEISHU_DOC_DOMAIN"] = "docs.feishu.cn"
    return vals


def parse_github_tree_url(url: str) -> tuple[str, str, str, str]:
    # https://github.com/{owner}/{repo}/tree/{branch}/{path...}
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.*)", url.strip())
    if not m:
        raise ValueError("github_url 必须是 github tree 链接，例如 https://github.com/org/repo/tree/main/books/T2_revision")
    owner, repo, branch, base_path = m.group(1), m.group(2), m.group(3), m.group(4)
    return owner, repo, branch, base_path.strip("/")


def github_session() -> requests.Session:
    s = requests.Session()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    s.headers.update({"Accept": "application/vnd.github+json"})
    return s


def list_markdown_files(owner: str, repo: str, branch: str, base_path: str) -> list[str]:
    # git trees recursive API
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    r = github_session().get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    tree = data.get("tree", [])

    md_paths: list[str] = []
    prefix = base_path.rstrip("/") + "/"
    for item in tree:
        if item.get("type") != "blob":
            continue
        p = item.get("path", "")
        if not isinstance(p, str):
            continue
        p_low = p.lower()
        if not p_low.endswith(".md") and not p_low.endswith(".markdown"):
            continue
        if not (p == base_path or p.startswith(prefix)):
            continue
        md_paths.append(p)
    return sorted(md_paths)


def fetch_raw_markdown(owner: str, repo: str, branch: str, path: str) -> str:
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    r = github_session().get(raw, timeout=60)
    r.raise_for_status()
    return r.text


def group_by_book(base_path: str, files: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    base_prefix = base_path.rstrip("/") + "/"
    for p in files:
        rel = p[len(base_prefix):] if p.startswith(base_prefix) else p
        first = rel.split("/", 1)[0] if rel else "default"
        # 只按一级目录划分“书”，根目录 md 归入 _root
        book = first if "/" in rel else "_root"
        grouped.setdefault(book, []).append(p)
    for k in grouped:
        grouped[k].sort()
    return grouped


def _chapter_rank(path: str) -> tuple[int, int, str] | None:
    name = pathlib.Path(path).name.lower()
    m = re.match(r"^ch(\d{2})_(.+)\.md$", name)
    if not m:
        return None
    ch = int(m.group(1))
    tag = m.group(2)
    if tag == "final":
        score = 10000
    else:
        vm = re.search(r"(?:^|_)v(\d+)(?:_|$)", tag)
        if vm:
            score = 1000 + int(vm.group(1))
        elif "backup" in tag or "old" in tag:
            score = 10
        else:
            score = 100
    return (ch, score, name)


def select_latest_chapter_files(paths: list[str], include_extra: bool = False) -> list[str]:
    by_ch: dict[int, tuple[int, str]] = {}
    extras: list[str] = []
    for p in paths:
        rk = _chapter_rank(p)
        if rk is None:
            if include_extra:
                extras.append(p)
            continue
        ch, score, _ = rk
        cur = by_ch.get(ch)
        if cur is None or score > cur[0] or (score == cur[0] and p > cur[1]):
            by_ch[ch] = (score, p)
    selected = [by_ch[k][1] for k in sorted(by_ch.keys())]
    if include_extra:
        selected.extend(sorted(extras))
    return selected


def _strip_md_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def _chapter_label_from_path(path: str) -> str:
    m = re.match(r"^ch(\d{2})_", pathlib.Path(path).name.lower())
    return f"第{int(m.group(1)):02d}章" if m else pathlib.Path(path).stem


def _extract_h1_title(text: str, fallback: str) -> str:
    t = _strip_md_comments(text)
    for ln in t.splitlines():
        s = ln.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def _summarize_markdown(text: str, limit: int = 180) -> str:
    t = _strip_md_comments(text)
    t = re.sub(r"(^|\n)\s{0,3}#{1,6}\s*", "\n", t)
    t = re.sub(r"(^|\n)\s*[-*+]\s+", "\n", t)
    t = re.sub(r"(^|\n)\s*\d+\.\s+", "\n", t)
    t = re.sub(r"\s+", " ", t).strip()
    parts = [p.strip() for p in re.split(r"(?<=[。！？.!?])\s+", t) if p.strip()]
    out: list[str] = []
    size = 0
    for s in parts:
        if len(s) < 12:
            continue
        if size + len(s) > limit:
            break
        out.append(s)
        size += len(s)
        if len(out) >= 2:
            break
    return " ".join(out) if out else t[:limit]


def _chapter_body_without_h1(text: str) -> str:
    t = _strip_md_comments(text)
    lines = t.splitlines()
    out: list[str] = []
    skipped_h1 = False
    for ln in lines:
        s = ln.strip()
        if not skipped_h1 and s.startswith("# "):
            skipped_h1 = True
            continue
        out.append(ln)
    return "\n".join(out).strip()


def parse_chapter_info(path: str, content: str) -> dict[str, str]:
    return {
        "path": path,
        "label": _chapter_label_from_path(path),
        "title": _extract_h1_title(content, pathlib.Path(path).name),
        "summary": _summarize_markdown(content, limit=180),
        "raw_content": content,
        "body": _chapter_body_without_h1(content),
    }


def compose_book_markdown(book: str, file_contents: list[tuple[str, str]]) -> str:
    book_title = BOOK_TITLES.get(book, book)
    chapters = [parse_chapter_info(path, content) for path, content in file_contents]

    lines = [
        f"# {book_title}",
        "",
        "> 版本：仅最新章节",
        f"> 章节数：{len(chapters)}",
        "",
        "## 目录",
        "",
    ]
    for ch in chapters:
        lines.append(f"- {ch['label']} · {ch['title']}")

    lines += ["", "---", ""]
    for ch in chapters:
        lines.append(f"## {ch['label']} · {ch['title']}")
        lines.append("")
        lines.append(f"**章节导读**：{ch['summary']}")
        lines.append("")
        lines.append(ch["body"])
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def compose_book_markdown_index(
    book: str,
    owner: str,
    repo: str,
    branch: str,
    file_contents: list[tuple[str, str]],
    preview_chars: int = 320,
) -> str:
    """Fast publish mode: file index + short preview + raw links."""
    book_title = BOOK_TITLES.get(book, book)

    def _clean_preview(text: str) -> str:
        # Drop HTML comments (e.g. changelog blocks) and collapse whitespace.
        t = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        lines = [ln for ln in t.splitlines() if ln.strip() and not ln.strip().startswith("<!--")]
        t = "\n".join(lines)
        return re.sub(r"\s+", " ", t).strip()

    def _summarize_preview(text: str, limit: int) -> str:
        t = _clean_preview(text)
        # Remove markdown headings and list markers for summary extraction.
        t = re.sub(r"(^|\\n)\\s{0,3}#{1,6}\\s*", "\\n", t)
        t = re.sub(r"(^|\\n)\\s*[-*+]\\s+", "\\n", t)
        t = re.sub(r"(^|\\n)\\s*\\d+\\.\\s+", "\\n", t)
        t = re.sub(r"\\s+", " ", t).strip()
        if not t:
            return ""

        # Pick first 1-2 meaningful sentences instead of raw truncation.
        parts = [p.strip() for p in re.split(r"(?<=[。！？.!?])\\s+", t) if p.strip()]
        picked = []
        size = 0
        for s in parts:
            if len(s) < 12:
                continue
            if size + len(s) > limit:
                break
            picked.append(s)
            size += len(s)
            if len(picked) >= 2:
                break
        if picked:
            return " ".join(picked)
        return t[:limit]

    def _extract_heading(text: str) -> str:
        t = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        for ln in t.splitlines():
            s = ln.strip()
            if s.startswith("# "):
                return s[2:].strip()
        return ""

    def _chapter_label(path: str) -> str:
        name = pathlib.Path(path).name.lower()
        m = re.match(r"^ch(\d{2})_", name)
        if m:
            return f"第{int(m.group(1)):02d}章"
        return pathlib.Path(path).stem

    lines = [
        f"# {book_title}",
        "",
        "> 发布模式: index（飞书内链版）",
        f"> 文件数: {len(file_contents)}",
        "",
        "## 目录",
        "",
    ]
    for path, content in file_contents:
        heading = _extract_heading(content) or pathlib.Path(path).name
        lines.append(f"- {_chapter_label(path)} · {heading}")
        lines.append("  - 阅读方式：本页查看章节摘要，详细内容以飞书文档正文为准")

    lines += ["", "---", ""]
    for path, content in file_contents:
        preview = _summarize_preview(content, preview_chars)
        lines.append(f"## {_chapter_label(path)} · {(_extract_heading(content) or pathlib.Path(path).name)}")
        lines.append("")
        if preview:
            lines.append(f"- 摘要: {preview}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def compose_book_markdown_split_index(
    book: str,
    owner: str,
    repo: str,
    branch: str,
    chapters: list[dict[str, str]],
    chapter_urls: dict[str, str],
) -> str:
    book_title = BOOK_TITLES.get(book, book)

    lines = [
        f"# {book_title}",
        "",
        "## 阅读导航",
        "",
        "- 发布结构：总目录 + 章节文档",
        "- 当前版本：仅保留每章最新稿（`*_final.md` 优先）",
        f"- 章节总数：{len(chapters)}",
        "",
        "## 章节清单",
        "",
    ]

    for idx, ch in enumerate(chapters, start=1):
        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{ch['path']}"
        feishu_url = chapter_urls.get(ch["path"], "")
        lines.append(f"### {idx:02d}. {ch['label']} · {ch['title']}")
        lines.append("")
        lines.append(f"- 摘要：{ch['summary']}")
        lines.append(f"- 飞书正文：{feishu_url if feishu_url else '发布失败'}")
        lines.append(f"- GitHub原文：{raw}")
        lines.append("")

    lines.extend(
        [
            "## 使用说明",
            "",
            "- 点击每章“飞书正文”链接进入章节完整内容。",
            "- 本页作为总入口，正文更新按章节独立进行。",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def split_chunks(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + chunk_size)
        chunk = text[start:end]
        if end < n:
            cut = max(chunk.rfind("\n\n"), chunk.rfind("。"), chunk.rfind("\n"))
            if cut > int(chunk_size * 0.4):
                end = start + cut + 1
                chunk = text[start:end]
        chunks.append(chunk.strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def rebuild_kb_index(source_url: str, books: dict[str, str]) -> tuple[int, int]:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    chunk_count = 0
    book_count = 0
    with KB_INDEX_FILE.open("w", encoding="utf-8") as f:
        for book, text in books.items():
            book_count += 1
            chunks = split_chunks(text)
            for i, ch in enumerate(chunks, start=1):
                row = {
                    "book": book,
                    "chunk_id": i,
                    "text": ch,
                    "source": source_url,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                chunk_count += 1
    meta = {
        "updated_at": int(time.time()),
        "source": source_url,
        "books": sorted(books.keys()),
        "book_count": book_count,
        "chunk_count": chunk_count,
    }
    KB_META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return book_count, chunk_count


def _tokenize_for_search(text: str) -> list[str]:
    # 英文词 + 中文双字切片
    low = text.lower()
    en = re.findall(r"[a-z0-9_]+", low)
    zh = "".join(re.findall(r"[\u4e00-\u9fff]", low))
    zh_bi = [zh[i:i+2] for i in range(max(0, len(zh) - 1))]
    return en + zh_bi


def search_kb(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not KB_INDEX_FILE.exists():
        raise RuntimeError(f"知识库索引不存在: {KB_INDEX_FILE}")
    q_tokens = _tokenize_for_search(query)
    if not q_tokens:
        return []

    hits: list[tuple[float, dict[str, Any]]] = []
    with KB_INDEX_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = str(row.get("text", ""))
            low = text.lower()
            score = 0.0
            for t in q_tokens:
                c = low.count(t)
                if c:
                    score += min(c, 8)
            if score > 0:
                # 轻微偏好较短块，避免大段噪声
                score = score / (1.0 + len(text) / 2500.0)
                hits.append((score, row))

    hits.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "score": round(s, 3),
            "book": r.get("book"),
            "chunk_id": r.get("chunk_id"),
            "text": r.get("text", "")[:900],
            "source": r.get("source"),
        }
        for s, r in hits[:top_k]
    ]


@dataclass
class FeishuPublisher:
    app_id: str
    app_secret: str
    doc_domain: str = "docs.feishu.cn"

    def __post_init__(self):
        if not self.app_id or not self.app_secret:
            raise ValueError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
        self.sess = requests.Session()
        self.token = self._tenant_token()
        self.sess.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
        )

    def _tenant_token(self) -> str:
        r = requests.post(
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=30,
        )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {d}")
        return d["tenant_access_token"]

    def create_doc(self, title: str) -> tuple[str, str]:
        r = self.sess.post(f"{FEISHU_BASE}/docx/v1/documents", json={"title": title}, timeout=30)
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Create doc failed: {d}")
        doc_id = d["data"]["document"]["document_id"]
        url = f"https://{self.doc_domain}/docx/{doc_id}"
        return doc_id, url

    def _append_blocks(self, doc_id: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        r = self.sess.post(
            f"{FEISHU_BASE}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            json={"children": blocks},
            timeout=30,
        )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Write blocks failed: {d}")

    def write_markdown_like(self, doc_id: str, markdown_text: str) -> int:
        blocks: list[dict[str, Any]] = []
        para: list[str] = []
        written = 0

        def _flush_para() -> None:
            nonlocal para
            text = " ".join(x.strip() for x in para if x.strip()).strip()
            if text:
                blocks.append({"block_type": 2, "text": {"elements": [{"text_run": {"content": text}}]}})
            para = []

        for raw in markdown_text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                _flush_para()
                continue
            if line.startswith("#### "):
                _flush_para()
                blocks.append({"block_type": 6, "heading4": {"elements": [{"text_run": {"content": line[5:].strip()}}]}})
            elif line.startswith("### "):
                _flush_para()
                blocks.append({"block_type": 5, "heading3": {"elements": [{"text_run": {"content": line[4:].strip()}}]}})
            elif line.startswith("## "):
                _flush_para()
                blocks.append({"block_type": 4, "heading2": {"elements": [{"text_run": {"content": line[3:].strip()}}]}})
            elif line.startswith("# "):
                _flush_para()
                blocks.append({"block_type": 3, "heading1": {"elements": [{"text_run": {"content": line[2:].strip()}}]}})
            elif line.startswith("- "):
                _flush_para()
                blocks.append({"block_type": 12, "bullet": {"elements": [{"text_run": {"content": line[2:].strip()}}]}})
            else:
                para.append(line)

            if len(blocks) >= 45:
                self._append_blocks(doc_id, blocks)
                written += len(blocks)
                blocks = []
                time.sleep(0.05)

        _flush_para()
        if blocks:
            self._append_blocks(doc_id, blocks)
            written += len(blocks)
        return written

    def grant(self, doc_id: str, openid: str) -> None:
        if not openid:
            return
        r = self.sess.post(
            f"{FEISHU_BASE}/drive/v1/permissions/{doc_id}/members?type=docx",
            json={"member_type": "openid", "member_id": openid, "perm": "full_access"},
            timeout=30,
        )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Grant failed: {d}")


def run_sync(args: argparse.Namespace) -> int:
    owner, repo, branch, base_path = parse_github_tree_url(args.github_url)
    files = list_markdown_files(owner, repo, branch, base_path)
    if not files:
        print("未发现 Markdown 文件。")
        return 2

    groups = group_by_book(base_path, files)
    books_full: dict[str, str] = {}
    books_publish: dict[str, str] = {}
    books_chapters: dict[str, list[dict[str, str]]] = {}
    published: dict[str, str] = {}
    mode = str(getattr(args, "publish_mode", "index")).strip().lower()

    for book, paths in groups.items():
        if not args.all_versions:
            paths = select_latest_chapter_files(paths, include_extra=args.include_extra)
        contents_map: dict[str, str] = {}
        workers = max(1, int(getattr(args, "fetch_workers", 8)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fut_map = {
                pool.submit(fetch_raw_markdown, owner, repo, branch, p): p
                for p in paths
            }
            for fut in as_completed(fut_map):
                p = fut_map[fut]
                contents_map[p] = fut.result()
        contents = [(p, contents_map[p]) for p in paths if p in contents_map]
        chapter_infos = [parse_chapter_info(p, c) for p, c in contents]
        books_chapters[book] = chapter_infos
        full_text = compose_book_markdown(book, contents)
        books_full[book] = full_text

        if mode == "index":
            books_publish[book] = compose_book_markdown_index(
                book, owner, repo, branch, contents, preview_chars=int(getattr(args, "preview_chars", 320))
            )
        elif mode == "full":
            books_publish[book] = full_text

    b_count, c_count = rebuild_kb_index(args.github_url, books_full)

    if not args.no_feishu:
        conf = load_feishu_config()
        pub = FeishuPublisher(
            app_id=conf["FEISHU_APP_ID"],
            app_secret=conf["FEISHU_APP_SECRET"],
            doc_domain=conf["FEISHU_DOC_DOMAIN"] or "docs.feishu.cn",
        )
        def _write_doc(book_key: str, doc_id: str, text: str, publish_mode: str, timeout_s: int) -> int:
            if publish_mode == "split":
                return pub.write_markdown_like(doc_id, text)
            if FEISHU_DOC_PUBLISHER.exists():
                with tempfile.TemporaryDirectory(prefix="bookkb-") as td:
                    md_file = pathlib.Path(td) / f"{book_key}.md"
                    cfg_file = pathlib.Path(td) / "cfg.json"
                    md_file.write_text(text, encoding="utf-8")
                    cfg = {
                        "feishu": {
                            "app_id": conf["FEISHU_APP_ID"],
                            "app_secret": conf["FEISHU_APP_SECRET"],
                        },
                        "doc_token": doc_id,
                        "article_path": str(md_file),
                        "strip_trailing_info": False,
                    }
                    if args.user_openid:
                        cfg["user_openid"] = args.user_openid
                    cfg_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                    try:
                        proc = subprocess.run([sys.executable, str(FEISHU_DOC_PUBLISHER), str(cfg_file)], timeout=timeout_s)
                    except subprocess.TimeoutExpired:
                        proc = None
                    if proc is None or proc.returncode != 0:
                        return pub.write_markdown_like(doc_id, text)
                    return -1
            return pub.write_markdown_like(doc_id, text)

        if mode == "split":
            for book, chapters in books_chapters.items():
                book_title = BOOK_TITLES.get(book, book)
                chapter_urls: dict[str, str] = {}
                for i, ch in enumerate(chapters, start=1):
                    chapter_doc_title = f"{book_title}·{ch['label']} {ch['title']}"
                    doc_id, url = pub.create_doc(chapter_doc_title)
                    chapter_md = (
                        f"# {ch['label']} · {ch['title']}\n\n"
                        "## 章节导读\n\n"
                        f"- 核心摘要：{ch['summary']}\n"
                        f"- 原文地址：https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{ch['path']}\n\n"
                        "## 正文\n\n"
                        f"{ch['body']}\n"
                    )
                    block_count = _write_doc(f"{book}-chapter-{i:02d}", doc_id, chapter_md, "split", timeout_s=300)
                    if args.user_openid:
                        pub.grant(doc_id, args.user_openid)
                    chapter_urls[ch["path"]] = url
                    if block_count >= 0:
                        print(f"[feishu] {book} {ch['label']}: {url} (blocks={block_count})")
                    else:
                        print(f"[feishu] {book} {ch['label']}: {url} (typeset=feishu-doc-publisher)")

                index_md = compose_book_markdown_split_index(book, owner, repo, branch, chapters, chapter_urls)
                index_doc_id, index_url = pub.create_doc(f"{book_title}（总目录）")
                index_blocks = _write_doc(f"{book}-index", index_doc_id, index_md, "split", timeout_s=150)
                if args.user_openid:
                    pub.grant(index_doc_id, args.user_openid)
                published[book] = index_url
                if index_blocks >= 0:
                    print(f"[feishu] {book} index: {index_url} (blocks={index_blocks})")
                else:
                    print(f"[feishu] {book} index: {index_url} (typeset=feishu-doc-publisher)")
        else:
            for book, text in books_publish.items():
                book_title = BOOK_TITLES.get(book, book)
                if mode == "index":
                    title = f"{book_title}（最新章节索引）"
                    timeout_s = 150
                else:
                    title = f"{book_title}（最新章节）"
                    timeout_s = 900
                doc_id, url = pub.create_doc(title)
                block_count = _write_doc(book, doc_id, text, mode, timeout_s=timeout_s)
                if args.user_openid:
                    pub.grant(doc_id, args.user_openid)
                published[book] = url
                if block_count >= 0:
                    print(f"[feishu] {book}: {url} (blocks={block_count})")
                else:
                    print(f"[feishu] {book}: {url} (typeset=feishu-doc-publisher)")

    print(f"[kb] source={args.github_url}")
    print(f"[kb] books={b_count} chunks={c_count} index={KB_INDEX_FILE}")
    if published:
        print("[kb] published_docs=")
        for book, url in published.items():
            print(f"  - {book}: {url}")

    return 0


def run_query(args: argparse.Namespace) -> int:
    hits = search_kb(args.query, top_k=args.top_k)
    if not hits:
        print("未命中相关内容。")
        return 1

    print(f"query: {args.query}")
    for i, h in enumerate(hits, start=1):
        print(f"\n[{i}] score={h['score']} book={h['book']} chunk={h['chunk_id']}")
        print(h["text"])
    return 0


def _load_hydromas_api_specs() -> dict[str, Any]:
    hydromas_call = BASE_DIR / "hydromas_call.py"
    if not hydromas_call.exists():
        raise RuntimeError(f"hydromas_call.py 不存在: {hydromas_call}")

    spec = importlib.util.spec_from_file_location("hydromas_call_module", str(hydromas_call))
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 hydromas_call.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hydromas_call_module"] = mod
    spec.loader.exec_module(mod)

    api_specs = getattr(mod, "_API_SKILLS", None)
    if not isinstance(api_specs, dict):
        raise RuntimeError("hydromas_call.py 中未找到 _API_SKILLS")
    return api_specs


def _build_api_docs_markdown(api_specs: dict[str, Any]) -> str:
    def _sample_override(defaults: Any) -> dict[str, Any]:
        if not isinstance(defaults, dict) or not defaults:
            return {}
        out = {}
        for i, (k, v) in enumerate(defaults.items()):
            if i >= 2:
                break
            if isinstance(v, (int, float)):
                out[k] = v + 1 if isinstance(v, int) else round(v * 1.1, 4)
            elif isinstance(v, str):
                out[k] = v + "_override"
            elif isinstance(v, bool):
                out[k] = not v
            elif isinstance(v, list) and v:
                out[k] = v[:1]
            elif isinstance(v, dict) and v:
                first_k = next(iter(v))
                out[k] = {first_k: v[first_k]}
            else:
                out[k] = v
        return out

    lines: list[str] = [
        "# HydroMAS API 文档知识库",
        "",
        "> 来源: hydromas_call.py::_API_SKILLS 自动抽取",
        "",
        "## 总览",
        "",
        "| API | 方法 | 路径 | 说明 |",
        "|-----|------|------|------|",
    ]
    for name, info in sorted(api_specs.items()):
        method = info.get("method", "POST")
        path = info.get("path", "")
        desc = str(info.get("description", "")).replace("|", "\\|")
        lines.append(f"| `{name}` | `{method}` | `{path}` | {desc} |")

    lines += ["", "---", ""]

    for name, info in sorted(api_specs.items()):
        method = info.get("method", "POST")
        path = info.get("path", "")
        desc = info.get("description", "")
        defaults = info.get("defaults", {})
        sample_override = _sample_override(defaults)
        lines += [
            f"## {name}",
            "",
            f"- 说明: {desc}",
            f"- 端点: `{method} {path}`",
            "",
            "### 默认参数",
            "",
            "```json",
            json.dumps(defaults, ensure_ascii=False, indent=2),
            "```",
            "",
            "### 命令行调用示例",
            "",
            "```bash",
            f"python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api {name}",
            "```",
            "",
            "```bash",
            f"python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api {name} '{json.dumps(sample_override, ensure_ascii=False)}'",
            "```",
            "",
            "---",
            "",
        ]
    return "\n".join(lines).strip() + "\n"


def run_sync_api_docs(args: argparse.Namespace) -> int:
    api_specs = _load_hydromas_api_specs()
    markdown = _build_api_docs_markdown(api_specs)
    API_DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    API_DOC_OUT.write_text(markdown, encoding="utf-8")
    source = "hydromas_call.py::_API_SKILLS"
    books = {"HydroMAS_API": markdown}
    b_count, c_count = rebuild_kb_index(source, books)

    if not args.no_feishu:
        conf = load_feishu_config()
        pub = FeishuPublisher(
            app_id=conf["FEISHU_APP_ID"],
            app_secret=conf["FEISHU_APP_SECRET"],
            doc_domain=conf["FEISHU_DOC_DOMAIN"] or "docs.feishu.cn",
        )
        doc_id, url = pub.create_doc("HydroMAS API 文档知识库")
        pub.write_markdown_like(doc_id, markdown)
        if args.user_openid:
            pub.grant(doc_id, args.user_openid)
        print(f"[feishu] HydroMAS_API: {url}")

    print(f"[kb] source={source}")
    print(f"[kb] books={b_count} chunks={c_count} index={KB_INDEX_FILE}")
    print(f"[kb] api_count={len(api_specs)}")
    print(f"[kb] api_doc={API_DOC_OUT}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GitHub 书稿 -> 飞书文档 + HydroMAS 知识库")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sync", help="同步 GitHub 目录到知识库（并可发布飞书）")
    ps.add_argument("--github-url", required=True, help="GitHub tree URL")
    ps.add_argument("--user-openid", default="", help="发布后授予 full_access 的用户 openid")
    ps.add_argument("--no-feishu", action="store_true", help="只建知识库，不发飞书")
    ps.add_argument("--fetch-workers", type=int, default=8, help="并发下载 Markdown 文件的线程数")
    ps.add_argument(
        "--publish-mode",
        choices=["full", "index", "split"],
        default="index",
        help="飞书发布模式：full=整书正文，index=目录+摘要，split=总目录+章节文档（推荐）",
    )
    ps.add_argument("--preview-chars", type=int, default=320, help="index 模式每文件预览字符数")
    ps.add_argument("--all-versions", action="store_true", help="保留所有版本文件（默认仅保留每章最新版本）")
    ps.add_argument("--include-extra", action="store_true", help="在 latest-only 模式下保留非章节 markdown")

    pa = sub.add_parser("sync-api-docs", help="同步 HydroMAS API 文档到知识库（并可发布飞书）")
    pa.add_argument("--user-openid", default="", help="发布后授予 full_access 的用户 openid")
    pa.add_argument("--no-feishu", action="store_true", help="只建知识库，不发飞书")

    pq = sub.add_parser("query", help="查询本地知识库")
    pq.add_argument("query", help="查询词")
    pq.add_argument("--top-k", type=int, default=5)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "sync":
        return run_sync(args)
    if args.cmd == "query":
        return run_query(args)
    if args.cmd == "sync-api-docs":
        return run_sync_api_docs(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
