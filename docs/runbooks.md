# Runbook

## 环境要求

- Python 3.11+（建议使用仓库 `.venv`）
- Node.js 18+ 与 npm
- git
- 可选：GitHub Actions（仓库 CI）
- 可访问通达信 TCP 和腾讯/百度 HTTPS 行情接口的网络
- SQLite 由 Python 标准库提供；默认快照路径为 `.artifacts/market-environment/snapshots.sqlite3`

安装依赖：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --prefix apps/market-environment-dashboard
```

## 启动命令

启动后端 API：

```bash
python -m uvicorn src.market_environment.api:app --reload --port 8001
```

启动前端开发服务器（另开终端）：

```bash
npm run dev --prefix apps/market-environment-dashboard
```

浏览器访问 `http://localhost:5173`；生产构建后可由 FastAPI 从 `apps/market-environment-dashboard/dist` 托管静态文件。

本机开发默认使用 8001，避免与常见的 CLodop 打印服务占用的 8000 端口冲突；Vite 会将 `/api` 代理到 `http://127.0.0.1:8001`。容器内 API 端口和 k3s Service 仍为 8000，不受此本机开发配置影响。

## k3s 部署

仓库根目录的 `Dockerfile` 使用 Node 构建前端，再将 `dist` 与 Python API 放入同一个非 root 运行镜像。构建并推送固定版本镜像：

```bash
docker build -t registry.example.com/a-stock/market-environment:2026.09.02 .
docker push registry.example.com/a-stock/market-environment:2026.09.02
```

将 `deploy/k3s/kustomization.yaml` 的 `images.newName` 和 `newTag` 改为集群可拉取的地址与固定版本，然后部署：

```bash
kubectl apply -k deploy/k3s
kubectl -n a-stock rollout status deployment/market-environment-dashboard --timeout=180s
kubectl -n a-stock get pods,pvc,service,ingress
```

k3s 单节点也可不使用镜像仓库，将默认名称的镜像直接导入节点。多节点集群必须导入每个可能调度 Pod 的节点，或改用共享镜像仓库：

```bash
docker build -t a-stock-market-environment:latest .
docker save a-stock-market-environment:latest | sudo k3s ctr images import -
kubectl apply -k deploy/k3s
```

默认 Ingress 使用 k3s 内置 Traefik 的 `web` 入口且不限定 Host，可通过任一节点 IP 访问；正式环境应增加域名、TLS 和证书配置。服务必须允许访问通达信 TCP 与腾讯、百度、新浪、东方财富 HTTPS 行情源。Deployment 默认单副本，因为 SQLite、refresh lease、短缓存与 provider limiter 仍是单机边界；不要直接增加副本数。

`market-environment-data` PVC 使用 k3s 默认 `local-path` StorageClass，并挂载到 `/data`；API 快照路径为 `/data/snapshots.sqlite3`。该存储适合单节点或 Pod 固定在同一 k3s 节点的部署，不提供多节点共享。删除 PVC 通常会连同 local-path 数据一起回收，执行删除前先备份 SQLite 文件。

发布检查、日志和回滚：

```bash
curl "http://<k3s-node-ip>/api/health"
kubectl -n a-stock logs deployment/market-environment-dashboard --tail=200 -f
kubectl -n a-stock describe deployment market-environment-dashboard
kubectl -n a-stock rollout history deployment/market-environment-dashboard
kubectl -n a-stock rollout undo deployment/market-environment-dashboard
```

`/api/health` 不访问外部行情源，只用于容器启动、就绪和存活检查。健康检查成功但行情接口返回 503 时，应继续按 provider 网络和降级 warning 排查，而不是重启 Pod。删除工作负载可使用 `kubectl delete -k deploy/k3s`，但该命令也会删除 PVC；需要保留快照时先移除 `persistent-volume-claim.yaml`，或先导出数据再删除。

### Helm 发布

`deploy/helm/a-stock/` 提供与原生 k3s 清单等价的参数化 Chart。首次发布：

