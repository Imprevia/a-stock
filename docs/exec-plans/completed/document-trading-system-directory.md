# 编制交易系统目录索引

## Stage（阶段）

文档索引与仓库规则同步

## Status（状态）

`completed`

## Scope（范围）

根据 `搭建交易系统/` 的实际子目录和 Markdown 文件，生成一份保存在 `docs/` 下的目录索引，并在 `AGENTS.md` 中说明索引位置、章节结构和新增文档规则。不修改交易系统正文内容。

## Acceptance（验收）

- `docs/` 下存在一份完整的交易系统目录索引。
- 索引覆盖根入口、11 个章节目录及其全部 Markdown 文件。
- `AGENTS.md` 明确指向该索引，并说明目录与文件命名约定。
- 索引中的路径与实际文件树一致，无遗漏或虚构路径。
- `python scripts/check-docs-contract.py --mode=full` 通过。

## Completion Evidence（完成证据）

已生成 `docs/trading-system-directory.md`，覆盖实际 70 个 Markdown 文件；已更新 `AGENTS.md`、`docs/repository-guide.md` 和 `docs/status.md`。索引与实际文件树逐项比较，列出 70 个、实际 70 个，缺失 0 个、多余 0 个。

验证：`python scripts/check-docs-contract.py --mode=full` 输出 `docs-contract: 通过`。

## Remaining Gaps（剩余缺口）

- 后续新增或重命名交易系统文档时，需要同步维护目录索引。

## Next Step（下一步）

整理已完成；后续按 `AGENTS.md` 中的目录规则维护索引。
