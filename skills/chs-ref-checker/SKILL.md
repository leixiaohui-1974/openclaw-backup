---
name: chs-ref-checker
description: "CHS参考文献检查与修复工具。当用户说'检查文献'、'验证引用'、'自引率'、'reference check'时触发。对指定文件执行全面的参考文献验证、格式检查和自引率分析。可调用 ref-search 脚本和 citation_verify.py 工具。"
version: 1.0.0
tags: [chs, reference, verification, citation]
---

# CHS参考文献检查与修复

对指定文件执行全面的参考文献检查。

## 输入

用户提供待检查文件路径。

## 检查流程

### 1. 提取参考文献
- 读取文件，提取所有参考文献条目
- 读取 `knowledge-base/refs/verified-refs.md` 获取已验证文献库

### 2. 逐条验证
对每条参考文献执行（优先使用已有工具）：
- 在 `knowledge-base/refs/verified-refs.md` 中查找已验证记录
- 未收录的调用 `tools/citation_verify.py` 或 `skills/ref-search/scripts/ref_search.py` 验证
- 验证作者、年份、标题、期刊/出版社、ISBN/DOI/页码
- 标记可疑条目（搜不到的、信息不匹配的）

### 3. 自引率计算
- 统计 Lei/雷晓辉 相关引用数量
- 计算自引率 = Lei引用数 / 总引用数
- 目标: T1=10-15%, T2=7-10%, M系列=5-8%
- 如超标，建议删除哪些自引；如不足，建议补充哪些

### 4. 格式检查
- 中文文献: GB/T 7714-2015 格式，含文献类型标识 [J][M][D][S][R]
- 英文文献: 与目标出版社格式一致
- 所有文献需包含: 作者、年份、标题、期刊/出版社、卷号/页码或DOI

### 5. 输出报告
```
[文献检查报告] 文件: xxx
- 总引用数: N
- 自引率: X% (目标: Y%)
- 验证通过: N1条
- 验证失败: N2条 (列出)
- 格式问题: N3条 (列出)
- 缺失必引: (列出)
- 修复建议: (按优先级)
```

### 6. 可选：自动修复
如用户同意，直接修正格式问题、替换不可验证的文献、调整自引率。
新验证通过的文献自动追加到 `knowledge-base/refs/verified-refs.md`。