```bash
helm upgrade --install a-stock ./deploy/helm/a-stock --namespace a-stock --create-namespace --set image.repository=registry.example.com/a-stock/market-environment --set image.tag=2026.09.02-1 --wait --timeout 3m
```

后续仅更新镜像时保留已有 values；Chart 模板或默认 values 有变化时，不要使用 `--reuse-values`，而应重新传入受版本控制的环境 values 文件：

```bash
# 仅更新镜像
helm upgrade a-stock ./deploy/helm/a-stock --namespace a-stock --reuse-values --set image.tag=2026.09.02-2 --wait --timeout 3m

# 同时应用新的 Chart 默认值和环境覆盖
helm upgrade a-stock ./deploy/helm/a-stock --namespace a-stock -f values-production.yaml --set image.tag=2026.09.02-2 --wait --timeout 3m
```

渲染和检查：

```bash
helm lint deploy/helm/a-stock
helm template a-stock deploy/helm/a-stock --namespace a-stock
helm get values a-stock --namespace a-stock
helm history a-stock --namespace a-stock
```

启用 `persistence.existingClaim` 时 Helm 不创建或删除该 PVC。Chart 创建的 PVC 默认设置 `helm.sh/resource-policy: keep`，卸载 release 后仍保留；确认无需数据后再手工删除，或显式设置 `persistence.keep=false`。原生 Kustomize 与 Helm 的 catch-all Ingress 会发生冲突，单个环境只选择一条发布路径。

### TrueNAS 1.20 + VM 1.21 一键发布

当项目已经 clone 到 1.21 的 `/home/gyt/a-stock`，可使用 `scripts/deploy-truenas-k3s.sh` 完成构建、镜像传输、containerd 导入和 Helm 发布。该脚本假设 1.21 上有 Podman、Helm、kubectl、SSH 和 SCP，且 SSH 用户在 1.20 具有无需交互密码的受控 `sudo` 权限；它不会修改 1.21 的 NGINX/Tailscale 配置。

首次配置：

```bash
cd /home/gyt/a-stock
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
```

至少修改 `TRUENAS_HOST`、`TRUENAS_SSH_USER`、`REMOTE_IMAGE_DIR`，并根据 1.20 的实际输出设置 `STORAGE_CLASS` 与 `TRUENAS_INGRESS_PORT`。`REMOTE_IMAGE_DIR` 应是 1.20 上允许该 SSH 用户写入的专用数据集目录。`INGRESS_HOST` 默认使用 `a-stock.k3s.lan`，NGINX 反代时必须发送相同的 `Host` 值。若希望脚本先更新代码，将 `GIT_UPDATE=true` 写入环境文件；脚本只接受干净工作区的 `git pull --ff-only`，也可通过 `GIT_REF` 固定到 tag 或 commit。

执行一键发布：

```bash
bash scripts/deploy-truenas-k3s.sh
```

脚本使用新 tag（时间戳 + Git SHA），本地检查 `/api/health` 和首页，生成 SHA-256 后通过 SCP 传输，在 1.20 执行 `k3s ctr --namespace k8s.io images import`，再运行 `helm upgrade --install` 并等待 Dashboard rollout。首次默认暂停盘后 CronJob；确认 PVC、外网行情出口和手工 Job 日志后，将 `SCHEDULED_COLLECTION_SUSPEND=false` 写入环境文件，再次执行脚本。

后续更新只需在 1.21 拉取代码并重新执行同一命令；如需明确指定版本，可在环境文件设置新的 `IMAGE_TAG`。脚本不使用 `kubectl port-forward` 作为长期入口，也不会删除远端镜像归档，旧 tag 可用于 Helm 回滚。

一键发布完成后，1.21 NGINX 建议新增独立 TLS 端口，例如 `8443`，反代到 1.20 的 Traefik HTTP 入口（若 Traefik 是 NodePort，使用其实际 HTTP NodePort）：

