#!/usr/bin/env python3
"""本地文档契约门禁（docs-contract gate）。

用法:
    python scripts/check-docs-contract.py --mode=fast   # pre-commit：作用于 staged
    python scripts/check-docs-contract.py --mode=full   # pre-push / 手动：作用于 upstream...HEAD

规则事实源: AGENTS.md 硬规则 + docs/repository-guide.md 代码-文档映射表。
修改本脚本的错误消息时必须同步 AGENTS.md。

逃生口（显式且可审计）:
    [skip-plan]            commit message 标记，跳过 Gate 2/3
    [docs-only] / [no-docs] commit message 标记，跳过 Gate 1（应附理由）
    SKIP_PLAN_GATE=1       环境变量，跳过 Gate 2/3
    SKIP_DOCS_CONTRACT=1   环境变量，跳过全部 gate（仅应急）
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys

# ---------- Windows 控制台编码安全 ----------

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # Python < 3.7 场景，几乎不会发生
        pass

# ---------- 常量 ----------

MODE = "full" if "--mode=full" in sys.argv else "fast"

# 顶层代码目录（仓库等价代码区；业务目录落地后按 repository-guide 映射表扩展）
CODE_TOP_DIRS = {"src", "apps", "packages", "tools"}
# 代码文件扩展名（docs/ 下的不算代码）
CODE_EXTS = {".py", ".pyi", ".js", ".ts", ".tsx", ".mjs", ".go", ".rs", ".vue", ".java"}

# Gate 0：必需文件存在
REQUIRED_FILES = [
    "AGENTS.md",
    "README.md",
    "docs/repository-guide.md",
    "docs/architecture.md",
    "docs/runbooks.md",
    "docs/lessons-learned.md",
    "docs/status.md",
    "docs/exec-plans/active/_index.md",
    "scripts/check-docs-contract.py",
    "scripts/install-hooks.py",
    ".githooks/pre-commit",
    ".githooks/pre-push",
]

# Gate 4：active plan 必需字段（标题中英任一即可）
PLAN_REQUIRED_FIELDS = {
    "Stage": "阶段",
    "Status": "状态",
    "Acceptance": "验收",
    "Completion Evidence": "完成证据",
    "Remaining Gaps": "剩余缺口",
    "Next Step": "下一步",
}

# Gate 5-7：代码-文档映射（glob: (必需文档, 门禁级别 fail/warn)）
# 映射为空/未命中 → 对应 gate 跳过。业务代码落地后按 repository-guide 映射表扩展。
DOCS_MAP: dict[str, tuple[tuple[str, ...], str]] = {
    "src/**": (("docs/architecture.md",), "fail"),
    "apps/**": (("docs/architecture.md", "docs/runbooks.md"), "fail"),
    "scripts/**": (("docs/runbooks.md",), "warn"),
    "requirements.txt": (("docs/runbooks.md", "README.md"), "fail"),
    "pyproject.toml": (("docs/runbooks.md", "README.md"), "fail"),
}

# Gate 3 阈值（默认启发式，可按仓库调整）
PLAN_GATE_TOP_DIR_THRESHOLD = 2
PLAN_GATE_FILE_THRESHOLD = 5

# 小改 escape 阈值
SMALL_CHANGE_FILES = 1
SMALL_CHANGE_DIRS = 1
SMALL_CHANGE_LINES = 20


# ---------- git 工具 ----------

def git(args: list[str]) -> str:
    """运行 git 命令并返回输出；失败时抛异常由调用方处理。"""
    out = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} 失败")
    return out.stdout


def try_git(args: list[str]) -> str:
    try:
        return git(args)
    except (RuntimeError, OSError):
        return ""


def changed_files() -> list[str]:
    """返回当前变更集文件列表。fast=staged；full=upstream...HEAD（逐级回退）。"""
    if MODE == "fast":
        raw = try_git(["diff", "--name-only", "--cached"])
    else:
        raw = try_git(["diff", "--name-only", "@{u}...HEAD"])
        if not raw:
            raw = try_git(["diff", "--name-only", "origin/main...HEAD"])
        if not raw:
            raw = try_git(["diff", "--name-only", "HEAD"])
    files = []
    for line in raw.splitlines():
        name = line.strip().strip('"')
        if name:
            files.append(name.replace("\\", "/"))
    return files


def changed_line_count(files: list[str]) -> int:
    """统计变更集的增删行数（用于 <20 行小改判定）。"""
    if MODE == "fast":
        raw = try_git(["diff", "--numstat", "--cached"])
    else:
        raw = try_git(["diff", "--numstat", "@{u}...HEAD"]) or try_git(
            ["diff", "--numstat", "origin/main...HEAD"]
        ) or try_git(["diff", "--numstat", "HEAD"])
    total = 0
    wanted = set(files)
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, name = parts[0], parts[1], parts[2].strip().strip('"').replace("\\", "/")
        if name not in wanted:
            continue
        for n in (added, deleted):
            total += int(n) if n.isdigit() else 0  # 二进制文件显示 "-"，按 0 计
    return total


def last_commit_message() -> str:
    """最近一次 commit message（pre-commit 场景下的近似逃生口载体）。"""
    return try_git(["log", "-1", "--pretty=%B"])


# ---------- 分类 ----------

def is_code(path: str) -> bool:
    top = path.split("/", 1)[0]
    if top in {"docs", ".githooks", ".codegraph", ".agent-state", "notes"}:
        return False
    if top in CODE_TOP_DIRS:
        return True
    _, ext = os.path.splitext(path)
    return ext in CODE_EXTS


def is_docs(path: str) -> bool:
    return path.startswith("docs/") or path in {"README.md", "AGENTS.md"}


def is_plan(path: str) -> bool:
    return bool(re.fullmatch(r"docs/exec-plans/active/(?!_index\.md)[^/]+\.md", path))


def top_dir(path: str) -> str:
    return path.split("/", 1)[0]


# ---------- gate 实现 ----------

def fail(msg: str) -> None:
    print(msg, file=sys.stderr)


def gate0_required_files() -> bool:
    """Gate 0：harness 必需文件存在。"""
    missing = [f for f in REQUIRED_FILES if not os.path.isfile(f)]
    if missing:
        fail("docs-contract: 必需文件缺失（Gate 0）：")
        for f in missing:
            fail(f"  - {f}")
        fail("  修复：恢复上述文件，或更新 scripts/check-docs-contract.py 的 REQUIRED_FILES 并同步 AGENTS.md")
        return False
    return True


def gate4_plan_fields() -> bool:
    """Gate 4：active plan 必需字段完整。"""
    ok = True
    active_dir = os.path.join("docs", "exec-plans", "active")
    if not os.path.isdir(active_dir):
        return True  # Gate 2 会另行报告
    for name in sorted(os.listdir(active_dir)):
        if not name.endswith(".md") or name == "_index.md":
            continue
        path = os.path.join(active_dir, name)
        try:
            content = open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            fail(f"docs-contract: 无法读取 active plan {path}: {exc}")
            ok = False
            continue
        missing = [
            en for en, zh in PLAN_REQUIRED_FIELDS.items()
            if en not in content and zh not in content
        ]
        if missing:
            fail(f"plan-gate: active plan 缺必需字段（Gate 4）：{path}")
            fail("  必需：" + " / ".join(
                f"{en}（{zh}）" for en, zh in PLAN_REQUIRED_FIELDS.items()))
            ok = False
    return ok


def plan_gate_escape(code_files: list[str], top_dirs: set[str], lines: int, msg: str) -> bool:
    """Gate 2/3 的小改与显式逃生口判定。"""
    if "[skip-plan]" in msg or os.environ.get("SKIP_PLAN_GATE") == "1":
        return True
    if len(code_files) <= SMALL_CHANGE_FILES and len(top_dirs) <= SMALL_CHANGE_DIRS:
        return True
    if lines < SMALL_CHANGE_LINES and len(top_dirs) <= SMALL_CHANGE_DIRS:
        return True
    return False


def gate1_docs(code_files: list[str], doc_files: list[str], msg: str) -> bool:
    """Gate 1：代码改动必须伴随事实源更新。"""
    if not code_files or doc_files:
        return True
    if "[docs-only]" in msg or "[no-docs]" in msg:
        return True
    fail("docs-contract: 代码改动未伴随事实源更新（Gate 1）。")
    fail("  同一任务内更新 docs/、README.md 或 AGENTS.md。")
    fail("  如确不需要，commit message 加 [no-docs] 并说明理由。")
    return False


def gate2_plan_exists(code_files: list[str], plan_files_on_disk: bool,
                      plan_changes: list[str], escape: bool) -> bool:
    """Gate 2：代码改动不得先于 active plan（存在或变更均可）。"""
    if not code_files or plan_files_on_disk or plan_changes or escape:
        return True
    fail("plan-gate: 代码改动前必须更新 docs/exec-plans/active/*.md（Gate 2）。")
    fail("  创建 active plan 后重试；小改可加 [skip-plan] 或设 SKIP_PLAN_GATE=1。")
    return False


def gate3_plan_change(code_files: list[str], top_dirs: set[str],
                      plan_changes: list[str], escape: bool) -> bool:
    """Gate 3：跨目录 / 多文件工作需要本次变更 active plan（仅 full 模式）。"""
    if MODE != "fast" and code_files:
        triggered = (
            len(top_dirs) >= PLAN_GATE_TOP_DIR_THRESHOLD
            or len(code_files) >= PLAN_GATE_FILE_THRESHOLD
        )
        if triggered and not plan_changes and not escape:
            fail(f"plan-gate: 跨区工作（{len(top_dirs)} 个顶层代码区 / {len(code_files)} 个代码文件）"
                 "需要本次变更 docs/exec-plans/active/*.md（Gate 3）。")
            fail("  创建或更新 active plan 后重试；小改可加 [skip-plan] 或设 SKIP_PLAN_GATE=1。")
            return False
    return True


def gate5to7_docs_map(code_files: list[str], doc_files: list[str]) -> bool:
    """Gate 5-7：代码-文档映射强制（仅 full 模式；映射未命中即跳过）。"""
    ok = True
    doc_set = set(doc_files)
    for pattern, (required, level) in DOCS_MAP.items():
        hits = [f for f in code_files if fnmatch.fnmatch(f, pattern)]
        if not hits:
            continue
        missing = [d for d in required if d not in doc_set]
        if not missing:
            continue
        message = (
            f"docs-contract: {pattern} 改动需同步更新 {'、'.join(missing)}"
            f"（Gate 5-7 映射，级别 {level}）。命中文件：{'、'.join(hits[:5])}"
        )
        if level == "fail":
            fail(message)
            ok = False
        else:
            print(f"[warn] {message}")
    return ok


# ---------- 主流程 ----------

def main() -> int:
    if os.environ.get("SKIP_DOCS_CONTRACT") == "1":
        print("docs-contract: SKIP_DOCS_CONTRACT=1，已跳过（应急用法，须记录原因）")
        return 0

    print(f"docs-contract: 模式 {MODE}")

    ok = True
    ok &= gate0_required_files()
    ok &= gate4_plan_fields()

    files = changed_files()
    code_files = [f for f in files if is_code(f)]
    doc_files = [f for f in files if is_docs(f)]
    plan_changes = [f for f in files if is_plan(f)]
    top_dirs = {top_dir(f) for f in code_files}
    lines = changed_line_count(code_files)
    msg = last_commit_message()
    escape = plan_gate_escape(code_files, top_dirs, lines, msg)

    ok &= gate1_docs(code_files, doc_files, msg)
    ok &= gate2_plan_exists(code_files, any_plan_on_disk(), plan_changes, escape)
    ok &= gate3_plan_change(code_files, top_dirs, plan_changes, escape)
    ok &= gate5to7_docs_map(code_files, doc_files)

    if not files:
        print("docs-contract: 无变更，跳过 diff 检查")
    if ok:
        print(f"docs-contract: 通过（代码 {len(code_files)} / 文档 {len(doc_files)} / plan {len(plan_changes)}）")
    return 0 if ok else 1


def any_plan_on_disk() -> bool:
    """active/ 目录是否存在至少一个 plan 文件（不含 _index.md）。"""
    active_dir = os.path.join("docs", "exec-plans", "active")
    if not os.path.isdir(active_dir):
        return False
    return any(
        n.endswith(".md") and n != "_index.md" for n in os.listdir(active_dir)
    )


if __name__ == "__main__":
    sys.exit(main())
