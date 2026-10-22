# 部署当前 main 到 TrueNAS k3s（2026-10-22）

## Stage（阶段）

生产发布与发布后只读验证已完成。

## Status（状态）

completed-with-production-write

## Scope（范围）

- 将已审阅的 `main` 当前 commit 通过仓库受支持的 TrueNAS k3s 普通发布入口
  （`scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all`）
  部署到 `a-stock` namespace / Helm release。
- 使用 clean worktree + 精确 `REVIEWED_GIT_HEAD` 绑定，按 database → schema migration → service →
  full-release convergence 顺序发布不可变镜像。
- 保持 live values 的语义不变：单副本、`NodePort:32001`、`service/existingClaim a-stock-data`、
  PostgreSQL ClusterIP StatefulSet + Retain RWO PVC、两个既有 Secret 引用、manual refresh 与 automation
  refresh 现状、Fuyao 数据集开关现状。
- 唯一的受控 baseline 差异是 `database.migration.schemaEnabled true`，用于满足组件化合同要求的
  唯一一次 schema hook；候选 commit 未新增 Alembic revision（仍为 `0008_collection_idempotency`），
  因此 `alembic upgrade head` 是幂等 head 校验，不属于 schema 变更。
- 不调用 provider，不触发 collection，不创建或激活 Kubernetes CronJob，不删除或替换 Secret、PVC/PV，
  不使用 `helm uninstall` 或历史 revision 回滚，不修改生产数据。

## Acceptance（验收）

- 发布候选 commit 与 `origin/main` 一致，部署源 worktree 洁净且 `REVIEWED_GIT_HEAD` 精确绑定。
- 离线门禁通过：`bash -n scripts/deploy-truenas-k3s.sh`、Helm strict lint、k3s `1.26.6` 离线 render
  （database/service/all 三包）、`tests/test_deployment_manifests.py` 与
  `tests/test_truenas_scheduling_guard.py`、`check-docs-contract --mode=full`；render 不含 application CronJob。
- 只读生产预检证明节点 Ready、Dashboard/PostgreSQL `1/1`、两个 PVC Bound、当前 Helm release、
  两个历史 CronJob identity 与 namespace Job 满足 fail-closed 合同。
- 受控入口完成镜像构建、本地 smoke、传输、containerd 导入与三段 Helm 收敛；rollout 成功且唯一 Ready
  Pod 的 repo/tag/imageID 与冻结 digest 一致。
- 发布后 `/api/health`、首页与 provider-free GET 正常，不触发 provider 或生产采集。
- Secret/PVC identity、NodePort、单副本、安全上下文、manual/automation 开关与 CronJob/Job absent 不漂移。

## Completion Evidence（完成证据）

- 只读预检（2026-10-22 Asia/Shanghai）：Helm release `a-stock` revision `146` deployed，
  chart `a-stock-0.1.1`；节点 `ix-truenas` Ready，k3s `v1.26.6+k3s-6a894050-dirty`；
  `a-stock-d5b456854-d7xmj` 与 `a-stock-postgresql-0` 均 `1/1 Running`/0 重启；两个历史 CronJob 与
  namespace Job 均 absent；active run/task/lease=`0|0|0`；`http://192.168.1.20:32001/api/health` HTTP 200。
- 冻结 baseline：以 revision 146 live values 落盘
  `~/.local/share/a-stock/deploy-packets/20261022/values-baseline.yaml`（mode 600），
  SHA-256 `2476f733c757c65455fdaf1bfa6bf3d5a8a75ad89d26c39fb7180981ff21172b`，仅将
  `database.migration.schemaEnabled` 置 `true`（与 revision 144 一致）。
- 离线门禁：`bash -n` exit 0；`helm lint --strict` 0 failed；三包 render 仅含预期资源；
  `pytest tests/test_deployment_manifests.py tests/test_truenas_scheduling_guard.py` `200 passed`；
  `check-docs-contract --mode=full` 通过。
