---
name: chs-file-converter
description: "文件格式转换助手。当用户说'转格式'、'转docx'、'转PDF'、'合并章节'、'pandoc'时触发。支持Markdown↔Word↔PDF转换，以及多章节合并输出。"
version: 1.0.0
tags: [chs, conversion, pandoc, docx, pdf]
---

# 文件格式转换

支持以下转换操作。

## 常用转换

### Markdown → Word (.docx)
```bash
pandoc input.md -o output.docx --reference-doc=template.docx
```
- 如有数学公式，加 `--mathjax` 或 `--webtex`
- 如需目录，加 `--toc --toc-depth=3`

### Markdown → PDF
```bash
pandoc input.md -o output.pdf --pdf-engine=xelatex -V mainfont="SimSun" -V CJKmainfont="SimSun"
```
- 中文文档必须指定 CJK 字体

### 多章节合并
```bash
pandoc ch01.md ch02.md ch03.md -o book.docx --toc
```

### Word → Markdown
```bash
pandoc input.docx -o output.md --extract-media=./media
```

## 批量转换

如需批量转换整本书，提供书目编号（如 T2a），自动：
1. 找到所有章节文件
2. 按顺序合并
3. 生成完整的 .docx 文件（含目录、统一格式）

## 输入

告诉我：
1. 源文件路径
2. 目标格式
3. 特殊要求（如模板、字体、目录等）
