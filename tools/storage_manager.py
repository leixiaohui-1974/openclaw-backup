#!/usr/bin/env python3
"""OpenClaw 存储管理工具

用法:
  python3 storage_manager.py status          # 查看存储状态
  python3 storage_manager.py archive          # 归档大文件到 OSS
  python3 storage_manager.py clean-cache      # 清理各种缓存
  python3 storage_manager.py list-oss         # 列出 OSS 归档内容
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

OSS_MOUNT = Path("/home/admin/oss-workspace")
OSS_ARCHIVE = OSS_MOUNT / "archive"
LOCAL_ARTICLES = Path("/home/admin/workspace/workspace/articles")
LOCAL_IMAGES = LOCAL_ARTICLES / "images"
LOCAL_IMAGES_NEW = LOCAL_ARTICLES / "images-new"
LOCAL_VIDEOS = LOCAL_ARTICLES / "video"

def get_dir_size(path):
    """Get directory size in bytes."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += get_dir_size(entry.path)
    except PermissionError:
        pass
    return total

def human_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"

def cmd(command):
    r = subprocess.run(command, shell=True, capture_output=True, text=True)
    return r.stdout.strip()

def status():
    print("=" * 60)
    print("OpenClaw 存储状态报告")
    print("=" * 60)

    # Disk usage
    df = cmd("df -h / | tail -1").split()
    print(f"\n本地磁盘: {df[1]} 总 | {df[2]} 已用 ({df[4]}) | {df[3]} 可用")

    # OSS mount
    if OSS_MOUNT.is_mount():
        oss_used = get_dir_size(OSS_MOUNT)
        print(f"OSS (lxh-openclaw): ✅ 已挂载 | {human_size(oss_used)} 已用 | 无限容量")
    else:
        print("OSS (lxh-openclaw): ❌ 未挂载")

    # Content breakdown
    print(f"\n--- 内容文件 ---")
    dirs = [
        ("文章图片 (images)", LOCAL_IMAGES),
        ("文章图片 (images-new)", LOCAL_IMAGES_NEW),
        ("视频", LOCAL_VIDEOS),
    ]
    for name, path in dirs:
        if path.exists():
            size = get_dir_size(path)
            count = len(list(path.glob("*")))
            print(f"  {name}: {human_size(size)} ({count} 文件)")

    # OSS archive
    if OSS_MOUNT.is_mount():
        print(f"\n--- OSS 归档 ---")
        for sub in ["images", "videos", "articles"]:
            p = OSS_ARCHIVE / sub
            if p.exists():
                size = get_dir_size(p)
                count = len(list(p.glob("*")))
                print(f"  {sub}: {human_size(size)} ({count} 文件)")

    # Cache sizes
    print(f"\n--- 可清理缓存 ---")
    caches = [
        ("npm", Path.home() / ".npm"),
        ("pip", Path.home() / ".cache/pip"),
        ("uv", Path.home() / ".cache/uv"),
        ("Homebrew", Path.home() / ".cache/Homebrew"),
        ("pnpm", Path.home() / ".cache/pnpm"),
    ]
    total_cache = 0
    for name, path in caches:
        if path.exists():
            size = get_dir_size(path)
            total_cache += size
            if size > 10 * 1024 * 1024:  # >10MB
                print(f"  {name}: {human_size(size)}")
    print(f"  合计可回收: {human_size(total_cache)}")

def archive():
    if not OSS_MOUNT.is_mount():
        print("❌ OSS 未挂载，请先执行: ossfs lxh-openclaw /home/admin/oss-workspace ...")
        sys.exit(1)

    for sub in ["images", "videos", "articles"]:
        (OSS_ARCHIVE / sub).mkdir(parents=True, exist_ok=True)

    count = 0
    # Archive images
    for img_dir in [LOCAL_IMAGES, LOCAL_IMAGES_NEW]:
        if img_dir.exists():
            for f in img_dir.glob("*.png"):
                dest = OSS_ARCHIVE / "images" / f.name
                if not dest.exists():
                    shutil.copy2(f, dest)
                    print(f"  📷 {f.name} → OSS")
                    count += 1

    # Archive videos
    if LOCAL_VIDEOS.exists():
        for f in LOCAL_VIDEOS.glob("*.mp4"):
            dest = OSS_ARCHIVE / "videos" / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
                print(f"  🎬 {f.name} → OSS")
                count += 1

    # Archive markdown articles
    for f in LOCAL_ARTICLES.glob("*.md"):
        dest = OSS_ARCHIVE / "articles" / f.name
        if not dest.exists() or f.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(f, dest)
            print(f"  📄 {f.name} → OSS")
            count += 1

    if count == 0:
        print("✅ 所有文件已是最新，无需归档")
    else:
        print(f"\n✅ 归档完成: {count} 个新文件")

def clean_cache():
    print("清理缓存...")
    cmds = [
        ("npm", "npm cache clean --force 2>/dev/null"),
        ("pip", "pip cache purge 2>/dev/null"),
        ("uv", "uv cache clean 2>/dev/null"),
    ]
    for name, c in cmds:
        subprocess.run(c, shell=True, capture_output=True)
        print(f"  ✅ {name} 已清理")

    # Clean Homebrew downloads
    hb = Path.home() / ".cache/Homebrew/downloads"
    if hb.exists():
        size = get_dir_size(hb)
        shutil.rmtree(hb, ignore_errors=True)
        hb.mkdir(parents=True, exist_ok=True)
        print(f"  ✅ Homebrew 已清理 ({human_size(size)})")

    df = cmd("df -h / | tail -1").split()
    print(f"\n磁盘: {df[2]} 已用 ({df[4]}) | {df[3]} 可用")

def list_oss():
    if not OSS_MOUNT.is_mount():
        print("❌ OSS 未挂载")
        sys.exit(1)

    print("OSS 归档内容 (lxh-openclaw):")
    for root, dirs, files in os.walk(OSS_MOUNT):
        level = root.replace(str(OSS_MOUNT), '').count(os.sep)
        indent = '  ' * level
        dirname = os.path.basename(root)
        if level == 0:
            dirname = "oss-workspace/"
        print(f"{indent}{dirname}/")
        for f in sorted(files):
            fp = Path(root) / f
            size = fp.stat().st_size
            print(f"{indent}  {f} ({human_size(size)})")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    action = sys.argv[1]
    if action == "status":
        status()
    elif action == "archive":
        archive()
    elif action == "clean-cache":
        clean_cache()
    elif action == "list-oss":
        list_oss()
    else:
        print(f"未知命令: {action}")
        print(__doc__)
        sys.exit(1)
