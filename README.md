# a-stock

A 股分析与交易规则工程工作区。当前包含市场环境分析看板，以及可重复执行、可追溯、可接入 CI 的规则平台。

## 这个仓库怎么运作

- `docs/` 是事实源：规格、架构、runbook、执行计划、状态全部落在仓库里，不依赖聊天历史。
- 任何多步工作以 `docs/exec-plans/active/*.md` 起手，完成前回写 Status / 证据 / 缺口。
- 本地 gate 强制"代码改动必须伴随文档更新"：`.githooks/` + `scripts/check-docs-contract.py`。
- 本地交易知识 MCP 只读消费交易系统文档、规则和证据摘要，索引位于被忽略的 `.artifacts/knowledge-base/`。

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

默认环境保持 requests-only。仅在离线验证可选静态 HTTP engine 时安装
`requirements-scrapling.txt`；该 profile 固定 Scrapling 版本但不执行
`scrapling install`、不下载 Chromium，也不表示任何真实 provider 已获准启用。

打开 `http://localhost:5173` 查看上证、深证、创业板、沪深 300 和中证 500 的趋势、区间位置与成交额分析。市场广度指标暂未接入。

## TrueNAS k3s 部署

生产写操作只使用仓库的 fail-closed 入口。先从示例创建私有环境文件，至少核对目标、镜像、完整 baseline values、release 和 namespace；不要把凭据提交到仓库：

```bash
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env
```

同一入口支持按组件执行，依赖和写入顺序固定为 `postgresql -> schema migration -> service`：

```bash
# 一键按 database -> service 部署
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all
# 只部署/校验 PostgreSQL StatefulSet、Service 和数据库 PVC；不构建或传输镜像
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component database
# 部署 Dashboard Deployment、Service 和 Ingress
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component service
```

`database` 部署单主 PostgreSQL StatefulSet、内部 ClusterIP 和独立 Retain RWO PVC；必须提前创建
`database.existingSecret`，Secret 至少提供 `DATABASE_URL`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 和
`POSTGRES_DB`。Dashboard 不挂载 SQLite 或 PostgreSQL PVC，运行时只通过
`MARKET_ENVIRONMENT_DATABASE_URL` 访问 PostgreSQL。旧 SQLite PVC 仅由一次性迁移 Job 只读挂载。
`service` 依赖 PostgreSQL StatefulSet/Service ready、数据库 PVC `Bound` 和可用镜像。仓库不再提供
`schedule` component、scheduling overlay、CronJob template 或 release/activate/disable 模式；失败时按输出的
组件重试目标重跑，绝不删除 PVC。

首次部署前先创建 `database.existingSecret`，再等待 PostgreSQL StatefulSet/ClusterIP ready；Helm 的
schema migration Job 成功执行 `alembic upgrade head` 后，才 rollout Dashboard。
迁移旧环境时先确认 Hermes job 已暂停、automation/manual 写入口都关闭，再用迁移工具生成不可覆盖的 SQLite before-image并校验
`quick_check`、行数、checksum 和日期覆盖；导入校验通过后切换同一 Secret。PostgreSQL 首次写入后不回切
过期 SQLite，恢复只能使用 PostgreSQL 备份或前向修复；旧 SQLite PVC 与备份继续保留作归档。

后续发布在审阅后的 clean commit 上设置新的不可变 `IMAGE_TAG`，再执行同一入口；不得直接调用 Helm write、继承 release values 或恢复历史 revision。入口必须在构建、导入或发布前确认 Helm stored manifest 与 live state 均无 application CronJob，并在成功写入后再次证明 live CronJob 仍不存在。

若只读发现显示 stored manifest 或 live cluster 中存在 release-derived `a-stock-data-collection` 或 legacy
`market-data-collection`，不论 active 或 suspended，普通发布和应用回退都必须停止：

```bash
helm get manifest a-stock --namespace a-stock
kubectl get cronjob a-stock-data-collection --namespace a-stock --ignore-not-found -o yaml
kubectl get cronjob market-data-collection --namespace a-stock --ignore-not-found -o yaml
```

入口只读取并拒绝遗留资源，不 patch、删除、接管或激活 CronJob。处置遗留资源必须另建计划、冻结 stored/live
证据并取得明确授权；处置并证明两个 identity 都 absent 后，才能重跑普通发布。应用回退不恢复历史 Helm revision，
而是用已审阅 commit、新的不可变 rollback image tag 和同一普通入口前向部署；PostgreSQL 历史、快照、幂等记录和
PVC 保持不变。

Chart 支持 Kubernetes 1.26+；所有 Helm/Kustomize profile 都只部署 PostgreSQL、migration 和 Dashboard service，
不包含 application-owned market-data CronJob，也没有 `scheduledCollection` values。盘后时钟与通知由
`192.168.1.21` 上的 Hermes Agent 持有，工作日上海时间 15:30 调用后端默认关闭的
`POST http://192.168.1.20:32001/api/market-environment/collection-runs/full`。该接口固定七数据集且要求
`Idempotency-Key`；开启后所有可路由内网客户端均可调用，幂等不是鉴权。安装、启用、停止和回滚步骤见
`docs/runbooks.md`；无 Ingress Controller 时可显式使用 NodePort，无动态 StorageClass 时应预先创建 PostgreSQL
静态 PV/PVC 并通过数据库 values 引用。

## 交易规则平台

```bash
python -m src.trading_system.cli rules validate
python -m src.trading_system.cli rules coverage
python -m src.trading_system.cli evaluate --rule-set market-environment --snapshot tests/fixtures/trading-system/market-environment-complete.json --output .artifacts/evidence
python -m src.trading_system.cli evidence verify .artifacts/evidence
```

`trading-rules/` 是机器执行事实源，`搭建交易系统-量化版/` 是人读说明层。首期实现市场环境第 01 章 46 条规则；经验阈值不代表已经验证的收益优势。

## 交易知识 MCP

```bash
python -m src.trading_knowledge.cli index build --repo-root /home/gyt/a-stock
codex mcp add trading-knowledge -- \
  /home/gyt/a-stock/.venv/bin/python -m src.trading_knowledge.mcp_server \
  --repo-root /home/gyt/a-stock
```

注册后 Codex 可调用中文检索、原文摘录、`QTS-*` 规则、证据状态和索引状态五个只读工具。源文件变化会返回 `stale`；证据不足和 `needs-backtest` 状态不会被升级为已验证结论。详细操作见 [`docs/runbooks.md`](docs/runbooks.md)。

## 下一步去哪

- 接手工作 → [docs/status.md](docs/status.md)
- 新任务流程 → [AGENTS.md](AGENTS.md)
- 仓库布局 → [docs/repository-guide.md](docs/repository-guide.md)
