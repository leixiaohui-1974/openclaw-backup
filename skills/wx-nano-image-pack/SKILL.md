# WX Nano Image Pack

Generate WeChat article illustrations by directly calling `nano-banana-pro`.

## What it does
- Parse `【配图建议 N：...】` lines from a Markdown article.
- Build polished English prompts for each figure slot.
- Call Nano Banana script directly for each image.
- Save images and a `manifest.json` mapping file.

## Requirements
- Nano script exists at: `~/.openclaw/workspace/skills/nano-banana-pro/scripts/generate_image.py`
- Valid `GEMINI_API_KEY` (or key in `~/.openclaw/openclaw.json`)
- `uv` installed

## Usage

```bash
python3 scripts/generate_wx_images.py \
  --article /home/admin/workspace/articles/wx_auto_20260305.md \
  --output-dir /home/admin/workspace/articles/wx_auto_20260305_imgs \
  --resolution 2K
```

## Output
- `wx_01.png ... wx_06.png`
- `manifest.json`