```nginx
location / {
    proxy_pass http://<1.20的IP>:<Traefik_HTTP端口>;
    proxy_set_header Host a-stock.k3s.lan;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host $host;
}
```

当前 `gyt.tail0007b1.ts.net/` 根路径已用于 multica，本项目应访问 `https://gyt.tail0007b1.ts.net:8443/` 或使用另一个独立 hostname；不要未经前端 base path 改造就直接挂载 `/a-stock/`。1.20 的 `6443` 只供 1.21 的 Helm/kubectl 管理访问，不应暴露给公网或普通 Tailnet 客户端。

前端可读性基线：全部可见文字（包括 ECharts 图例、坐标轴和 tooltip）不得小于 `14px`。修改页面样式后需检查 01 至 09 视图，并在桌面与移动宽度确认没有文字重叠、控件截断或页面级横向溢出；宽表自身的横向滚动属于预期行为。

新增或调整页面时，布局、组件、颜色、图表、状态和响应式验收遵循 `docs/product-specs/market-environment-dashboard-design-guidelines.md`。

接口检查：

```bash
curl "http://127.0.0.1:8001/api/health"
curl "http://127.0.0.1:8001/api/market-environment?as_of=2026-08-28"
curl "http://127.0.0.1:8001/api/market-environment/core?as_of=2026-08-28"
curl "http://127.0.0.1:8001/api/market-environment/chapter-01?as_of=2026-08-28&section=breadth"
curl "http://127.0.0.1:8001/api/market-environment/data-collection"
curl "http://127.0.0.1:8001/api/market-environment/data-collection?as_of=2026-08-28"
```

`/api/market-environment` 保留完整聚合响应用于兼容；网页首屏使用 `/api/market-environment/core`，该接口不访问全 A、涨跌停池和行业 provider。章节接口的 `section` 支持 `breadth`、`limits`、`sectors`、`activeDirection` 和 `summary`，其中 `summary` 用于第 08、09 页并加载全部已接入章节证据。`chapter01` 仍是向后兼容的可选扩展。`breadth`、`sectors` 和 `activeDirection` 只在请求上海时区当前日期、且其实际交易日与最新市场快照一致时读取；查询历史日期时这些当前快照型数据集返回 `missing`，不得拿今日数据回填。`limits` 使用实际交易日查询日期化涨停/跌停/炸板池。所有数据集检查 `quality.status` 和 `quality.warnings`；缺失值保持 `null`，不要在前端转换为 0。

普通市场环境 GET 优先读取精确日期的 SQLite 数据集快照或 materialized aggregate，不自动启动 provider 采集。五类数据 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 分别使用 `(dataset, as_of)` lease；失败尝试保留同日期成功值并记录 warning，一键采集中的单项失败不会阻止其他结果保存。排查加载慢时分别查看 snapshot lookup、collection lease、provider collection、aggregate validation 和 store write 计时。

盘后预计算：

```bash
python -m src.market_environment.cli snapshots refresh --as-of 2026-09-02
python -m src.market_environment.cli snapshots refresh --as-of 2026-09-02 --dataset core --dataset breadth --dataset limits --dataset sectors --dataset activeDirection
```

当前快照型 provider 默认只允许在上海时区目标市场日且达到结算时间后刷新；`--force` 仅用于显式本地诊断。命令输出每个数据集的 source、observations、duration、cache result 和 quality。单个数据集失败不会回滚其他成功数据集，也不会覆盖该日期上一次成功快照。

容量方向单项验证可运行 `python -m src.market_environment.cli snapshots refresh --as-of <上海市场当天> --dataset activeDirection --force`。采集先请求 `push2` 主域；连接/读取错误、429 或 5xx 在共享客户端有界恢复后仍失败，或主域载荷不满足契约时，再请求 `push2delay`。两个端点都必须返回至少 30 个含代码、名称和成交额的有效样本，并保持成交额非递增排序。延迟域成功时应看到 `source=eastmoney-clist-delay`、`quality.status=fallback` 和包含主域错误的 warning；两个端点都失败时只允许保留同日期旧快照。

