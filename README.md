# a-stock

A 股分析与交易规则工程工作区。当前包含市场环境分析看板，以及可重复执行、可追溯、可接入 CI 的规则平台。

## 这个仓库怎么运作

- `docs/` 是事实源：规格、架构、runbook、执行计划、状态全部落在仓库里，不依赖聊天历史。
- 任何多步工作以 `docs/exec-plans/active/*.md` 起手，完成前回写 Status / 证据 / 缺口。
- 本地 gate 强制"代码改动必须伴随文档更新"：`.githooks/` + `scripts/check-docs-contract.py`。

## 快速开始

```bash
# 1. 安装本地 hooks（git config core.hooksPath .githooks）
python scripts/install-hooks.py

# 2. 手动验证文档契约
python scripts/check-docs-contract.py --mode=full
```

## 市场环境看板

安装 Python 与前端依赖后，分别启动 API 和 Vite：

```bash
python -m pip install -r requirements.txt
python -m uvicorn src.market_environment.api:app --reload --port 8001
npm install --prefix apps/market-environment-dashboard
npm run dev --prefix apps/market-environment-dashboard
```

完整 Python 依赖也包含部署文档安全测试所需的 CommonMark 与 Bash AST 解析器；只安装运行时依赖的环境不能生成该命令审计的发布证据。

打开 `http://localhost:5173` 查看上证、深证、创业板、沪深 300 和中证 500 的趋势、区间位置与成交额分析。市场广度指标暂未接入。

## TrueNAS k3s 部署

生产写操作只使用仓库的 fail-closed 入口。先从示例创建私有环境文件，至少核对目标、镜像、完整 baseline values、`SCHEDULED_COLLECTION_ENABLED=false` 和 `SCHEDULED_COLLECTION_SUSPEND=true`：

```bash
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env
```

同一入口支持按组件执行，依赖和写入顺序固定为 `postgresql -> schema migration -> service -> schedule`：

```bash
# 一键按 database -> service -> schedule 部署；无 frozen image 时 schedule 保持 disabled/absent
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all
# 只部署/校验 PostgreSQL StatefulSet、Service 和数据库 PVC；不构建或传输镜像
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component database
# 部署 Dashboard Deployment、Service 和 Ingress
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component service
# 复用已验证的 frozen image，部署 suspended CronJob
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component schedule
```

`database` 部署单主 PostgreSQL StatefulSet、内部 ClusterIP 和独立 Retain RWO PVC；必须提前创建
`database.existingSecret`，Secret 至少提供 `DATABASE_URL`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 和
`POSTGRES_DB`。Dashboard 与 CronJob 不挂载 SQLite 或 PostgreSQL PVC，运行时只通过
`MARKET_ENVIRONMENT_DATABASE_URL` 访问 PostgreSQL。旧 SQLite PVC 仅由一次性迁移 Job 只读挂载。
`service` 依赖 PostgreSQL StatefulSet/Service ready、数据库 PVC `Bound` 和可用镜像，`schedule` 还依赖已验证的 service 与
`FROZEN_IMAGE_REPOSITORY/TAG/DIGEST`；`all` 未提供 frozen image 时会记录 skipped 并保持
schedule disabled/absent。没有 Gate B/Gate C 授权时不会启动 Job；失败时按输出的组件重试目标
重跑，绝不删除 PVC。

首次部署前先创建 `database.existingSecret`，再等待 PostgreSQL StatefulSet/ClusterIP ready；Helm 的
schema migration Job 成功执行 `alembic upgrade head` 后，才 rollout Dashboard 和 suspended CronJob。
迁移旧环境时先暂停 CronJob、关闭手工写入，用迁移工具生成不可覆盖的 SQLite before-image 并校验
`quick_check`、行数、checksum 和日期覆盖；导入校验通过后切换同一 Secret。PostgreSQL 首次写入后不回切
过期 SQLite，恢复只能使用 PostgreSQL 备份或前向修复；旧 SQLite PVC 与备份继续保留作归档。

后续发布在审阅后的 clean commit 上设置新的不可变 `IMAGE_TAG`，再执行同一入口；不得直接调用 Helm write、继承 release values 或恢复历史 revision。入口必须在构建、导入或发布前确认 Helm stored manifest 与 live state 均无 application CronJob，并在成功写入后再次证明 live CronJob 仍不存在。

若只读发现显示 release 已有 active 或 suspended application CronJob，普通发布和应用回退都必须停止。先冻结并审核 exact off packet，在授权后通过受控调度入口删除 exact CronJob；只有 `--disable-schedule` 的 server-observed postcondition 成功后，才能重新执行普通发布：

```bash
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --read-only-discovery \
  --release-name a-stock --namespace a-stock
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --disable-schedule \
  --baseline-values deploy/truenas/values-secure-manual-collection.yaml \
  --scheduling-overlay deploy/truenas/values-scheduled-off.yaml \
  --kube-version <ACTUAL_KUBERNETES_VERSION> --release-name a-stock --namespace a-stock
```

应用回退不恢复历史 Helm revision。检出已审阅的回退 commit，使用新的不可变 rollback image tag 和同一普通入口重建 disabled 状态。写入、rollout 或写后读取失败时，入口必须返回非零，并将意外 active CronJob 精确补偿为 suspended 后验证 absent/suspended；无法验证时状态为 uncertain/NO-GO。失败后仍须返回审核后的 `--disable-schedule` 流程，不能直接重试普通发布。

Chart 的 Dashboard 支持 Kubernetes 1.26+，定时采集默认 `enabled=false`、`suspend=true`，无 scheduling overlay 的 render 不包含 CronJob。定时采集显式选择 `timezoneStrategy`：`native` 仅用于 Kubernetes 1.27+，会输出 `spec.timeZone: Asia/Shanghai`；k3s 1.26 只能使用经过 controller 时区证据验证的 `controller` 策略，它省略该字段，并把上海 16:30 映射为 `Etc/UTC` 的 `30 8 * * 1-5` 或 `Asia/Shanghai` 的 `30 16 * * 1-5`。CronJob 与 Dashboard 使用同一镜像和 PostgreSQL Service/Secret，均不挂载数据库 PVC，采集五类市场环境数据；只有受控 Gate B/Gate C 入口可使用 `scheduled-suspended` 或 `scheduled-active` overlay。TrueNAS 的普通发布使用完整 baseline 且不带 scheduling overlay；`deploy/k3s/` 是不含 CronJob 的 Dashboard base，原生 `spec.timeZone` CronJob 位于 `deploy/k3s-native-scheduled/`，仅可通过 `python scripts/render-k3s.py --kube-version <1.27+>` 检查渲染。无 Ingress Controller 时可改用显式 NodePort，无动态 StorageClass 时应预先创建 PostgreSQL 静态 PV/PVC 并通过数据库 values 引用。

## 交易规则平台

```bash
python -m src.trading_system.cli rules validate
python -m src.trading_system.cli rules coverage
python -m src.trading_system.cli evaluate --rule-set market-environment --snapshot tests/fixtures/trading-system/market-environment-complete.json --output .artifacts/evidence
python -m src.trading_system.cli evidence verify .artifacts/evidence
```

`trading-rules/` 是机器执行事实源，`搭建交易系统-量化版/` 是人读说明层。首期实现市场环境第 01 章 46 条规则；经验阈值不代表已经验证的收益优势。

## 下一步去哪

- 接手工作 → [docs/status.md](docs/status.md)
- 新任务流程 → [AGENTS.md](AGENTS.md)
- 仓库布局 → [docs/repository-guide.md](docs/repository-guide.md)
