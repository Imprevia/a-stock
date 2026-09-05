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

打开 `http://localhost:5173` 查看上证、深证、创业板、沪深 300 和中证 500 的趋势、区间位置与成交额分析。市场广度指标暂未接入。

## Helm 部署到 k3s

先构建镜像并推送到 k3s 节点可访问的镜像仓库：

```bash
docker build -t registry.example.com/a-stock/market-environment:2026.09.02-1 .
docker push registry.example.com/a-stock/market-environment:2026.09.02-1
```

首次安装或幂等部署：

```bash
helm upgrade --install a-stock ./deploy/helm/a-stock --namespace a-stock --create-namespace --set image.repository=registry.example.com/a-stock/market-environment --set image.tag=2026.09.02-1 --wait --timeout 3m
```

后续发布新镜像时使用新 tag，并保留上次部署参数：

```bash
docker build -t registry.example.com/a-stock/market-environment:2026.09.02-2 .
docker push registry.example.com/a-stock/market-environment:2026.09.02-2
helm upgrade a-stock ./deploy/helm/a-stock --namespace a-stock --reuse-values --set image.tag=2026.09.02-2 --wait --timeout 3m
```

查看状态和回滚：

```bash
helm status a-stock --namespace a-stock
helm history a-stock --namespace a-stock
helm rollback a-stock <revision> --namespace a-stock --wait --timeout 3m
```

Chart 支持 Kubernetes 1.26+；默认使用 k3s 1.27+ 的 Traefik 和 `local-path` StorageClass，并启用上海时区工作日 16:30 的市场数据 CronJob。CronJob 与 Dashboard 使用同一镜像和 PVC，采集五类市场环境数据；可通过 `marketEnvironment.scheduledCollection.enabled=false` 关闭，或通过 `suspend=true` 暂停。Kubernetes 1.26 必须关闭使用 `spec.timeZone` 的 CronJob；无 Ingress Controller 时可改用显式 NodePort，无动态 StorageClass 时可引用预先创建的静态 PVC。正式环境的域名、TLS、镜像拉取凭据、调度时间及其他参数通过 `deploy/helm/a-stock/values.yaml` 或独立 values 文件覆盖。

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
