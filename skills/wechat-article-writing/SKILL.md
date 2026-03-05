---
name: wechat-article-writing
description: |
  End-to-end WeChat article writing workflow.
  Use when user asks to:
  - 调用公众号写作skill
  - 生成公众号文章并发布飞书
  - 一键执行 写稿→评审→修改→配图→图文排版→标题A/B→写入飞书
  - "公众号写作", "公众号全流程", "微信文章自动生成"
homepage: local
metadata:
  openclaw:
    emoji: "🧠"
    requires:
      bins: [python3, uv]
---

# wechat-article-writing

可调用的公众号写作完整工作流 skill。

## 执行流程
- 写稿
- 三角色评审
- 修订
- 配图（默认跳过，避免超时；可切换为自动生成 5 张 nano-banana 图片）
- 图文排版
- 生成标题 A/B
- 覆盖写入飞书文档

## Usage

最简调用（零参数，使用默认主题+默认文档）：

```bash
python3 {baseDir}/scripts/run.py
```

推荐调用（显式指定）：

```bash
python3 {baseDir}/scripts/run.py \
  --topic "调度员会被AI取代吗？水网协同真相" \
  --doc-token "F1yfdz69Jo8k2kxIzshcMrFknVd"
```

可选参数：
- `--output-dir` 产物目录
- `--user-openid` 飞书授权用户
- `--feishu-app-id` / `--feishu-app-secret` 覆盖飞书配置
- `--image-mode skip|auto`，默认 `skip`（稳定）；`auto` 为尝试生成图片，失败自动降级无图

## Output
- 最终飞书文档链接
- 标题 A/B
- 本地完整产物目录（草稿/评审/终稿/图片/报告）