部署内盘后定时采集：

```bash
# 本地验证调度入口；日期由 Python 按 Asia/Shanghai 解析
python -m src.market_environment.cli snapshots scheduled-refresh

# 查看 CronJob、最近 Job 和结构化日志
kubectl get cronjob,job -n a-stock
kubectl logs -n a-stock job/<job-name>

# Kustomize 部署的 CronJob 暂停与恢复
kubectl patch cronjob market-data-collection -n a-stock --type=merge -p '{"spec":{"suspend":true}}'
kubectl patch cronjob market-data-collection -n a-stock --type=merge -p '{"spec":{"suspend":false}}'

# 从现有 CronJob 创建一次性补跑；名称必须唯一
kubectl create job -n a-stock --from=cronjob/market-data-collection market-data-collection-manual-20260903
```

默认 CronJob 使用 `Asia/Shanghai` 和 `30 16 * * 1-5`，覆盖 `core`、`breadth`、`limits`、`sectors`、`activeDirection`，并设置 `concurrencyPolicy: Forbid`、`backoffLimit: 0` 和执行超时。标准 `spec.timeZone` 要求 Kubernetes/k3s 1.27 或更高版本，Helm Chart 也声明该最低版本。周末直接运行 CLI 时返回 `skipped` 且不访问 provider；结算前运行返回非零。`partial`/`failed` 也返回非零并让 Job 显示失败，但已经成功的数据集继续保存在 SQLite，CronJob 不自动整批重跑；到 `/data-collection` 只重采失败行。

Helm 通过 `marketEnvironment.scheduledCollection` 配置：`enabled=false` 不渲染 CronJob，`suspend=true` 保留资源但不创建新 Job，`schedule` 和 `timeZone` 可覆盖默认值。正式部署使用不可变 image tag，Dashboard 和 CronJob 必须解析到同一镜像版本并挂载同一 PVC。先以 suspend 部署后，可用 `kubectl create job --from=cronjob/<helm-fullname>-data-collection ...` 验证 PVC、外网和日志，再解除暂停。

第一版只用 cron 周范围排除周末，不维护交易所节假日日历。工作日节假日可能产生 failed/partial run；这是可审计的失败安全行为，任何 provider 无法证明属于当天的数据都不得落入当天快照。不要用 `--force` 或跨日期复制规避该限制。

配置：

- `MARKET_ENVIRONMENT_SNAPSHOT_PATH`：覆盖默认 SQLite 路径。
- `MARKET_ENVIRONMENT_PERSISTENT_CACHE=0`：关闭持久缓存并回退到直接 provider 路径，用于紧急回滚。
- `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`：显式关闭数据采集页面写操作和 collection POST；默认开启。对外无认证部署在接入权限边界前必须设置为 `0`。
- `MARKET_ENVIRONMENT_SETTLEMENT_TIME=15:10`：上海时区盘后结算边界；scheduled-refresh 在该时间前拒绝采集，CronJob schedule 必须晚于该值。
- SQLite 文件必须位于单机本地文件系统；多主机或网络共享目录不属于当前支持范围。

开发期手工采集 API：

```bash
curl -X POST "http://127.0.0.1:8001/api/market-environment/collection-runs" -H "Content-Type: application/json" -d '{"asOf":"2026-09-03"}'
curl "http://127.0.0.1:8001/api/market-environment/collection-runs/<run-id>"
```

POST 立即返回 `202` 和 `runId`；省略 datasets 时创建五个独立 task，传 `{"datasets":["breadth"]}` 时只采集单项。父批次允许 `partial`，每个成功 task 独立提交；失败 task 不覆盖同日期旧值。数据采集页 `/data-collection` 只通过 GET 查询本地状态，所有 provider 故障时仍应可打开。历史日期仅允许采集 provider 能验证日期的数据集；无法证明日期的最新快照型数据按钮必须禁用并由 API 返回 422。服务重启后，遗留 collecting task 在 lease 过期后可重新采集。

