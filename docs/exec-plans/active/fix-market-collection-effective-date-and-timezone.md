# 修复市场采集有效日期与最近尝试时区

## Stage（阶段）

需求澄清与实施阶段：统一上海市场有效日期、修正 2026-09-15 开市前误写的快照日期，并完成采集页时间展示回归。

## Status（状态）

`completed-with-production-write-code-deploy-pending`

## Scope（范围）

- 定义并实现数据采集页/API/CLI 共用的上海时区有效市场日：开市前不得把尚未开始的当日行情当作已完成交易日；开市前请求必须按可证明的上一真实交易日处理，或明确拒绝无法证明实际日期的 provider 结果。
- 对本次误写为 `2026-09-15` 的成功或部分成功采集执行可审计、可回滚的重标迁移，将数据放回 `2026-09-14`；迁移前校验 payload/质量元数据的实际日期、目标日期冲突、checksum 和 materialized aggregate，禁止跨日期覆盖或伪造数据。
- 将数据采集页“最近尝试”及相关抓取时间统一按 `Asia/Shanghai` 格式化，显示 UTC 偏移并保留原始 UTC ISO；前端与后端字段保持现有契约兼容。
- 同步产品规格、架构边界、运行手册、仓库状态和测试证据；不改变交易规则 ID、provider 真实日期证据或生产 PVC，未获授权不执行生产数据库写入。

## Acceptance（验收）

- 上海时区边界测试覆盖开市前、开市后、结算前后、周末和带 offset/无时区 `now`；开市前默认有效日期与上一真实交易日一致，未来日期和 provider 实际日期不匹配均被拒绝或标记为 `failed-missing`/`failed-retained`，不得把前一日行情伪装成当日成功快照。
- 数据采集页首次状态、单项/全部采集、CLI 和定时入口使用同一有效日期解析；研究页既有 15:00 规则不被无意改写。`2026-09-15` 误写样本经 dry-run 校验后可安全重标到 `2026-09-14`，已有 14 日成功值时采用显式冲突策略并保留审计记录，失败可回滚。
- “最近尝试”、`lastSuccessAt`、`fetchedAt` 等可见时间在桌面和 390px 视口显示北京时间（`Asia/Shanghai`）和 UTC 偏移，tooltip/接口仍保留规范 UTC ISO；null、非法值和无时区输入不被静默改写。
- 后端相关 pytest、前端 Vitest/build、迁移 dry-run/回归、`python scripts/check-docs-contract.py --mode=full` 和 `git diff --check` 通过；任何未运行检查及生产验证缺口记录在本计划。

## Completion Evidence（完成证据）

已完成有效日期边界、API 默认日期、日期重标迁移/回滚、前端时间显示与构建验证。相关后端聚焦测试 86 项通过，前端 Vitest 39 项通过，Vite build 通过，`git diff --check` 通过；将新增文件以 intent-to-add 暴露后，`scripts/check-docs-contract.py --mode=full` 通过。全量 pytest 共 528 项通过、78 项失败；失败集中在工作区原有 TrueNAS 部署脚本/fixture 漂移，与本计划改动无关，详见失败输出。生产 PVC 已完成一次授权迁移：`a-stock` Pod 的 `/data/snapshots.sqlite3` 先以 `Connection.backup()` 保存为 `/data/snapshots-pre-relabel-20260915.sqlite3`，隔离副本审计 `e4a5a6dee3624fb98631828333a1557c` 以 overwrite 应用，生产 `PRAGMA quick_check=ok`，15 日记录为 0、14 日快照为 4，Deployment 已恢复 1 副本并 rollout 成功。当前生产运行镜像仍是旧版本，盘前日期和北京时间代码尚未部署。

## Remaining Gaps（剩余缺口）

- 生产数据库迁移已完成并保留 before-image/备份；代码修复需通过受控镜像构建与部署后，才能在生产 API 上验证盘前默认日期和采集页北京时间展示。
- Provider 的“开市前可返回上一交易日收盘数据”能力依数据源而异；无法证明实际日期时必须保持 `insufficient`/`failed`，不能通过日期重命名绕过证据要求。
- 生产备份和迁移回滚演练尚未执行；如需撤销，必须先停止采集写入并使用审计回滚流程。

## Next Step（下一步）

1. 通过受控发布入口构建并部署包含本次日期及时区修复的不可变镜像；部署前后保持 SQLite/PVC 不变。
2. 部署后在生产 API 只读验证：盘前省略 `as_of` 返回上一交易日，显式 15 日请求被拒绝，数据采集页时间显示为北京时间。
3. 保留 `/data/snapshots-pre-relabel-20260915.sqlite3` 与 `snapshots-live-before-relabel-20260915.sqlite3`，如需撤销使用审计 `e4a5a6dee3624fb98631828333a1557c` 的 rollback 流程并先停止写入。
