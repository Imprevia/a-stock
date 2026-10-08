# 部署统一市场数据采集适配器到 TrueNAS k3s（2026-10-08）

## Stage（阶段）

生产发布前只读发现与调度回退授权准备。

## Status（状态）

completed-with-production-write

## Acceptance（验收）

- 将应用候选 `b2dd6898eb79a06a4cff00c2a14213fc0f28648c` 通过 `scripts/deploy-truenas-k3s.sh --component all` 发布到 TrueNAS `192.168.1.20` 的 Helm release `a-stock` / namespace `a-stock`。
- 发布前必须通过受控 `--disable-schedule` 将 exact `a-stock-data-collection` 安全关闭并证明 absent；该操作需操作责任人单独明确授权，禁止裸 `kubectl patch/delete` 或 `helm rollback/uninstall`。
- 普通发布最终值保持 `scheduledCollection.enabled=false`、`suspend=true`，Scrapling 保持 disabled 且生产 allowlist 为空；不启用新的 Fuyao、TDX 或 sector enrichment 开关，不创建 provider-backed Job，不调用刷新接口。
- 不创建、修改或输出 Secret；不删除、替换、扩容、重绑 PostgreSQL/SQLite PVC，不修改生产数据。
- 发布后验证 Helm revision、Deployment/StatefulSet/Pod Ready、精确镜像 tag/digest、NodePort 健康、provider-free GET、两个 exact CronJob absent，并证明两个 PVC 的 UID/PV/容量保持不变。

## Deployment Boundary（部署边界）

- 目标集群：`192.168.1.20`，k3s `v1.26.6+k3s-6a894050-dirty`。
- release / namespace：`a-stock` / `a-stock`。
- 应用候选：`b2dd6898eb79a06a4cff00c2a14213fc0f28648c`；执行生产写入前还需与 `origin/main` 对齐并在 clean、受审 checkout 中运行。
- 普通发布入口：`bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all`。
- 回退：先确保 exact CronJob absent/suspended，再从受审 rollback commit 构建新的不可变 tag 并重跑同一普通入口；不得恢复历史 Helm revision、卸载 release 或删除 PVC。

## Completion Evidence（完成证据）