- 2026-10-22 17:26–17:48 Asia/Shanghai 使用受支持入口 `scripts/deploy-truenas-k3s.sh --component all`
  从 clean detached worktree 完成发布。候选 `REVIEWED_GIT_HEAD=16d9b3ecf81a01f66f7bd26abd4336dc56a2002e`
  与执行时 `origin/main` 一致且 worktree 洁净；镜像
  `localhost/a-stock-market-environment:20261022-172620-16d9b3e`，archive SHA-256
  `07a9ae64d43c5b6fe087aeff5c78ed6969e64543f93467859e3468a6ab91f308`，containerd manifest digest
  `sha256:9e830440183adb1d74acebcdb554b309f865c3af8be073eaf4fb1228f681e7cc`。
- Helm revisions 147（database，唯一一次 hook-enabled schema hook，`hook-complete execution=single
  namespaceJobs=absent`）/148（service，`--no-hooks`，`rollout=ready`）/149（完整清单收敛，
  `--no-hooks`）；最终 revision `149` deployed，stored manifest 的 CronJob/Job 计数为 `0`。
- Deployment `a-stock` `1/1`，Pod `a-stock-bb55cdfff-s4cmh` Ready/0 重启，运行时镜像与冻结 tag 一致；
  PostgreSQL `1/1`、0 重启；`a-stock-data`（UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`）与
  `a-stock-postgresql-data`（UID `6c426fc5-10e2-4e88-b534-b258c70869c4`）均 Bound 且 UID 未变；
  Secret `a-stock-postgresql`（`653a79bf-a881-43de-8623-2d9f69e9aa0f`）与 `a-stock-market-provider`
  （`81b9d039-7d77-44bc-9c4f-41b9ce2e19b2`）UID 未变。
- 开关不变量与预检一致：`MANUAL_REFRESH_ENABLED=1`、`AUTOMATION_REFRESH_ENABLED=1`、
  `FUYAO_CORE_ENABLED=1`/`APPROVED_REVISION=fuyao-market-v2`/`SHADOW=0`、
  `FUYAO_SECTORS_ENABLED=1`、`THS_WRITES_AUTHORIZED=1` 与六个 THS enabled/三个 revision 全部保持；
  单副本、`strategy=Recreate`、`automountServiceAccountToken=false`、`readOnlyRootFilesystem=true`、
  `NodePort:32001` 未变；schema 仍为 `0008_collection_idempotency`/`schema_migrations=8`（候选未新增
  Alembic revision，hook 为幂等 head 校验）。
- 发布后 smoke（`http://192.168.1.20:32001`）全部 HTTP 200：`/api/health`、`/`、
  `/api/market-environment/overview?date=2026-10-21`、`indices/history`、`breadth/summary`、
  `limits/history`、`breadth/history?page=1`；v2 `overview`、`breadth/summary`、`breadth/history`
  均为 200；未调用 provider、未触发 collection、未创建 CronJob。
- 环境处置：1.21 VM 的 `/run/user/1000`（591M tmpfs）被两个与本项目无关的 Trae IDE 安装包占满
  （0 字节可用），导致 crun 无法写入容器配置。未删除任何用户文件，改为在磁盘 runtime
  （`XDG_RUNTIME_DIR=/home/gyt/.cache/astock-runtime/xdg`）下运行 podman，并为 base image 配置
  daocloud 镜像；该处置仅影响本地构建环境，不改变仓库清单、镜像内容或集群契约。

## Remaining Gaps（剩余缺口）

- 无本次部署范围内缺口。业务数据采集与 Hermes 调度观察属于既有独立运行流程，本次未触发。
- 后续在 1.21 VM 复现发布时，如 `/run/user/1000` 仍被占满，需要重复上述磁盘 runtime 处置，或由
  运维清理该 tmpfs。

## Next Step（下一步）

维持常规只读健康观察；如需回滚，检出受审 rollback commit 并使用新的不可变 tag 重跑 `service` 或
`all`，不得使用 `helm uninstall`、删除 PVC 或直接恢复历史 revision。
