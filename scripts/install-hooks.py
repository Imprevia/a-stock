#!/usr/bin/env python3
"""Install tracked hooks or verify their activation without modifying Git config."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

HOOKS = ("pre-commit", "pre-push", "commit-msg")


def check_hooks(root: Path) -> int:
    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"], cwd=root,
        capture_output=True, text=True, check=False,
    )
    configured = result.stdout.strip()
    if result.returncode not in (0, 1):
        print("install-hooks: 无法读取 Git hooks 配置", file=sys.stderr)
        return 1
    active = bool(configured) and (root / configured).resolve() == (root / ".githooks").resolve()
    missing = [name for name in HOOKS if not (root / ".githooks" / name).is_file()]
    executable = os.name == "nt" or all(
        os.access(root / ".githooks" / name, os.X_OK) for name in HOOKS
    )
    if not active or missing or not executable:
        print("install-hooks: inactive；运行 python scripts/install-hooks.py", file=sys.stderr)
        return 1
    print("install-hooks: active (pre-commit / pre-push / commit-msg)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False,
    )
    if result.returncode:
        print("install-hooks: 当前目录不是 Git 仓库", file=sys.stderr)
        return 1
    root = Path(result.stdout.strip())
    if args.check:
        return check_hooks(root)
    if any(not (root / ".githooks" / name).is_file() for name in HOOKS):
        print("install-hooks: hook 文件缺失；未修改配置", file=sys.stderr)
        return 1
    result = subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=root, check=False)
    if result.returncode:
        return result.returncode
    if os.name != "nt":
        for name in HOOKS:
            hook = root / ".githooks" / name
            hook.chmod(hook.stat().st_mode | 0o111)
    return check_hooks(root)


if __name__ == "__main__":
    sys.exit(main())
