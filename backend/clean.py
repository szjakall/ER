# -*- coding: utf-8 -*-
"""
清理仓库内的非项目文件（编译缓存等）
====================================

用途：跑完测试/服务后，确保 git 目录下只留项目文件。

运行：python clean.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

JUNK_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
             "dist", ".mypy_cache", ".ruff_cache"}
JUNK_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def main() -> None:
    removed = []
    for p in list(ROOT.rglob("*")):
        if ".git" in p.parts:
            continue
        if p.is_dir() and p.name in JUNK_DIRS:
            removed.append(p.relative_to(ROOT))
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file() and (p.suffix == ".pyc" or p.name in JUNK_FILES):
            removed.append(p.relative_to(ROOT))
            p.unlink(missing_ok=True)

    if removed:
        print(f"已清理 {len(removed)} 项：")
        for r in removed:
            print(f"  - {r}")
    else:
        print("仓库已干净，无需清理。")


if __name__ == "__main__":
    main()