数据采集页首次加载调用不带 `as_of` 的状态 GET，并用响应 `asOf` 初始化日期控件；该值由后端按 `Asia/Shanghai` 计算，因此在 15:00 前也会选择上海市场当天，使 `breadth`、`sectors` 和 `activeDirection` 可按当前快照能力采集。用户手工切换日期后使用显式 `as_of`，历史限制继续生效。研究看板仍使用下述 15:00 结算日期逻辑，两者不要重新合并。

研究看板日期控件使用浏览器本地时间计算默认值：15:00 前为前一天，达到 15:00 后为当天；最大值始终为浏览器本地当天。不要改回 `new Date().toISOString().slice(0, 10)`，否则 UTC 转换可能导致日期错位。API 的默认日期与未来日期校验使用 `Asia/Shanghai`。市场广度直接从 `push2delay` 按涨跌幅排序分页定位边界与中位数，成功时 `chapter01.breadth.quality.source` 为 `eastmoney-clist-delay`、状态为 `fallback`。行业板块先请求 `push2`，连接/读取错误、429 和 5xx 有界重试后仍失败再请求 `push2delay`；403 不重试。延迟域成功时保留主域 warning，领涨股名称使用 `f128`，不得显示 `f140` 证券代码。容量方向的 Top-N 响应必须验证排序、最小样本和必需字段。任一采集失败时保留 `null` 或上一次精确日期成功值，并在 `quality.warnings` / `refreshWarning` 记录错误，不能用 0 填充。

指数 `history` 契约中的每个点应包含 `date`、`open`、`close`、`low`、`high`、`ma5`、`ma10`、`ma20`、`ma60` 和 `amount`。浏览器 QA 必须确认 60 日图存在非空 K 线实体、红涨绿跌、均线叠加和 OHLC tooltip；禁止用收盘价复制生成开高低。

指数 provider 默认拉取 280 根 K 线：mootdx `offset`、新浪 `datalen`、东方财富 `lmt`、腾讯 `param` 数量均按 280 请求，百度响应在本地最多保留 280 根。盘后显式冒烟应逐一记录五指数返回数量与冷缓存耗时；不足 280 根时不得伪造，只能按实际观测降置信。升级前已落 SQLite 的历史核心快照通常只含旧版 160 根输入，本次不回填，相关 250 日分位应保持 `insufficient-history` 或 reduced confidence。

指数卡的量价区域应先展示 `amountRatio5`，再展示可选的 `volumePriceState`。量价状态为 `null` 表示价格与成交额组合未命中任何明确规则，不是接口错误，前端不得改写为“量价平稳”；只有比值缺失时显示 `--` / “数据不足”。

每个指数的 `combination` 契约应包含 `key`、`state`、`matched`、`tone`、`evidence` 和 `tradingMode`。`chapter01.combinationOverview` 汇总 `strength`、`stage`、`capitalAcceptance`、`tradingMode`、`confidence` 和 `evidence`。浏览器 QA 必须切换至少两个指数，确认组合状态和证据同步变化；未命中状态显示“未命中明确组合”，不得补成六类中的任意一类。

`summary.syncPattern` 只记录五指数当日方向模式；`summary.synchronizationAssessment` 是独立的联合研判，返回总状态、稳定结论码、中文结论、置信度，以及 `breadth`、`trend`、`turnover` 三项确认维度。排查结论时先核对原始模式，再逐项核对上涨占比/中位数、MA20 上下方指数数和 5 日成交额比值/放量下跌数，不能只看最终文案。权重指数领涨不等于个股偏弱，普遍走弱也不自动等于系统性下降。

广度改善或恶化只比较精确上一交易日：服务从核心指数历史取得前一交易日期，再读取该日期的 `breadth` SQLite 快照。上一日记录缺失时 `previousAsOf` 与变化值保持 `null`、维度标记不足且整体置信度不高于中；不得向更早日期回退，普通 GET 的 provider 调用数必须仍为 0。需要补齐时先显式采集缺失交易日，再通过既有 collection/rebuild 路径重建目标日期聚合，不要直接修改 SQLite 或复制其他日期 payload。