- 2026-10-08 只读发现确认节点 `ix-truenas` 为 `Ready`，`k3s` systemd 为 `enabled/active`，集群版本为 `v1.26.6+k3s-6a894050-dirty`。
- 当前 Helm release 为 revision `82`，Dashboard 镜像为 `localhost/a-stock-market-environment:20260930-115139-40c3498`；Deployment `1/1`。
- 当前 exact `a-stock-data-collection` 为 `30 16 * * 1-5`、`suspend=false`，2026-10-08 16:30（Asia/Shanghai）已自然触发 Job。普通应用发布的 off/absent 前置条件不成立，因此未执行镜像构建、传输、containerd 导入或 Helm 写入。
- PostgreSQL PVC `a-stock-postgresql-data` 为 `Bound`，UID `6c426fc5-10e2-4e88-b534-b258c70869c4`、PV `a-stock-postgresql-data`、容量 `5Gi`；旧 SQLite PVC `a-stock-data` 为 `Bound`，UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`、PV `a-stock-data`、容量 `2Gi`。
- baseline Helm lint 与 Kubernetes `1.26.6` template 通过；合并值为 `scheduledCollection.enabled=false`、`suspend=true`。线上已有的手工刷新、TDX fallback、TDX 派生容量方向和 Fuyao Secret 引用与 baseline 一致，本次不扩大这些开关。
- Git 初次只读预检发现候选 `b2dd689` 尚未推送，随后已按操作责任人要求将代码及本计划提交推送到 `origin/main`；工作树另有用户已有的未跟踪嵌套目录 `a-stock/`。未删除、移动、忽略或提交该目录，生产操作改用独立 clean worktree。
- 2026-10-08 操作责任人明确授权“允许停止后续自动采集”。授权范围为 release `a-stock` / namespace `a-stock` 的受控 `--disable-schedule`，删除 exact Helm-owned `a-stock-data-collection` 并停止后续自动触发；不授权裸 `kubectl`/Helm 写入、provider-backed Job、Secret/PVC/生产数据修改或其他调度变更。
- 调度关闭 packet 使用 reviewed HEAD `eee52eacc5ca9d7a55a423293778133c196a8646`；该提交的 chart、部署脚本、验证器和 off overlay 与 revision 82 激活时的 reviewed HEAD `40c3498c16325ad0962661a841a3efe6d23cb7d2` 一致，并包含已归档的完整 scheduling baseline。
- 冻结镜像为 `localhost/a-stock-market-environment:20260930-115139-40c3498`，containerd manifest digest 为 `sha256:53c1219db808acd6860286725fa77ebda7da40f8dbcbf8e66e001056cfe05883`；chart/baseline/off-overlay/render SHA-256 依次为 `3ad82655fee3d42b6527b75608132e805b0238561101c71e6f9d4b31590fd01a`、`d7e6492934ccf56ebaeb77c3a16e6e1e83ef074d306c8d84f0dc8efb5a68e25c`、`d624601138ca7e803c7e1b7c85c86172fa17f6c1295b5ac49c576924f0fff8ff`、`b03baadde1914dbf23b3c11c96fc0569d811eb312fb7394a94ddf7e204e93ab6`。
- rollback-v1 canonical binding SHA-256 为 `c38c1ce02dd942750a1499b485a408525fa9ef24008c5c03e39aa51dca7c213d`，授权引用为 `rollback-v1:user-20261008-stop-auto-collection:c38c1ce02dd942750a1499b485a408525fa9ef24008c5c03e39aa51dca7c213d`；`--disable-schedule` 不适用 activation catch-up 行为。
- 第一次受控 `--disable-schedule` 将 Helm stored manifest 更新为 revision `83`；retained CronJob 仍为 active 时入口拒绝删除并非零退出，fail-safe 随即将 exact `a-stock-data-collection` 补偿为 `suspend=true`。该次操作未报告成功。
- 使用同一授权 packet 第二次执行后更新为 revision `84`；入口识别 stored manifest absent + live exact CronJob suspended 的 retained-resource 状态，删除 Helm-owned `a-stock-data-collection` 并两次读回证明 absent。未创建 canary 或 provider-backed Job，legacy `market-data-collection` 同样 absent。
- CronJob 删除后，其 owner-referenced 的三个既有 failed Job/Pod 已由 Kubernetes 级联清理；namespace 当前 CronJob/Job 列表均为空。它们的失败状态、UID、时间和 exit code 2 已在本计划的发布前证据中记录，未改写为成功。
- 调度关闭后 Dashboard 与 PostgreSQL 仍为 `1/1` Ready，`/api/health` 返回 HTTP 200；两个 PVC 的 UID、PV、容量和 `Bound` 状态与发布前一致。
- 第一次普通 `--component all` 尝试生成本地镜像 `20261008-234628-18afe45` 后，在镜像传输和 Helm write 前被本地健康门禁阻断：统一 bootstrap 已要求 PostgreSQL URL，但旧 smoke 命令未注入 `MARKET_ENVIRONMENT_DATABASE_URL`，容器以 `DatabaseConfigurationError` 退出。线上保持 revision `84`、旧镜像 Ready、CronJob absent，未导入该候选镜像。
- 部署脚本已改为仅在本地 smoke 容器中注入不可达的 loopback PostgreSQL URL `127.0.0.1:1`；实测 `/api/health` 与首页均为 HTTP 200，未连接生产数据库或 provider。已增加命令级回归断言并同步 runbook；生产 Deployment 的数据库连接仍来自既有 Secret。
- 修复提交 `36aba3b359ffb306fe95a6afe989a1c501fa4d3c` 与 `origin/main` 对齐后，从 clean worktree 重新执行普通 `--component all` 成功；应用代码载荷包含 `b2dd6898eb79a06a4cff00c2a14213fc0f28648c` 的统一采集适配器实现。
- 新镜像为 `localhost/a-stock-market-environment:20261008-235342-36aba3b`；远端归档 SHA-256 为 `1dd76b3807019dba42d5c25be68b364b5e4b24912867e675fa6209ddfbd6c585`，containerd manifest digest 为 `sha256:7d7a2762e274aad710257ad66224ddf782831b156a3bd56eafbf0f93cb219978`，运行 Pod imageID 为 `sha256:d0b1fefe8408ef07c45e53fec14a31902077a6638a188deefdae2c7509a8ec30`。
- Helm database/service/完整 release 收敛依次完成 revisions `85`、`86`、`87`；revision `87` 为 deployed。Deployment revision `16` 使用目标镜像并为 `1/1`，Pod `a-stock-56948cfc-v8xl8` 为 Running/Ready、0 重启；PostgreSQL StatefulSet 与 Pod 同样为 `1/1` Running/Ready、0 重启。
- 写后两个 PVC 仍为 `Bound`：PostgreSQL PVC UID `6c426fc5-10e2-4e88-b534-b258c70869c4`、PV `a-stock-postgresql-data`、`5Gi`；旧 SQLite PVC UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`、PV `a-stock-data`、`2Gi`。StatefulSet UID `272d7fa4-69a2-4608-b755-31e27ac27c66` 未变。
- 写后 `a-stock-data-collection`、legacy `market-data-collection` 和 namespace 内 Job 均 absent；Deployment 明确读回 `MARKET_ENVIRONMENT_SCRAPLING_ENABLED=0`、`MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST=[]`，Fuyao 四类数据集开关保持关闭。未调用任何采集 POST 或真实 provider。
- `http://192.168.1.20:32001/api/health` 与首页均返回 HTTP 200；provider-free `GET /api/market-environment?as_of=2026-10-08` 返回 5 个指数和真实 `asOf/generatedAt`，data-collection GET 返回已保存的 exact-date source/quality 状态，没有触发采集。
- k3s systemd 保持 `enabled/active`，节点 `ix-truenas` 为 Ready。部署脚本回归为 `52 passed`；`bash -n`、Helm strict lint/template、`git diff --check` 和 docs-contract full 均通过。

## Remaining Gaps（剩余缺口）

- 无本次部署阻断项。定时采集按授权保持 disabled/absent；后续恢复必须另建受审计划并取得独立授权。
- 本次未执行真实 provider smoke 或新采集；现有 2026-10-08 数据继续保留真实 fallback/partial/missing 质量，不因发布改写为成功。

## Next Step（下一步）

保持 revision `87`、当前不可变镜像、PVC 和调度 disabled 基线；继续通过只读接口观察应用与已有数据质量。任何调度重新激活、provider probe、Secret/PVC 变更均需独立计划和授权。
