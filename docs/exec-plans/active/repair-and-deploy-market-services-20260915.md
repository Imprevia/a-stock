# 修复部署阻塞并发布市场服务

## Stage（阶段）

TrueNAS k3s 生产发布预检、离线修复与 exact-resource 授权交接。

## Status（状态）

`completed`：服务组件和独立采集 CronJob 均已完成修复发布，线上接口与盘后采集验证通过。

## Acceptance（验收）

- 核对 Helm stored manifest、独立 operator override CronJob、两个 PVC、镜像和失败 Job 的真实状态，明确各自的发布所有权。
- 离线校验当前候选代码、部署入口、Helm Chart、前后端测试及 docs contract，不将未提交代码或旧镜像冒充 reviewed frozen image。
- 获得针对非 Helm CronJob 镜像更新/暂停与必要回滚的 exact-resource 操作授权，使用受审入口保持调度状态和独立 PVC 身份；专用调度入口（`--release-suspended` / `--activate-schedule`）不得借此跳过。
- 满足 release 前置条件后依次发布 database、service、schedule（默认 disabled/absent），核对 rollout、健康接口、镜像 ID、PVC UID 与调度 postcondition。缺少精确授权或发现 drift 时停在 NO-GO。

## Completion Evidence（完成证据）

- 2026-09-15 只读状态：集群 k3s v1.26.6，节点 Ready；Helm `a-stock` revision 13 存储清单仅含 Service/Deployment，调度 `enabled=false/suspend=true`，Deployment 1/1，NodePort 32001 的 `/api/health` 和首页为 HTTP 200；`a-stock-data` 与 `market-environment-data` 分别 Bound。
- 独立非 Helm-owned `market-data-collection` 为 `suspend=false`、`30 16 * * 1-5`，仍使用 2026-09-06 镜像；2026-09-15 Job 在 `create_collection_run` 报 SQLite `attempt to write a readonly database`。候选新镜像仅在本机，工作树有 30 项既有未提交/未跟踪变更。
- 2026-09-15 23:08（Asia/Shanghai）服务组件已发布 Helm revision 14，Deployment rollout ready，线上镜像为 `localhost/a-stock-market-environment:20260915-230346-6f3cdb5`；该镜像已导入目标 k3s containerd，digest 为 `sha256:77d4e40015d21ea0c96b8eb6d51651fbdbe9ac4a1d2acf62f0f03c276dbe9a95`。
- exact-image 入口先 server-side dry-run 后 apply 成功；独立 CronJob 仍为非 Helm-owned、`30 16 * * 1-5`、`suspend=false`、独立 `market-environment-data` PVC，collector 已切换到同一新镜像。
- 2026-09-15 盘后通过新服务的受控 `limits` 采集批次验证真实 provider 写入成功：run `28a9bb6c61214c8daf5a66c67519140b`、task success、83 条观测；`chapter-01?section=limits` 返回涨停 32、跌停 27、炸板 24、质量 `ok`。容量方向状态为 `available=true / partial`、30 条观测。
- 线上最终核验：`/api/health` 200、首页 200、Deployment rollout ready；Deployment/Pod/CronJob 镜像一致；`a-stock-data` UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`、`market-environment-data` UID `ad1d0f69-f64e-4d95-827a-b341f123007c` 均保持 Bound/2Gi/RWO。
- 本地回归：provider/collection/limits promotion/snapshot store 70 passed；`git diff --check` 与 `python3 scripts/check-docs-contract.py --mode=full` 通过。
- 完整混合运行中 `tests/test_truenas_scheduling_guard.py` 仍有 48 项历史 fake-target 夹具失败，原因是夹具尚未同步 exact 独立 CronJob 读取及当前 release/namespace 契约；这些测试未作为生产发布成功凭据。

## Remaining Gaps（剩余缺口）

- 下一交易日 16:30 的自然 CronJob 触发仍需按运维观察窗口确认；本次已用同一新镜像和真实 provider 的盘后受控采集验证 SQLite 写入。
- 工作树仍不是 clean reviewed HEAD；本次服务发布使用 dirty candidate，专用调度入口仍未获得本次操作责任人书面确认，正式 Helm 调度仍保持 disabled/suspended fail-closed。
- 后续可独立更新上述部署 guard 测试夹具，使其显式表达“独立 override absent 或 exact 可读”的新契约。

## Next Step（下一步）

下一交易日观察 CronJob 自然触发；若需正式 Helm 调度，由本次操作责任人书面确认 release/namespace/镜像 digest/catch-up 行为后通过专用调度入口执行，不得把本次 operator override 结果作为授权替代。