第 01 页第四部分使用四问结论条、五指数乘六组合矩阵、选中行证据与盘后收束句。移动端矩阵允许组件内横向滚动，但页面本身不得横向溢出。`dataGaps` 四种 reason 必须显示差异化文案；风险相关缺失不能按安全处理。

本地门禁：

```bash
# 手动验证文档契约（快速 / 完整）
python scripts/check-docs-contract.py --mode=fast
python scripts/check-docs-contract.py --mode=full

# （重）安装本地 hooks
python scripts/install-hooks.py
```

交易规则平台离线命令：

```bash
python -m src.trading_system.cli rules validate
python -m src.trading_system.cli rules coverage
python -m src.trading_system.cli docs sync-check
python -m src.trading_system.cli evaluate --rule-set market-environment --snapshot tests/fixtures/trading-system/market-environment-complete.json --output .artifacts/evidence
python -m src.trading_system.cli evidence verify .artifacts/evidence
```

创建快照与回测：

```bash
python -m src.trading_system.cli snapshot create --as-of 2026-08-31 --output .artifacts/snapshot.json
python -m src.trading_system.cli backtest --rule-set market-environment --snapshots .artifacts/history --output .artifacts/backtest.json
```

PR 验证必须只使用 `tests/fixtures/trading-system/`，不得访问外部网络。盘后 workflow 可访问真实数据；任何 provider 失败必须写入 snapshot 的质量状态，并上传 `degraded` 或 `insufficient` 证据，不能用 0 填充缺失数据。

## 验证矩阵

| 检查 | 命令 / 方法 | 证据位置 | 必需 |
|------|-------------|----------|------|
| docs-contract | `python scripts/check-docs-contract.py --mode=full` | 终端输出 / plan 的 Completion Evidence | 是 |
| hooks 连通 | `git config core.hooksPath`（应为 `.githooks`） | 终端输出 | 是 |
| Build | `npm run build --prefix apps/market-environment-dashboard` | 终端输出 / plan | 是 |
| Backend tests | `.venv` Python 下运行 `python -m pytest tests -q` | 终端输出 / plan | 是 |
| k3s manifests | `kubectl kustomize deploy/k3s` 与集群端 `kubectl apply --dry-run=server -k deploy/k3s` | 终端输出 / plan | 是 |
| Helm chart | `helm lint deploy/helm/a-stock` 与 `helm template a-stock deploy/helm/a-stock --namespace a-stock` | 终端输出 / plan | 是 |
| Snapshot refresh | `python -m src.market_environment.cli snapshots refresh --as-of <date>` | CLI JSON / plan | 是 |
| Collection management | 启用开发开关后验证状态 GET、单项 POST、全部 POST、轮询和 partial 结果 | pytest / 浏览器 / plan | 是 |
| Scheduled collection | scheduled-refresh success/partial/skipped、`kubectl kustomize`、Helm enabled/disabled/suspended 渲染 | pytest / CLI JSON / plan | 是 |
| Warm cache | 对已预计算日期请求 Chapter 01，确认 provider 0 调用且 <500ms | pytest / plan | 是 |
| Frontend build | `npm run build --prefix apps/market-environment-dashboard` | 终端输出 / plan | 是 |
| Browser QA | 启动前后端后检查 01 至 09 视图的桌面与移动宽度、最小 `14px` 字号和溢出；01 页检查真实 OHLC K 线、均线和 tooltip；确认首屏先于章节数据出现、章节失败不清空核心数据 | 截图 / plan | 是 |
| Rule registry | `python -m src.trading_system.cli rules validate` | 终端输出 / PR workflow | 是 |
| Rule coverage | `python -m src.trading_system.cli rules coverage` | `trading-rules/coverage.yaml` / PR workflow | 是 |
| Deterministic replay | 固定 fixture 执行两次并比较 canonical result | pytest / golden fixture | 是 |
| Evidence verification | `python -m src.trading_system.cli evidence verify <bundle>` | manifest / CI Artifact | 是 |

