---
name: chs-figure-generator
description: "CHS教材图片生成助手。当用户说'生成图片'、'画图'、'figure'、'配图'、提到图表编号如'图X-Y'时触发。生成科学图表的AI提示词或matplotlib/mermaid代码。"
version: 1.0.0
tags: [chs, figure, image, matplotlib, diagram]
---

# CHS图片生成助手

帮助生成科学图表、架构图和示意图。

## 统一配色方案（全体系共享）

- 主色: #1565C0（深蓝，水/控制）
- 辅色1: #4CAF50（绿，安全/ODD）
- 辅色2: #7B1FA2（紫，认知智能）
- 辅色3: #FF7043（橙红，扰动/警告）
- 背景: 白色，辅助线 #E0E0E0

## 工作流程

### 1. 确定图表需求
- 读取章节中的 `[图X-Y: 标题]` 占位符
- 更新 `knowledge-base/figures/index.md` 图表索引

### 2. 根据图表类型选择策略

**架构/概念图**: 生成 AI 图片提示词
```
Create a professional [type] diagram: "[title]".
Layout: [horizontal/vertical/radial].
Elements: [list with colors and labels].
Style: flat vector, white background, sans-serif, [size]mm, 300dpi.
Color scheme: primary #1565C0, secondary #4CAF50, accent #7B1FA2.
```

**数据曲线图**: 生成 matplotlib Python 代码
```python
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei']  # 中文支持
plt.rcParams['axes.unicode_minus'] = False
# ... 绑定数据和样式
```

**流程图**: 生成 Mermaid 代码（可配合 mermaid-diagrams 技能）

## 输入

告诉我：
1. 哪本书哪一章的哪张图
2. 或者直接描述想要的图表内容
