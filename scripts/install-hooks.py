#!/usr/bin/env python3
"""安装 / 重连本地 git hooks。

用法:
    python scripts/install-hooks.py

行为:
    1. git config core.hooksPath .githooks
    2. macOS / Linux 上为 hook 入口补可执行位（Windows 依赖 Git for Windows 内置 sh，无需 chmod）
"""

from __future__ import annotations

import os
import subprocess
import sys

HOOKS = [".githooks/pre-commit", ".githooks/pre-push"]

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def main() -> int:
    result = subprocess.run(["git", "config", "core.hooksPath", ".githooks"])
    if result.returncode != 0:
        print("install-hooks: git config 失败（当前目录是 git 仓库吗？）", file=sys.stderr)
        return 1

    if os.name != "nt":  # 类 Unix 平台补可执行位；Windows 不是必需步骤
        for hook in HOOKS:
            if os.path.isfile(hook):
                os.chmod(hook, 0o755)

    print("install-hooks: 已设置 core.hooksPath=.githooks")
    missing = [h for h in HOOKS if not os.path.isfile(h)]
    if missing:
        print(f"install-hooks: 警告，以下 hook 文件缺失：{missing}", file=sys.stderr)
        return 1
    print("install-hooks: hooks 就绪（pre-commit=fast，pre-push=full）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
