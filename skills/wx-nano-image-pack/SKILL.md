# WX Full Workflow Skill

公众号全流程自动化技能，执行：
`写稿 → 评审 → 修改 → 生成 5 张图 → 插入图文 → 标题 A/B → 写入飞书文档`

## Main command

```bash
python3 scripts/wx_full_workflow.py \
  --topic "你的选题" \
  --doc-token "飞书文档token" \
  --output-dir "/home/admin/workspace/articles/wx_workflow_latest"
```

可选参数：
- `--user-openid` 指定授权用户（默认你的 openid）
- `--feishu-app-id` / `--feishu-app-secret` 手动覆盖飞书凭据

## Internal steps
1. LLM 生成公众号初稿（含 5 个配图占位符）
2. LLM 评审并输出结构化问题清单
3. LLM 按评审意见重写终稿
4. 直接调用 nano-banana 生成 5 张图
5. 把图片占位符替换成 Markdown 图文
6. 生成标题 A/B（JSON）
7. 用标题 A 固定为终稿主标题
8. 调用 `feishu-doc-publisher` 覆盖写入飞书正文并插图

## Artifacts
输出目录内会生成：
- `01_draft.md`
- `02_review.json`
- `03_revised.md`
- `04_with_images.md`
- `05_titles.json`
- `06_final.md`
- `images/wx_01.png` ~ `images/wx_05.png`
- `images/manifest.json`
- `run_report.json`

## Notes
- 飞书写入采用“先清空正文再写入”的覆盖模式，避免“只有标题”问题。
- LLM/Feishu 凭据默认从 `~/.openclaw/openclaw.json` 读取。
- 如只需生图，仍可使用：

```bash
python3 scripts/generate_wx_images.py \
  --article /path/to/article.md \
  --output-dir /path/to/images \
  --resolution 2K
```
