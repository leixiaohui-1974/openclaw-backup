#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

NANO_SCRIPT = Path.home() / ".openclaw/workspace/skills/nano-banana-pro/scripts/generate_image.py"

PROMPT_TEMPLATES = {
    1: "Night smart-water dispatch control room, Chinese engineers monitoring giant digital wall, AI recommendation panels side-by-side with human decision console, tense rainstorm context, cinematic realistic illustration, high detail, no text, 16:9",
    2: "Split-screen workflow comparison infographic: left manual dispatch process with fragmented screens and slow response cues, right AI-assisted dispatch process with unified dashboard and fast response cues, professional clean style, no text, 16:9",
    3: "Three-layer collaboration architecture diagram for water network operations: sensing layer, recommendation layer, decision layer, clear boundary between AI recommendation and human confirmation, modern engineering visual style, no text labels, 16:9",
    4: "Storm response timeline scene, two strategy-switch moments highlighted on a time axis, control team discussion and dashboard updates, risk level escalation then stabilization, technical cinematic style, no text, 16:9",
    5: "Safety-rule whitelist concept illustration for autonomous water operations, protected control boundary, forbidden zones, policy shield over actuators and valves, robust governance visual metaphor, clean tech style, no text, 16:9",
    6: "Role migration concept art: operator to strategist, career capability ladder in smart water utility, from manual control desk to strategic orchestration center, forward-looking professional style, no text, 16:9",
}


def parse_image_slots(markdown_text: str):
    pattern = re.compile(r"【配图建议\s*(\d+)：([^】]+)】")
    slots = []
    for m in pattern.finditer(markdown_text):
        idx = int(m.group(1))
        desc = m.group(2).strip()
        slots.append({"index": idx, "description": desc})
    slots.sort(key=lambda x: x["index"])
    return slots


def build_prompt(slot):
    idx = slot["index"]
    base = PROMPT_TEMPLATES.get(idx)
    if base:
        return base
    return (
        f"Professional illustration for WeChat article section. Topic: {slot['description']}. "
        "Smart water operations, modern engineering visual language, clean composition, no text, 16:9"
    )


def run_nano(prompt: str, output_path: Path, resolution: str):
    cmd = [
        "uv",
        "run",
        str(NANO_SCRIPT),
        "--prompt",
        prompt,
        "--filename",
        str(output_path),
        "--resolution",
        resolution,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    ok = result.returncode == 0 and output_path.exists()
    return ok, result


def main():
    parser = argparse.ArgumentParser(description="Generate WX article images using nano-banana directly")
    parser.add_argument("--article", required=True, help="Path to markdown article")
    parser.add_argument("--output-dir", required=True, help="Directory for generated images")
    parser.add_argument("--resolution", default="2K", choices=["1K", "2K", "4K"])
    args = parser.parse_args()

    article_path = Path(args.article)
    output_dir = Path(args.output_dir)

    if not article_path.exists():
        raise SystemExit(f"Article not found: {article_path}")
    if not NANO_SCRIPT.exists():
        raise SystemExit(f"Nano script not found: {NANO_SCRIPT}")

    output_dir.mkdir(parents=True, exist_ok=True)

    text = article_path.read_text(encoding="utf-8")
    slots = parse_image_slots(text)
    if not slots:
        raise SystemExit("No image slots found. Expected lines like: 【配图建议 1：...】")

    manifest = {
        "article": str(article_path),
        "resolution": args.resolution,
        "nano_script": str(NANO_SCRIPT),
        "images": [],
    }

    print(f"Found {len(slots)} image slots")
    for slot in slots:
        idx = slot["index"]
        filename = f"wx_{idx:02d}.png"
        output_path = output_dir / filename
        prompt = build_prompt(slot)

        print(f"[{idx}] Generating {filename}")
        ok, result = run_nano(prompt, output_path, args.resolution)

        entry = {
            "index": idx,
            "description": slot["description"],
            "filename": filename,
            "path": str(output_path),
            "prompt": prompt,
            "ok": ok,
        }

        if not ok:
            entry["stderr"] = (result.stderr or "")[-2000:]
            entry["stdout"] = (result.stdout or "")[-2000:]
            print(f"  failed: {result.stderr.strip() or result.stdout.strip()}")
        else:
            print(f"  saved: {output_path}")

        manifest["images"].append(entry)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    success = sum(1 for x in manifest["images"] if x["ok"])
    total = len(manifest["images"])
    print(f"Done: {success}/{total} images generated")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
