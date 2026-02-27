# 雷晓辉学术写作风格蓝图 (Style Blueprint)

> 基于雷晓辉已发表论文（200+篇）提炼的写作风格指令。
> 所有Agent写作时必须遵守。

## 中文写作风格

写作时采用以下风格：语言精炼、逻辑严密，偏好工程化表述而非文学化修辞。
句式以短句为主（15-25字），避免长定语从句嵌套。论述结构为"问题→机理→模型→验证→结论"，
每段以论点句开头。术语使用严格统一（见chs-terms.md），首次出现给中英文全称。
数学推导采用"物理直觉→数学表达→工程意义"三步法，公式前后必须有文字衔接。
引用文献时突出贡献而非罗列，用"X提出了…""Y发展了…"而非"文献[1]研究了…"。
图表说明要具体（"图3表明流量响应延迟约15min"而非"如图3所示"）。
段落长度控制在150-300字，避免超长段落。

## English Writing Style

Write in a precise, engineering-oriented academic style with clear logical flow.
Use active voice for methodology ("We propose..." "This paper develops...") and passive for established facts.
Sentences should be concise (15-25 words average), avoiding nested relative clauses.
Structure arguments as: motivation → gap → contribution → validation → significance.
Lead each paragraph with a topic sentence. Use transition words sparingly but effectively
("However," "Furthermore," "In contrast,"). Prefer specific quantitative claims over vague descriptions
("reduces computation time by 87%" not "significantly reduces computation time").
Define all acronyms at first use. Mathematical notation must be consistent with symbol-table.md.

## 禁止风格

- ❌ 不用"众所周知""不言而喻"等空洞套话
- ❌ 不用"随着...的发展"作为开头（几乎每篇AI文章都这么开头）
- ❌ 不用"本文的创新点在于"（让读者自己判断）
- ❌ 不用过度修饰词："非常""极其""显著"（除非有统计检验支持）
- ❌ 不在文末添加作者简介/署名行
- ❌ 英文不用 "In recent years" 开头
- ❌ 英文不用 "plays an important role" 等万能句