## 常见调试路径

- **pre-commit / pre-push 未触发**：`git config core.hooksPath` 是否为 `.githooks`；不是则跑 `python scripts/install-hooks.py`。
- **API 返回 503**：先检查 `/api/health`，再查看服务日志中的各指数数据源错误；mootdx 失败时应看到百度或腾讯降级 warning。
- **核心接口冷启动仍较慢**：分别计时 `/api/market-environment/core` 与章节接口。若核心接口慢且 warning 显示通达信不可用，当前实现仍会为五个指数串行执行既定降级链；不要通过跳过价格交叉校验换速度，后续应以独立熔断或线程安全并发方案处理。
- **成交额比值显示 `--`**：腾讯历史 K 线公共接口可能只提供成交量而无成交额；服务会先尝试新浪指数 K 线（用腾讯实时成交额校准），再尝试东方财富显式指数 K 线，最后降级到腾讯。若所有历史成交额源均不可用，保留 `--`，不要把缺失成交额当成 0。
- **有 5 日成交额比值但没有量价状态**：该日价格变化与比值处于已定义规则之间的空档，属于预期的未分类状态；不要在 API 或前端增加兜底分类。
- **组合判断显示“未命中明确组合”**：先核对 API 的 `combination.evidence` 和量化版 `0.2` 映射。六类条件要求同时成立，单独处于高位、放量或站上均线都不足以形成组合状态。
- **同步模式与最终结论不同**：这是两阶段模型的预期行为。`syncPattern` 记录指数方向，`synchronizationAssessment.status` 说明广度、趋势和成交额是否确认；查看 `dimensions` 中的实际值和 reason，不要改写原始模式。
- **同步上涨但显示“反驳”**：检查上涨占比是否不高于 45% 且中位数小于 0；这代表指数上涨没有得到多数个股确认，不应改成全面强势。
- **普遍走弱但未显示系统性下降**：必须同时满足弱广度、至少三个指数位于 MA20 下方和至少三个指数放量下跌。缺少或未命中任一维度时只保留普遍走弱风险提示。
- **上一交易日广度为不足**：从指数 history 确认 `previousAsOf`，再检查 SQLite 是否存在该精确日期的 `breadth` 成功快照；更早快照不会被采用，GET 也不会自动联网补采。
- **第 01 章证据显示 `missing` / `partial`**：先看对应对象的 `quality.warnings`。历史日期缺少广度、板块或成交额榜是当前快照源的预期边界；东方财富 403 或空 `data` 也必须保留缺失状态，不能用空数组伪造为 0。只有接口成功且明确返回空 `pool` 时，涨跌停计数才可为 0。
- **章节显示 `cacheState=stale`**：查看 `snapshotFetchedAt` 和 `refreshWarning`；旧值仍对应同一交易日，但后台刷新失败或尚在进行。不要删除旧快照后用其他日期数据替代。
- **refresh 一直显示被占用**：检查同 dataset/date 的 lease；正常 lease 会在有界时间后过期。仅在确认没有刷新进程后使用 CLI 强制重试，不要直接修改 SQLite。
- **数据采集批次显示 `partial`**：查看每个 task 的 warning；成功 task 已独立保存，只对失败行执行重新采集，不要删除整批成功快照。
- **最近采集失败但数据仍可用**：这是 `failed-retained`，页面继续服务同日期最后成功值并展示刷新错误；只有 `failed-missing` 才表示该日期没有可用数据。
- **数据采集按钮不可用**：检查 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 是否被显式设为 `0`，并检查所选日期和 provider 日期能力；不要用强制参数把最新快照写成历史日期。
- **CronJob 没有启动**：检查资源是否被 Helm `enabled=false` 省略、`spec.suspend`、schedule/timeZone、`startingDeadlineSeconds` 和控制器事件；先用 `kubectl create job --from=cronjob/...` 验证命令与 PVC。
- **CronJob 为 Failed 但页面有部分数据**：检查容器 JSON 中的父状态和各 task warning；`partial` 有意返回非零且不自动整批重试，成功兄弟任务已经落盘，只补采失败行。
- **CronJob 卡住或错过下一次运行**：查看 `activeDeadlineSeconds`、Pod 外网访问和 PVC 挂载；`concurrencyPolicy: Forbid` 会跳过重叠触发，确认旧 Job 结束后再补跑一次性 Job。
- **节假日出现 failed/partial**：第一版预期会在周一至周五节假日触发；确认没有跨日期 snapshot 后保留审计记录，不要伪造当天成功。
- **行业板块采集偶发 `RemoteDisconnected`**：确认请求经过共享串行门；主域会先执行有限连接重试，再降级到 `push2delay`。若两个域都失败，查看 task warning 和同日期 snapshot 是否触发 `failed-retained`，不要删除旧值或跨日期回填。
- **容量方向采集为 `failed-missing`**：先检查 warning 是否为 `push2` 主域断连，并确认实现已继续请求 `push2delay`。延迟域成功应记录 `eastmoney-clist-delay` / `fallback`；若延迟域少于 30 个有效样本、缺少代码/名称/成交额或排序异常，必须继续视为失败。存在同日期成功值时应为 `failed-retained`，不要用其他日期或零值替代。
- **需要紧急回滚持久缓存**：设置 `MARKET_ENVIRONMENT_PERSISTENT_CACHE=0` 并重启 API；原 SQLite 文件保留用于诊断，不需要删除。
- **指数价格异常**：检查实时腾讯报价是否可用。沪市歧义代码没有实时交叉校验时，mootdx/百度结果会被拒绝，避免错误股票数据进入页面。
- **hook 报 `\r` 相关错误**：`.githooks/*` 行尾被改为 CRLF，恢复 LF（`.gitattributes` 已强制 `eol=lf`，重新 checkout 即可）。
- **gate 误报需要紧急绕过**：优先修文档；确需绕过用 commit message 标记（`[skip-plan]` / `[no-docs]` + 理由）或环境变量（见 `AGENTS.md` 逃生口）。
- **规则加载失败**：先运行 `rules validate`；重复 ID、未知字段、未知 evaluator、阈值无来源或非法生命周期都会在执行前失败。
- **盘后证据显示 degraded/insufficient**：检查 manifest 的 provider 状态和 warnings。东方财富 403 不应循环重试；切换到降级源或等待下一次运行。
- **证据校验失败**：不要手改证据文件。重新从原 snapshot、规则版本和 Git SHA 执行；manifest 中任一 SHA-256 不一致都视为证据失效。

## 运维控制

- hook 逃生开关：`SKIP_DOCS_CONTRACT=1`（仅应急，须在 plan 或 commit message 记录原因）。

## 看板图表空白排障

- 第 01 章出现有高度但无内容的价格或成交额图表时，先确认 `GET /api/market-environment/core?as_of=<date>` 返回 `indices[*].history`，且每个指数至少有一条历史记录。
- 若 API 数据完整，检查浏览器页面是否刚结束“正在读取本节证据”状态。图表容器会随该加载态被替换，前端应在加载开始时释放旧实例，并在加载结束后的下一轮 DOM 更新中重新初始化 ECharts。
- 浏览器验收应确认 `.price-chart canvas` 和 `.volume-chart canvas` 均存在，容器尺寸非零，且截图中同时可见 K 线、均线和成交额柱状图；仅看到空白容器不算通过。

## 失败解读指引

gate 输出的每条错误消息都自带修复指引（对应 `AGENTS.md` 硬规则编号语义）。修改 `scripts/check-docs-contract.py` 的消息文案时必须同步 `AGENTS.md`。
