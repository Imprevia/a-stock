# 清理仓库根目录下的嵌套 a-stock 克隆

## Stage（阶段）

本地工作树清理与文档收口完成；未提交、未推送、未触碰远端。

## Status（状态）

completed-local-cleanup

## Scope（范围）

- 仓库根 `/home/gyt/a-stock/a-stock` 是一份独立克隆（自带 `.git`，HEAD `3d11b1e`，2026-10-07），外层索引仅以 gitlink 模式 `160000` 记录该指针，且仓库无 `.gitmodules`，不是可复现的 submodule。
- 该副本落后外层 `main` 67 个提交、567 个文件，`3d11b1e` 同时是外层 `main` 与 `origin/main` 的祖先；副本工作树干净、无未跟踪文件、无 stash、无未推送提交，因此不包含任何独有内容。
- 删除磁盘副本、解除 gitlink 跟踪，并在 `.gitignore` 增加根级 `/a-stock/` 规则，防止再次落入索引。
- 明确不做：不修改任何远端分支、不 force-push、不改写历史；不触碰工作树中其他未提交改动（QTS-04 skill 相关文件）；不执行 pytest 全量回归以外的生产或部署操作。

## Acceptance（验收）

- `/home/gyt/a-stock/a-stock` 不存在，外层 `git status` 显示 gitlink 删除而不再出现重复源码树。
- `.gitignore` 含根级 `/a-stock/` 规则，重新放置同名目录不会进入索引。
- 裸跑 pytest 收集不再包含 `a-stock/tests`，同名模块 `import file mismatch` 错误消失。
- 文档记录该清理与其原因：`docs/repository-guide.md` 顶层目录地图说明根目录禁止嵌套克隆，`docs/exec-plans/active/_index.md` 登记本计划。
- 未提交/未推送状态下 `python scripts/check-docs-contract.py --mode=fast` 对暂存文件通过，`git diff --check` 通过。

## Completion Evidence（完成证据）

- 2026-11-14：删除前复核 `readlink -f` 目标为 `/home/gyt/a-stock/a-stock`；副本 `git status --porcelain` 为空、`HEAD=3d11b1e`、`3d11b1e` 是外层 `origin/main` 祖先；无 stash、无未推送提交。
- 2026-11-14：`rm -rf /home/gyt/a-stock/a-stock` 后目录消失，`git rm --cached a-stock` 解除索引中的 gitlink（状态变为 `D  a-stock`），回收磁盘 17M（含 4.4M `.git`）。
- 2026-11-14：`.gitignore` 新增 `# 仓库根目录下的嵌套克隆（2026-11-14 已清理，禁止恢复）` + `/a-stock/`；解除 gitlink 后 `git check-ignore -v a-stock` 命中 `.gitignore:17:/a-stock/`，同名目录不再进入索引。
- 2026-11-14：裸跑 `pytest --collect-only` 由 1838 tests / 48 errors 变为 1840 tests / 0 errors 且不再收集 `a-stock/tests`；48 个错误全部由该副本引起——841 条重复用例叠加同名测试模块的 `import file mismatch`，以及陈旧副本测试反向导入外层已重构的 `src` 时触发的 `LegacyContainerAdapters` 等 `ImportError`。
- 2026-11-14：`.venv/bin/python -m pytest tests -q` 结果为 `1739 passed, 101 skipped, 1 warning`（365.19s）；warning 为既有 Starlette `BlockingPortal` 弃用提示。skipped 为既有的 PostgreSQL/集成类跳过，未增加。
- 2026-11-14：`.venv/bin/python scripts/check-docs-contract.py --mode=full` 通过（代码 5 / 文档 4 / plan 2），`git diff --check` 通过。

## Remaining Gaps（剩余缺口）

- 本次未提交且未推送：工作树仍包含他人未提交的 QTS-04 skill 改动，提交动作留给用户决定；远端在该提交推送前仍保留旧 gitlink 历史。
- 本计划只清理本地工作树，不回溯历史中 `16d9b3e` 记录的 gitlink 指针（历史重写需要单独授权）。

## Next Step（下一步）

本次本地清理已完成。若需固化，只提交 `a-stock` gitlink 删除、`.gitignore`、本计划与索引/指南更新，不要夹带 QTS-04 skill 的未完成改动。
