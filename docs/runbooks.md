# Runbook

## 下一交易日对照与多页看板（2026-09-14）

`GET /api/market-environment/next-session?as_of=YYYY-MM-DD` 只读本地精确交易日证据。排查时先确认 `trading_sessions` 存在严格大于请求日期的下一真实交易日，再检查该日核心指数和 materialized aggregate；缺失应保持 `pending`/`insufficient` 并记录 warning。该请求不得调用 provider、不得用自然日加一、不得回退旧日期。页面 01 和 09 共用该接口，普通研究页仍不承担采集职责。

复盘句式为临时展示与复制内容，不写入 PostgreSQL；不要添加保存按钮、复盘记录表或 20 日训练进度状态。03、04、07 的未接入证据继续显示真实 `unverified`/`insufficient`。

## 环境要求

- Python 3.11+（建议使用仓库 `.venv`）
- Node.js 18+ 与 npm
- git
- 可选：GitHub Actions（仓库 CI）
- 可访问通达信 TCP 和腾讯/百度 HTTPS 行情接口的网络
- 运行时数据库为 PostgreSQL（SQLAlchemy 2 + psycopg 3）；开发/生产必须设置 `MARKET_ENVIRONMENT_DATABASE_URL`。SQLite 仅供一次性导入工具使用，迁移输入可放在 `.artifacts/market-environment/snapshots.sqlite3`

安装依赖：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --prefix apps/market-environment-dashboard
```

`requirements.txt` 同时安装部署文档安全测试使用的 CommonMark 与 Bash AST 解析器；不要在只安装部分依赖的环境中把命令审计结果作为发布证据。

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

将 `deploy/k3s/kustomization.yaml` 的 `images.newName` 和 `newTag` 改为集群可拉取的地址与固定版本，然后部署 Dashboard 基础资源；该 base 不包含 CronJob：

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

默认 Ingress 使用 k3s 内置 Traefik 的 `web` 入口且不限定 Host，可通过任一节点 IP 访问；正式环境应增加域名、TLS 和证书配置。服务必须允许访问通达信 TCP 与腾讯、百度、新浪、东方财富 HTTPS 行情源。Deployment 默认单副本，因为当前 PostgreSQL 为单主、refresh lease/事务 fencing 与 provider limiter 仍是有界单主边界；不要直接增加副本数。

PostgreSQL StatefulSet 独占 `a-stock-postgresql-data` Retain RWO PVC（默认挂载 `/var/lib/postgresql/data`）；Dashboard Deployment 与 CronJob 不挂载任何数据库 PVC。删除数据库 PVC 会破坏运行时状态，执行任何存储操作前必须完成 PostgreSQL 逻辑备份/物理备份并记录 PVC UID；旧 SQLite PVC 只能由迁移 Job 只读挂载并保持归档。

发布检查、日志和回滚：

```bash
curl "http://<k3s-node-ip>/api/health"
kubectl -n a-stock logs deployment/market-environment-dashboard --tail=200 -f
kubectl -n a-stock describe deployment market-environment-dashboard
kubectl -n a-stock rollout history deployment/market-environment-dashboard
kubectl -n a-stock rollout undo deployment/market-environment-dashboard
```

`/api/health` 不访问外部行情源，只用于容器启动、就绪和存活检查。健康检查成功但行情接口返回 503 时，应继续按 provider 网络和降级 warning 排查，而不是重启 Pod。不要用 `kubectl delete -k deploy/k3s` 作为回滚；它可能移除应用资源且不负责数据库恢复。回滚应用应使用相同 release 的 atomic upgrade/受审 rollback image，PostgreSQL 数据通过备份恢复或前向修复处理，禁止删除 PVC。

### 生产定时任务契约（fail-closed 默认）

Helm `a-stock` 默认 `scheduledCollection.enabled=false / suspend=true`：Chart 在该默认下不渲染 CronJob 资源，`scheduledCollection.suspend=true` 在显式启用时保留资源但不创建新 Job。`scripts/deploy-truenas-k3s.sh` 的通用 install/upgrade/application-rollback 入口在首次 Helm render、image 工作、SSH 或目标 API 访问前，会强制 typed values 等于 `enabled=false / suspend=true`；任何偏离（含 `enabled=true` 但 `suspend=false`、空字符串布尔值、`false/false` 等其它组合）都会让入口 `die` 阻断所有后续写入，不会留下 active 或 identity-drifted 的 CronJob。`scheduled-off` / `scheduled-suspended` / `scheduled-active` 三个 overlay 未应用额外覆盖时同样保持 `enabled=false / suspend=true` 默认值。生产激活、回退或停止 CronJob 必须通过专用入口（`--release-suspended` / `--activate-schedule` / `--disable-schedule`），禁止裸 `kubectl apply`/`helm install|upgrade`/`kubectl patch`/`kubectl edit` 直接改动 CronJob 资源；任何绕过入口的写入都视为偏离契约并需立即回退。运维与排错请以本契约为准：

- `deploy/helm/a-stock/values.yaml`、`deploy/truenas/values-secure-manual-collection.yaml` 以及 `scheduled-off` / `scheduled-suspended` / `scheduled-active` 三个 overlay，未应用额外覆盖时均为 `scheduledCollection.enabled=false / suspend=true`；`market-data-collection-cronjob.yaml` 模板在该默认值下根本不会渲染 CronJob 资源。
- `scripts/deploy-truenas-k3s.sh` 的通用 install / upgrade / application-rollback 入口在首次 Helm render、image 工作、SSH 或目标 API 访问前，会强制 typed values 等于 `enabled=false / suspend=true`；任何偏离（包括 `enabled=true` 但 `suspend=false`、或空字符串布尔值）都会让入口 `die` 并阻断所有后续写入，不会留下 active 或 identity-drifted 的 CronJob。

- 排错动作顺序：先用 `helm get manifest <release> -n <namespace>`、`helm get values <release> -n <namespace>` 与 `kubectl get cronjob -n <namespace>` 核对 Helm stored manifest 和 live exact CronJob。合并所有权后的 release-derived `a-stock-data-collection` 必须带 Helm release metadata；若发现非 Helm-owned legacy `market-data-collection`，停止发布并按本节的迁移步骤处理，不得让两个 owner 并存。

### Helm Chart 与受控发布入口

`deploy/helm/a-stock/` 提供与原生 k3s 清单等价的参数化 Chart，但生产写操作不直接调用 Helm。TrueNAS 上唯一受支持的通用 install/upgrade/application rollback 入口是 `scripts/deploy-truenas-k3s.sh`；仓库没有通用 uninstall 入口，退役必须另建受审 exact-resource 操作包。先从 `deploy/truenas/deploy.env.example` 创建私有环境文件，核对完整 baseline values 和 disabled/suspended 调度状态后执行：

```bash
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env
```

Chart 可安装在 Kubernetes 1.26+。盘后 CronJob 的 native `spec.timeZone` 要求 Kubernetes 1.27+；1.26 只能在单 controller 的时区证据、固定上海 16:30 映射和后续授权 canary 均已验证时，使用 Helm `controller` strategy 省略该字段。没有 Ingress Controller 时可设置 `ingress.enabled=false`、`service.type=NodePort` 和 `service.nodePort=<未占用端口>`。没有动态 StorageClass 时，应由运维人员先创建绑定到受控节点目录的静态 PV/PVC，再通过 `persistence.existingClaim` 引用；目录需允许容器的 UID/GID 10001 写入。

TrueNAS 直连部署使用受版本控制的 `deploy/truenas/values-secure-manual-collection.yaml`：固定 `NodePort:32001`、关闭 Ingress/CronJob，并仅保留一个 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`。该 values 必须引用部署前创建的 `database.existingSecret`（至少 `DATABASE_URL`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`）；Dashboard 只通过 PostgreSQL ClusterIP Service 访问数据库，不挂载 SQLite 或 PostgreSQL PVC。匿名 NodePort 写入口是负责人显式接受的例外；任何能路由到节点端口的客户端都能触发 provider 调用和 PostgreSQL 写入。NodePort 不提供身份认证、客户端授权或子网隔离，禁止公网端口映射，发布前必须核对数据库 Secret、PostgreSQL claim、镜像 tag、集群版本和实际网络边界。

普通入口在首次 Helm render、构建、镜像传输/导入、SSH 或目标 API 访问前，对 chart defaults 与调用方 baseline 做 typed 深合并校验；最终调度值必须同时为 `enabled=false`、`suspend=true`，`false/false`、字符串布尔值和其他组合一律 fail closed。随后才把 chart、调用方 values 和 overlay 复制到本次运行的只读 packet，并在 packet 首次 render 前重复同一校验。入口从 packet render 解析 release-derived exact CronJob 名称，并按该名称读取 live state，不使用可能因 label drift 漏报资源的 selector。任何构建、镜像传输/导入或 release write 前，必须同时证明 Helm stored manifest 与 exact live CronJob 均 absent；普通部署不得带 scheduling overlay。最终 values 验证后记录 disabled render hash，Helm write 前从同一只读 packet 重渲染并比对，实际 Helm 调用也只读取该 packet。成功写入后必须重新读取 exact server-observed 状态并证明 CronJob 仍不存在。不得继承目标上的历史值、恢复历史 revision、执行原始 uninstall 或绕过入口直接执行 Helm write。

TrueNAS 的调度组件与 Dashboard 统一归属 Helm release `a-stock`。普通组件发布的 preflight、镜像工作前、Helm write 前和写后仍需核对 release-derived exact `a-stock-data-collection` 以及 legacy `market-data-collection` absent；schedule-only 操作只能通过 `--release-suspended` / `--activate-schedule` / `--disable-schedule` 三个专用入口。不得恢复独立 operator override 或使用裸 `kubectl apply` 创建同名 CronJob。

如果只读发现显示已有 active 或 suspended application CronJob，普通应用发布和回退必须停止。先用实际版本冻结 baseline + off overlay 和 hashes，取得 rollback-only exact authorization，并设置 `SCHEDULE_ROLLBACK_AUTHORIZATION_REF=rollback-v1:<approval-id>:<binding-sha256>`。其中 digest 是下列 UTF-8、逐行 LF 结尾且保持顺序的 canonical payload 的 SHA-256；入口会在 SSH、目标 API 访问或 release mutation 前重算比较。该引用是 rollback-only 的独立 namespace：

```text
schema=rollback-v1
operation=--disable-schedule
release=<RELEASE_NAME>
namespace=<NAMESPACE>
kubernetesVersion=<normalized TARGET_KUBERNETES_VERSION>
reviewedHead=<REVIEWED_GIT_HEAD>
chartSha256=<REVIEWED_CHART_SHA256>
baselineSha256=<REVIEWED_BASELINE_SHA256>
overlaySha256=<REVIEWED_OVERLAY_SHA256>
renderSha256=<REVIEWED_RENDER_SHA256>
```

随后执行受审的调度关闭入口：

```bash
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --disable-schedule \
  --baseline-values deploy/truenas/values-secure-manual-collection.yaml \
  --scheduling-overlay deploy/truenas/values-scheduled-off.yaml \
  --kube-version <ACTUAL_KUBERNETES_VERSION> --release-name a-stock --namespace a-stock
```

只有该命令的 server-observed postcondition 证明 exact CronJob 已删除后，才能重新运行普通入口。instance label 缺失或漂移不是“资源不存在”的证据：normal validation 仍会 fail closed，但 active-to-off 的应急补偿按 release-derived exact API name 工作，不让 label 或非安全关键 shape drift 阻止暂停。任何 write、rollout 或写后状态读取失败都不得报告成功；应急检查把 existing resource 中任何非 typed `spec.suspend=true` 状态视为需补偿，至多一次精确 patch，再按同名读回只接受 absent 或 typed suspended。无法读取、补偿或证明时保持 uncertain/NO-GO；即使紧急暂停成功，下一次普通发布前仍必须先完成同一个受审 `--disable-schedule` 流程。

渲染和检查：

```bash
helm lint deploy/helm/a-stock
helm template a-stock deploy/helm/a-stock --namespace a-stock --set marketEnvironment.scheduledCollection.enabled=false --set marketEnvironment.scheduledCollection.suspend=true
helm get values a-stock --namespace a-stock
helm history a-stock --namespace a-stock
```

启用 `persistence.existingClaim` 时 Helm 不创建或删除该 PVC。Chart 创建的 PVC 默认设置 `helm.sh/resource-policy: keep`，但 keep policy 不能把原始 uninstall 变成受支持操作；退役必须先冻结 release、CronJob、PVC/PV 和恢复证据。Chart 的 Dashboard 支持 Kubernetes 1.26+，但 CronJob timezone 需显式选择：`native` 仅支持 1.27+ 并输出 `spec.timeZone: Asia/Shanghai`；1.26 只能选 `controller`，省略该字段并要求已验证的 `Etc/UTC` 或 `Asia/Shanghai` controller timezone 和精确 16:30 上海映射。`deploy/k3s/` base 只渲染 Dashboard；native CronJob 位于同级 `deploy/k3s-native-scheduled/`，只允许通过 `python scripts/render-k3s.py --kube-version <actual-version>` 检查渲染，1.26 会在启动 kubectl 前失败。原生 Kustomize 与 Helm 的 catch-all Ingress 会发生冲突，单个环境只选择一条发布路径。

### TrueNAS 1.20 + VM 1.21 一键发布

TrueNAS 节点的 k3s 服务需要启用 systemd 开机自启；部署前确认并在维护窗口执行：

```bash
ssh admin@<truenas-host> 'sudo systemctl enable k3s'
ssh admin@<truenas-host> 'systemctl is-enabled k3s && systemctl is-active k3s'
```

若节点显示 `NotReady` 且原因为 `NetworkPluginNotReady: cni plugin not initialized`，不要继续
发布或重试 Helm rollout；先恢复 TrueNAS 管理的 CNI/Multus 清单和网络服务，再重新执行部署。

当项目已经 clone 到 1.21 的 `/home/gyt/a-stock`，可使用 `scripts/deploy-truenas-k3s.sh` 完成构建、镜像传输、containerd 导入和 Helm 发布。该脚本假设 1.21 上有 Podman、Helm、kubectl、SSH、SCP 和 netcat，且 SSH 用户在 1.20 具有无需交互密码的受控 `sudo` 权限；它不会修改 1.21 的 NGINX/Tailscale 配置。默认 `K3S_API_SSH_TUNNEL=true`，脚本把临时 kubeconfig 指向 1.21 回环端口，并经 SSH 转发到 TrueNAS `127.0.0.1:6443`；SSH 服务必须允许该目标的 TCP forwarding。脚本退出时自动关闭隧道，不要求也不建议向局域网开放 `6443/tcp`。

首次配置：

```bash
cd /home/gyt/a-stock
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
```

至少修改 `TRUENAS_HOST`、`TRUENAS_SSH_USER`、`REMOTE_IMAGE_DIR`，并根据 1.20 的实际输出设置 `TRUENAS_INGRESS_PORT`。动态存储与 Traefik 环境可设置 `STORAGE_CLASS`、`INGRESS_CLASS`；TrueNAS 24.04 无 StorageClass/IngressClass 的静态 PVC 环境使用 `deploy/truenas/values-secure-manual-collection.yaml` 作为 baseline。普通发布不得叠加 scheduling overlay；`values-scheduled-suspended.yaml`、`values-scheduled-active.yaml` 和 `values-scheduled-off.yaml` 只允许由对应的受控调度模式在精确授权下使用。`REMOTE_IMAGE_DIR` 应是 1.20 上允许该 SSH 用户写入的专用数据集目录。`INGRESS_HOST` 默认使用 `a-stock.k3s.lan`，NGINX 反代时必须发送相同的 `Host` 值。若本机 `K3S_API_LOCAL_PORT` 已占用，应换成其他 1024–65535 端口；只有在 TrueNAS 已将 6443 精确放行给管理机时才设置 `K3S_API_SSH_TUNNEL=false`。仓库更新必须作为独立前置步骤完成并重新审阅；部署脚本固定拒绝 `GIT_UPDATE=true`，不会在校验与发布之间 fetch、checkout 或 pull。

执行一键发布：

```bash
bash scripts/deploy-truenas-k3s.sh
```

#### 组件化部署（TrueNAS k3s）

同一 Helm release 支持一键和分项操作，组件依赖固定为：

```text
postgresql（namespace + existingSecret + PostgreSQL StatefulSet/PVC/Service） -> schema migration（Alembic Job） -> service（Deployment/Service/Ingress） -> schedule（suspended CronJob）
```

使用前确认 `deploy/truenas/deploy.env` 已设置 `TRUENAS_HOST`、`TRUENAS_SSH_USER`、
`REMOTE_IMAGE_DIR`（仅 `all`/`service` 需要）、`NAMESPACE`、`RELEASE_NAME`，并提供完整
baseline values 及预先创建的 `database.existingSecret`。PostgreSQL 数据使用独立 Retain RWO
claim；旧 SQLite claim 仅作为迁移输入保留。不要让 Dashboard/CronJob 挂载旧 claim，也不要在
组件操作中删除、替换、扩容或重新绑定 PostgreSQL claim。

```bash
# 一键：database -> service -> schedule；无 frozen image 时 schedule 保持 disabled/absent
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all
# 只处理存储契约；existingClaim 只读验证，chart-managed PVC 才允许首次创建
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component database
# 只更新 Dashboard 服务；会复用不可变镜像并等待单副本 rollout
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component service
# 只处理调度层；必须提供此前审核通过的 frozen image 三元组
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component schedule
```

`service` 在写入前必须观察到 namespace、PostgreSQL StatefulSet/Service 就绪、数据库 PVC
为 `Bound` 和目标镜像；`schedule` 还必须观察到 service 就绪以及目标运行时中与 frozen digest
相符的镜像。任一依赖失败都在
后续写入前返回非零。`all` 按上述顺序逐组件执行，输出每个组件的 `completed`/`failed`
状态和唯一重试目标；前一组件成功后即使后一组件失败，也保留 PVC 和已成功资源。

调度组件默认只创建或校验 `spec.suspend: true` 的 CronJob（或按 baseline 保持 absent），
不会因 `--component schedule` 自动激活生产采集。生产激活仍只能使用已审阅的
`--release-suspended`、`--activate-schedule` 与独立 rollback 授权；禁止直接 `kubectl apply`
或直接修改 `spec.suspend` 绕过受控入口。

回滚时先按 exact-resource 流程执行 `--disable-schedule`，确认 CronJob 已 absent/suspended，
再重跑失败的 `service` 或 `all` 组件。不要执行 `helm uninstall`、`kubectl delete pvc` 或
任何隐式 resize。迁移前恢复 SQLite 时才使用 `sqlite3.Connection.backup()` 导出副本；运行时
数据库恢复必须使用 PostgreSQL 备份/恢复工具，并保留 PostgreSQL PVC UID、PV、容量、备份
校验和及恢复时间线。

普通应用发布脚本可使用新 tag（时间戳 + Git SHA），本地检查 `/api/health` 和首页，生成 SHA-256 后通过 SCP 传输，在 1.20 执行 `k3s ctr --namespace k8s.io images import`，再由脚本完成 release write 并等待 Dashboard rollout。普通模式会冻结已验证的 chart/values，按 release-derived exact name 在所有构建/目标写操作前验证 stored/live scheduling 已为 off/absent，在 Helm write 前重验 live state 与 frozen render hash，并在写后验证同一 postcondition。调度发布不通过这条普通构建/导入路径：它必须使用 clean、无 drift 的已审阅 HEAD 和冻结镜像，先以 baseline 加唯一 overlay 离线 render。只读 discovery、exact suspended-CronJob server-side dry-run、suspended release 与 `--activate-schedule` 是分离模式；任何网络、构建或写操作前都必须校验最终合并后的 typed Helm values，激活前还必须证明候选相对已审阅 suspended release 只改变 `/spec/suspend`。入口不会自动创建 canary/Job。

后续更新只需在 1.21 检出审阅后的 clean commit 并重新执行同一命令；如需明确指定版本，可在环境文件设置新的唯一 `IMAGE_TAG`。脚本不使用 `kubectl port-forward` 作为长期入口，也不会删除远端镜像归档。应用回退检出受审 rollback commit，并使用新的不可变 rollback tag 运行同一普通入口；不直接恢复历史 Helm revision。若 release 中存在 active/suspended schedule，必须先按上文完成受审 `--disable-schedule`。

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

当前 `gyt.tail0007b1.ts.net/` 根路径已用于 multica，本项目应访问 `https://gyt.tail0007b1.ts.net:8443/` 或使用另一个独立 hostname；不要未经前端 base path 改造就直接挂载 `/a-stock/`。1.20 的 `6443` 只供集群本机访问；1.21 的 Helm/kubectl 默认经临时 SSH 回环隧道管理，不应把该端口暴露给局域网、公网或普通 Tailnet 客户端。

### TrueNAS NodePort 手工采集

问题报告为当前线上 Helm revision 7，但该值必须在后续只读 preflight 中与完整 values、镜像 digest、PostgreSQL PVC UID 和 controller timezone 一起确认；此前 revision 4/6 的文字不能替代 live evidence。仓库候选只允许将 Dashboard Service 改为 `NodePort:32001`；镜像、单副本、PostgreSQL StatefulSet/Service、数据库 Secret、安全上下文、关闭的 Ingress/CronJob 均不得改变。

离线检查候选：

```bash
helm lint --strict deploy/helm/a-stock
helm template a-stock deploy/helm/a-stock --namespace a-stock \
  --kube-version 1.26.6 -f deploy/truenas/values-secure-manual-collection.yaml
```

获准发布前，确认节点/集群没有占用 `32001`，并保存 Helm history、获现场确认的当前 revision（问题报告为 7）、完整 values、Service、Deployment、Endpoint/EndpointSlice、运行镜像、Pod 安全上下文、PVC 名称/UID/PV/容量/使用量以及 Ingress/CronJob 状态。检查节点和路由器/防火墙不存在公网映射；没有 ACL 证据时只能把边界描述为“所有可路由网络”。

发布前对 PostgreSQL 执行 `pg_dump --format=custom`（必要时配合受控物理备份），记录数据库 Service、PVC UID/PV、备份路径、SHA-256、schema 版本和恢复演练结果；旧 SQLite before-image 仅在迁移窗口按 `sqlite3.Connection.backup()` 创建。对现场捕获的当前 values 与候选执行 Helm diff，任何 PostgreSQL PVC 删除/替换、Secret 漂移或不变量变化都必须停止发布。

发布只能在单独批准的维护窗口执行一次 Helm upgrade 并等待 PostgreSQL StatefulSet ready、schema migration Job 成功及单个 Dashboard Deployment ready。随后从预期 LAN 客户端验证 `/api/health`、`/data-collection` 和 provider-free 状态 GET，再提交一次上海市场当天的受支持数据集并验证 202 和合法终态；历史不支持请求仍须返回 422。观察 collection run/task、provider warning/限流、PostgreSQL lock/连接池、任务时长与数据库 PVC 增长，并记录实际可达边界和最终 revision。

若出现异常请求、provider 压力、PostgreSQL 锁等待或数据库 PVC 增长，第一步使用审阅后的 values 将 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`，验证 POST 返回 403 且没有 provider 工作，同时保留 NodePort 健康与 provider-free 快照读取。第二步从现场捕获的 pre-release chart、完整 values 与不可变镜像 tag 执行新的 atomic upgrade，并显式保持 scheduled collection disabled/suspended；不得恢复含未知 values 的历史 revision、uninstall release 或删除/替换 PVC。恢复后复核镜像、副本、安全上下文、PostgreSQL PVC UID、Secret 引用、schema 版本和历史读取。

前端可读性基线：全部可见文字（包括 ECharts 图例、坐标轴和 tooltip）不得小于 `14px`。修改页面样式后需检查 01 至 09 视图，并在桌面与移动宽度确认没有文字重叠、控件截断或页面级横向溢出；宽表自身的横向滚动属于预期行为。

前端时间显示由 `src/timezone.ts` 统一处理，禁止组件自行调用 `Intl.DateTimeFormat` 或 `toLocaleString` 渲染 ISO 时间。`/data-collection` 的“最近尝试”属于市场运行审计字段，固定按 `Asia/Shanghai` 显示，避免部署浏览器使用 UTC 时把盘后采集时间显示成非北京时间；其他页面时间继续按生效时区展示。`/settings` 的日期与时间页通过可选 `GET/PUT /api/preferences/timezone` 读取/保存个人和工作区 IANA 偏好；后端未部署时个人偏好使用浏览器 localStorage fallback，并在页面提示“接口尚未接入/离线”，不伪造工作区保存成功。验证时间层和设置状态：

```bash
npm run test --prefix apps/market-environment-dashboard
npm run build --prefix apps/market-environment-dashboard
```

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

普通市场环境 GET 优先读取 PostgreSQL 中精确日期的数据集快照或 materialized aggregate，不自动启动 provider 采集。五类数据 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 分别使用 `(dataset, as_of)` lease；失败尝试保留同日期成功值并记录 warning，一键采集中的单项失败不会阻止其他结果保存。排查加载慢时分别查看 snapshot lookup、collection lease、provider collection、aggregate validation 和 PostgreSQL transaction/store write 计时。

盘后预计算：

```bash
python -m src.market_environment.cli snapshots refresh --as-of 2026-09-02
python -m src.market_environment.cli snapshots refresh --as-of 2026-09-02 --dataset core --dataset breadth --dataset limits --dataset sectors --dataset activeDirection
```

当前快照型 provider 默认只允许在上海时区目标市场日且达到结算时间后刷新；`--force` 仅用于显式本地诊断。命令输出每个数据集的 source、observations、duration、cache result 和 quality。单个数据集失败不会回滚其他成功数据集，也不会覆盖该日期上一次成功快照。

容量方向单项验证可运行 `python -m src.market_environment.cli snapshots refresh --as-of <上海市场当天> --dataset activeDirection --force`。采集先请求 `push2` 主域；连接/读取错误、429 或 5xx 在共享客户端有界恢复后仍失败，或主域载荷不满足契约时，再请求 `push2delay`。两个端点都必须返回至少 30 个含代码、名称和成交额的有效样本，并保持成交额非递增排序；数组、键值对象和已登记字段别名统一进入同一校验。延迟域成功时应看到 `source=eastmoney-clist-delay`、`quality.status=fallback` 和包含主域错误的 warning；两个端点都失败时只允许保留同日期旧快照。

### 第 02 页市场广度派生边界（2026-09-16）

第 02 页 "上涨家数、下跌家数和涨跌幅中位数" 在 provider 抓取的全 A 快照之上，由 `MarketEnvironmentService._enrich_breadth` 在每次章节请求时串接派生指标：涨跌家数差、涨跌差率、4 条 250 日滚动分位（上涨占比 / 涨跌差率 / 中位数 / 5 日动量）、5 日动量、5 个指数与广度同向判定、6 档宽度标签（含自然语言依据）。历史来源固定为 `SnapshotStore.list_snapshot_dates("breadth")` + `SnapshotStore.get("breadth", date)`，与第 01 章 `syncPattern` / `next-session` 共用同一快照读取路径。派生过程只读取本地快照，不调用 provider、不引入新的 API 路由、不修改 PostgreSQL schema、不增加新采集任务。`QTS-01-02-01..05` 规则 ID、阈值、权重与 YAML 保持不变；`rules validate` 仍输出 49 条规则。

排查 02 页 5 日趋势或 250 日分位缺失时：
- `breadth.history.validObservations` < 60 → 标注 `quality.status=insufficient`，3 个分位字段保持 `null`，不要补 0。
- `breadth.history.points` < 5 → 趋势表与折线图按已有天数渲染，不要用最近日期回填。
- `breadth.indexConsistent` 为 `null` → 5 个指数当日 `changePct` 全缺失时如实展示，不强行判定。
- `breadth.widthLabel="数据不足"` → 检查当日 `validCount == 0` 或 `quality.status in {missing, failed, insufficient}`。

### 第 03 页 limits 生态采集与验证

limits detail/V1 是独立于旧五字段池聚合的增量能力，由 `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED` 控制，默认值为 `0`。关闭时只提供既有 `limitUpCount`、`limitDownCount`、`failedLimitUpCount`、`failedLimitUpRatio`、`maxStreak` 和 PostgreSQL 快照读取；开启前必须在固定 fixture 上通过契约、Alembic schema、幂等、lease/CAS、失败保留、SQLite 导入源 `PRAGMA quick_check` 和 provider-free GET 验证。

扶摇作为三类池 membership 主源，必须校验交易日历、响应信封、逐页 `total/pages`、去重规范身份和日期冲突；池不回显日期时记录 `dateEvidence=request-parameter` warning。东方财富用于降级和交叉核对，两源集合差异按规范身份取并集并标记 degraded。基础晋级只要求精确相邻交易日、两日完整涨停集合和规范身份；ST、上市窗口、制度和板块缺失只降低对应分层，不得阻断基础晋级。不得使用证券名称匹配、自然日减一或固定涨跌幅制度推断。

状态排查应同时查看 `/api/market-environment/data-collection?as_of=<date>` 和 limits snapshot：状态 GET 只读 PostgreSQL、provider 调用数为 0；每个 limits task 显示当前/前一样本日期、实际日期、observations、排除数、checksum、晋级依赖和 warning。单项重试只启动 limits task，不重跑 `core`、`breadth`、`sectors` 或 `activeDirection`。刷新失败只记录 attempt，并保留同日期最后成功值为 `failed-retained` / `degraded`；没有旧值才为 `failed-missing`。

晋级验证必须能审计昨日完整涨停 membership 集合与今日同 `security_id` 集合的交集。分母为 0 时晋级率为 `null`、质量为 `insufficient`，不得显示 `0%`。`--history-sessions 6` 按交易日历升序采集六日并生成最近五个晋级点；有效观测不足 60 时 250 日分位和规则周期结论保持 `insufficient`。`QTS-01-03-01` 至 `QTS-01-03-05` 继续为 `needs-backtest`。

真实 provider smoke 不属于普通测试，只能在获得明确授权的盘后窗口、隔离 PostgreSQL 数据库和本地命令中执行。SQLite fixture（例如 `.artifacts/market-environment/limits-smoke.sqlite3`）仅用于导入回归，不承载 smoke 运行时状态。示例命令必须替换为获批的两日参数，并记录 provider 请求预算、每池主/延迟来源、`dateEvidence`、实际/前一交易日、来源、字段覆盖、排除数、warning、dataset/row checksum、耗时和最终 `ok`/`fallback`/`degraded`/`insufficient`/`failed` 质量；缺少日期绑定或存在日期冲突时只保留失败审计，不写生产数据库；禁止复用生产数据库或将失败转成成功。

```bash
# 仅限已授权的盘后隔离 smoke；普通离线/PR 验证不得执行真实 provider
MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=1 \
MARKET_ENVIRONMENT_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<isolated_db> \
MARKET_ENVIRONMENT_FUYAO_API_KEY=<secret> \
.venv/bin/python -m src.market_environment.cli snapshots refresh \
  --as-of <获批当前交易日> --dataset limits --history-sessions 6 --force
```

回滚时先将 `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=0` 并重启 API/采集进程，再恢复应用版本。保留 PVC、旧五字段快照、`trading_sessions`、`limit_security_datasets`、`limit_security_facts` 和 checksum；不删除数据库、不回填其他日期，也不因回滚修改规则 ID、权重或校准状态。

部署内盘后定时采集：

```bash
# 本地验证调度入口；日期由 Python 按 Asia/Shanghai 解析
python -m src.market_environment.cli snapshots scheduled-refresh

# 查看 CronJob、最近 Job 和结构化日志
kubectl get cronjob,job -n a-stock
kubectl logs -n a-stock 'job/<job-name>'
```

不得使用裸 `kubectl patch` 暂停或恢复周期调度；TrueNAS 的正常激活、回退和激活失败补偿都必须走下文受控入口，由入口绑定实际 release-derived CronJob、clean/upstream、冻结 hashes、授权与 live state。紧急停止新调度使用 `--disable-schedule`；若目标状态不确定则保持 NO-GO 并按已审核的 exact-resource incident packet 处置。provider-backed Job 也不得从本 runbook 的固定示例创建，必须由专用受审 packet 给出 exact name/resource/日期，并经本次操作责任人书面确认后通过专用入口执行。

业务目标 CronJob 使用 `Asia/Shanghai` 的 `30 16 * * 1-5`，覆盖 `core`、`breadth`、`limits`、`sectors`、`activeDirection`，并设置 `concurrencyPolicy: Forbid`、`backoffLimit: 0` 和执行超时。native `spec.timeZone` 要求 Kubernetes/k3s 1.27+；Chart 本身仍支持 1.26，TrueNAS controller profile 使用经过验证的 `Etc/UTC` `30 8 * * 1-5` 或 `Asia/Shanghai` `30 16 * * 1-5`，且省略该字段。周末直接运行 CLI 时返回 `skipped` 且不访问 provider；结算前运行返回非零。`partial`/`failed` 也返回非零并让 Job 显示失败，但已经成功的数据集继续保存在 PostgreSQL，CronJob 不自动整批重跑；到 `/data-collection` 只重采失败行。

Helm 通过 `marketEnvironment.scheduledCollection` 配置，Chart 默认 `enabled=false`、`suspend=true` 且不渲染 CronJob；`suspend=true` 在显式启用时保留资源但不创建新 Job。通用 install/upgrade/application rollback 必须重交完整受控 values 和这两个安全覆盖，不得继承历史 values 或恢复历史 revision。`timezoneStrategy=native` 仅允许 1.27+ 的上海 native timezone，`timezoneStrategy=controller` 仅允许 1.26、allowlist controller timezone、已声明的时区证据和固定 16:30 映射。controller profile 的 `suspend=false` 还要求 `controllerCanaryVerified=true`，但这个配置断言只是 typed 校验，不能替代运行时的 controller canary 证据。正式部署使用不可变 image tag，Dashboard 和 CronJob 必须解析到同一镜像版本并通过同一 PostgreSQL Service/Secret 访问数据库，均不挂载 PVC；fail-closed 默认下不会创建 Job 或解除暂停。

仓库入口的目标模式按用途分为通用入口和调度专用入口；通用入口（`--component all|database|service`）只渲染或发布对应组件，且任何构建/目标写操作前都强制 typed `enabled=false / suspend=true` 默认值：

```bash
# 一键：database -> service；schedule 默认 disabled/absent
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --component all

# 通用离线 render；不访问 SSH 或目标 API
bash scripts/deploy-truenas-k3s.sh --offline-render \
  --baseline-values deploy/truenas/values-secure-manual-collection.yaml \
  --scheduling-overlay deploy/truenas/values-scheduled-off.yaml \
  --kube-version 1.26.6+k3s1 --release-name a-stock --namespace a-stock
```

调度专用入口（`--release-suspended` / `--activate-schedule` / `--disable-schedule`）由本次操作责任人书面确认本次操作的 release、namespace、镜像 digest 和 catch-up 行为后再调用，并在 plan 的 Completion Evidence 中记录对应证据。`--activate-schedule` 必须明确选择 `next-schedule` 或 `immediate-catch-up`，其中 `next-schedule` 必须已越过上一触发的 `startingDeadlineSeconds` deadline 且距下一触发至少 300 秒，`immediate-catch-up` 只允许在 deadline window 内。该时间窗在 preflight 校验一次，并在 live/image/diff/re-render/hash 检查后、Helm write 前再次校验；第二次失败时 Helm write 和补偿 patch 都必须为零。第二次校验通过后才启用 fail-safe，Helm、写后读取/比较/最终查询或 HUP/INT/TERM 任一失败都对 release-derived exact CronJob 补偿 `suspend=true`，全部 postcondition 通过才解除。所有目标模式要求 `REVIEWED_GIT_HEAD` 与本地 upstream 相等、工作树完全 clean，并校验 `REVIEWED_CHART_SHA256`。

部署文档安全测试把 CommonMark shell fence 与 Bash AST 作为发布门禁。brace/glob executable expansion、`eval`、stdin-fed `bash`/`sh`/`dash`/`zsh`、`source`/`.`、`alias`/`hash -p` command-resolution mutation、动态 executable/action 和未知 Helm plugin/action 都必须返回 violation；无法解析或无法证明只读时 fail closed，不能因缺少字面量 `helm` 而跳过。

从 server dry-run 起，脚本把审阅后的 chart/baseline/overlay 复制到本次运行专属只读快照，重新校验 render hash，后续 admission 或 Helm upgrade 只读取该快照。实际 release 前同时验证 Helm 记录与 API server live Deployment/Service/CronJob，绑定 Dashboard Pod 的 Deployment→ReplicaSet owner chain、ready 状态、精确镜像 tag、合法 CRI imageID，以及目标 containerd tag→reviewed manifest digest；任一 drift 都拒绝。CRI imageID 通常是 image config digest，不要求与 containerd manifest digest 相等。写操作使用 `helm upgrade --atomic`，随后再次读取 live 资源并与冻结 manifest 比较；激活或回退失败会先对 exact CronJob 补偿设置 `suspend=true`，再报告目标状态需要复核。

调度专用入口的使用前提：所有修改必须经本次操作责任人书面确认并在 plan 的 Completion Evidence 中记录，并且：(1) `REVIEWED_GIT_HEAD`、clean 工作树与本地 upstream 一致；(2) `REVIEWED_CHART_SHA256`、`REVIEWED_BASELINE_SHA256`、`REVIEWED_OVERLAY_SHA256`、`REVIEWED_RENDER_SHA256` 全部已计算并验证；(3) frozen image 已通过 `FROZEN_IMAGE_*` 三元组固化；(4) `--activate-schedule` 已明确选择 `next-schedule` 或 `immediate-catch-up` catch-up 行为；(5) 在 execute 前再次核对 live release 与冻结 manifest 一致、candidate diff 只包含 `/spec/suspend: true -> false` 单字段变化。任何步骤失败都保持 `suspend=true`，不进入 Helm write。

第一版只用 cron 周范围排除周末，不维护交易所节假日日历。工作日节假日可能产生 failed/partial run；这是可审计的失败安全行为，任何 provider 无法证明属于当天的数据都不得落入当天快照。不要用 `--force` 或跨日期复制规避该限制。

配置：

### PostgreSQL 迁移与运行时边界

生产 Dashboard Deployment 与盘后 CronJob 只通过 Helm 创建的 PostgreSQL ClusterIP Service 访问数据库，
不挂载 SQLite 或 PostgreSQL PVC。PostgreSQL StatefulSet 单副本独占 Retain RWO claim；数据库凭据必须由
部署前置步骤创建 existing Secret，至少包含 `DATABASE_URL`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 和
`POSTGRES_DB`，Chart 不渲染明文凭据或外部监听器。

迁移前先暂停 CronJob、关闭手工写入并创建 SQLite before-image；迁移 Job 只读挂载旧 SQLite claim，执行
`python -m src.market_environment.cli database migrate --source /data/snapshots.sqlite3 --backup /tmp/snapshots-before-postgresql.sqlite3`
进行 dry-run。完成 quick-check、表统计、日期覆盖和 checksum 审核后，才显式增加 `--apply` 并切换
`MARKET_ENVIRONMENT_DATABASE_URL`。active lease 不迁移为有效所有权，改为可重试状态；旧 SQLite PVC 和备份
保留但脱离 Dashboard/CronJob，禁止在普通发布中删除。

迁移 Job 必须继承 chart 的 Pod 级 `runAsUser/runAsGroup/fsGroup=10001`，否则 root-owned `emptyDir /tmp`
无法写入 before-image。CLI 对该已停写、只读挂载且已固定 SHA-256 的源使用 SQLite `immutable=1`，避免 WAL
数据库在只读卷上尝试创建锁或共享内存 sidecar；普通仍可能写入的 SQLite 读路径禁止使用该选项。
导入事实表会触发 PostgreSQL revision trigger；`materialization_component_versions` 冲突时必须保留源/目标中较大的
revision，不能使用通用 `DO NOTHING` 降低版本。导入重试应保持幂等，并再次通过逐表子集 checksum 校验。

PostgreSQL 首次写入前失败可恢复旧镜像和 SQLite PVC；首次写入后禁止回切过期 SQLite，必须使用 PostgreSQL
备份/恢复或前向修复。数据库不可达时服务 fail closed，不创建本地 SQLite 回退文件。

#### Secret、初始化和依赖顺序

Chart 不生成或渲染明文凭据。部署前由受控凭据系统或管理员创建 existing Secret（以下命令仅为本地示例，
不要把真实密码写入 shell history）：

```bash
kubectl -n a-stock create secret generic a-stock-postgresql \
  --from-literal=DATABASE_URL='postgresql+psycopg://<user>:<password>@a-stock-postgresql:5432/<db>' \
  --from-literal=POSTGRES_USER='<user>' \
  --from-literal=POSTGRES_PASSWORD='<password>' \
  --from-literal=POSTGRES_DB='<db>'
```

Helm render/deploy 必须提供 `database.existingSecret=a-stock-postgresql`（或等价 Secret 名称），并 fail closed
于缺失 Secret、缺失 key 或 URL 不合法。组件依赖固定为：

```text
PostgreSQL StatefulSet/ClusterIP Service ready
  -> Alembic schema migration Job (`alembic upgrade head`) 成功
  -> Dashboard Deployment rollout
  -> suspended CronJob render/deploy
```

StatefulSet 未 ready 或 migration Job 失败时不得 rollout service/schedule；migration Job 使用同一 URL Secret，
成功后检查 `alembic_version`，并把 Job 日志及 manifest hash 作为切换证据。

#### 备份、恢复与切换边界

切换前暂停 CronJob、设置 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 并等待正在进行的 collection task
结束；创建不可覆盖的 PostgreSQL `pg_dump --format=custom` 备份，记录 Service、PVC UID/PV、数据库版本、
`alembic_version`、文件 SHA-256 和恢复演练结果。SQLite before-image 仅由迁移工具在线 `backup()` 生成，
执行 `quick_check`、行数/主键范围/payload checksum 与日期覆盖校验后才可 `--apply` 导入。

迁移 Job 只读挂载旧 SQLite PVC，导入完成后执行逐表统计与 checksum 校验；active lease 不导入为有效所有权，
而是标记为过期/可重试并保留 fencing 审计。所有校验通过后才更新 Deployment/CronJob 的 Secret 引用并 rollout，
执行 provider-free GET、并发 lease/collection 写入和一次受控 CronJob 试运行验证。旧 SQLite PVC 与 before-image
继续保留但脱离应用挂载，清理另行授权。

PostgreSQL 首次写入前失败时，可恢复旧镜像并继续使用旧 SQLite（仅在尚未产生 PostgreSQL 事实写入的窗口内）；
一旦 PostgreSQL 产生新写入，禁止把过期 SQLite 当作事实源回切。此后只能从 PostgreSQL 备份恢复或执行前向修复，
并重新运行 checksum/日期/aggregate 校验。任何恢复都不得删除或覆盖原备份、PVC 或迁移 before-image。

恢复示例（仅对隔离目标执行，禁止指向生产数据库）：

```bash
export PGHOST="db.example.internal" PGUSER="restore_admin" PGDATABASE="market_restore"
createdb --host "$PGHOST" --username "$PGUSER" "$PGDATABASE"
pg_restore --clean --if-exists --no-owner \
  --dbname="postgresql://${PGUSER:?set PGUSER}:${PGPASSWORD:?set PGPASSWORD}@${PGHOST:?set PGHOST}:5432/${PGDATABASE:?set PGDATABASE}" \
  "${BACKUP_FILE:?set BACKUP_FILE}"
```

- `MARKET_ENVIRONMENT_DATABASE_URL`：PostgreSQL 运行时连接 URL（生产必需，通过 Secret 注入）。
- `MARKET_ENVIRONMENT_DB_POOL_SIZE`、`MARKET_ENVIRONMENT_DB_MAX_OVERFLOW`、`MARKET_ENVIRONMENT_DB_POOL_TIMEOUT`、`MARKET_ENVIRONMENT_DB_STATEMENT_TIMEOUT_MS`：PostgreSQL 连接池和语句超时。
- `MARKET_ENVIRONMENT_SNAPSHOT_PATH`：仅供一次性 SQLite 导入/日期审计工具使用，不是运行时存储配置。
- `MARKET_ENVIRONMENT_PERSISTENT_CACHE=0`：关闭持久缓存并回退到直接 provider 路径，用于紧急回滚。
- `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`：显式关闭数据采集页面写操作和 collection POST；默认开启。TrueNAS 固定 NodePort 是经负责人接受的例外，启用时向所有可路由客户端匿名开放写操作；出现异常时先将此项设为 `0`，再按现场捕获的回退基线决定网络入口。
- `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=0`：关闭 limits detail/V1 事实写入和晋级扩展，继续服务旧五字段与 PostgreSQL 快照；开启前须完成离线门禁，真实 smoke 只能写隔离 PostgreSQL 数据库。
- `MARKET_ENVIRONMENT_FUYAO_API_KEY`：扶摇 provider 密钥，只能通过独立 Secret/进程环境注入；不得写入 values、日志、API 响应或仓库文件。V1 开启但变量缺失时采集失败并保留旧快照，普通 GET 仍可用。
- `MARKET_ENVIRONMENT_SETTLEMENT_TIME=15:10`：上海时区盘后结算边界；scheduled-refresh 在该时间前拒绝采集，CronJob schedule 必须晚于该值。
- 运行时不依赖 SQLite 文件；旧 SQLite 文件只能作为停写迁移源和归档，不能挂载给 Dashboard/CronJob 作为共享协调边界。

开发期手工采集 API：

```bash
curl -X POST "http://127.0.0.1:8001/api/market-environment/collection-runs" -H "Content-Type: application/json" -d '{"asOf":"2026-09-03"}'
curl "http://127.0.0.1:8001/api/market-environment/collection-runs/<run-id>"
```

POST 立即返回 `202` 和 `runId`；省略 datasets 时创建五个独立 task，传 `{"datasets":["breadth"]}` 时只采集单项。父批次允许 `partial`，每个成功 task 独立提交；失败 task 不覆盖同日期旧值。数据采集页 `/data-collection` 只通过 GET 查询本地状态，所有 provider 故障时仍应可打开。历史日期仅允许采集 provider 能验证日期的数据集；无法证明日期的最新快照型数据按钮必须禁用并由 API 返回 422。服务重启后，遗留 collecting task 在 lease 过期后可重新采集。

数据采集页首次加载调用不带 `as_of` 的状态 GET，并用响应 `asOf` 初始化日期控件；后端按 `Asia/Shanghai` 解析有效市场日：开市前（09:30 前）返回上一工作日对应的真实交易日并跳过周末，节假日或没有可证明实际日期时返回 `insufficient`/拒绝，不猜测日期；开市后才返回上海当天。provider 返回的实际日期必须与目标 `as_of` 一致，无法证明时保持 `insufficient`/`failed`，不得通过改名或复制跨日期数据。用户手工切换日期后使用显式 `as_of`，历史限制继续生效。研究看板仍使用下述 15:00 结算日期逻辑，两者不要重新合并。

研究看板日期控件使用浏览器本地时间计算默认值：15:00 前为前一天，达到 15:00 后为当天；首次核心响应若确认候选日为非交易日，日期控件同步为响应的有效交易日；用户手工选择后不得自动改写。最大值始终为浏览器本地当天。不要改回 `new Date().toISOString().slice(0, 10)`，否则 UTC 转换可能导致日期错位。API 的默认日期与未来日期校验使用 `Asia/Shanghai`。市场广度直接从 `push2delay` 按涨跌幅排序分页定位边界与中位数，成功时 `chapter01.breadth.quality.source` 为 `eastmoney-clist-delay`、状态为 `fallback`。行业板块先请求 `push2`，连接/读取错误、429 和 5xx 有界重试后仍失败再请求 `push2delay`；403 不重试。延迟域成功时保留主域 warning，领涨股名称使用 `f128`，不得显示 `f140` 证券代码。容量方向的 Top-N 响应必须验证排序、最小样本和必需字段。任一采集失败时保留 `null` 或上一次精确日期成功值，并在 `quality.warnings` / `refreshWarning` 记录错误，不能用 0 填充。

指数 `history` 契约中的每个点应包含 `date`、`open`、`close`、`low`、`high`、`ma5`、`ma10`、`ma20`、`ma60` 和 `amount`。浏览器 QA 必须确认 60 日图存在非空 K 线实体、红涨绿跌、均线叠加和 OHLC tooltip；禁止用收盘价复制生成开高低。

指数 provider 默认拉取 280 根 K 线：mootdx `offset`、新浪 `datalen`、东方财富 `lmt`、腾讯 `param` 数量均按 280 请求，百度响应在本地最多保留 280 根。盘后显式冒烟应逐一记录五指数返回数量与冷缓存耗时；不足 280 根时不得伪造，只能按实际观测降置信。升级前已落 SQLite 的历史核心快照通常只含旧版 160 根输入，本次不回填，相关 250 日分位应保持 `insufficient-history` 或 reduced confidence。

指数卡的量价区域应先展示 `amountRatio5`，再展示可选的 `volumePriceState`。量价状态为 `null` 表示价格与成交额组合未命中任何明确规则，不是接口错误，前端不得改写为“量价平稳”；只有比值缺失时显示 `--` / “数据不足”。

每个指数的 `combination` 契约应包含 `key`、`state`、`matched`、`tone`、`evidence` 和 `tradingMode`。`chapter01.combinationOverview` 汇总 `strength`、`stage`、`capitalAcceptance`、`tradingMode`、`confidence` 和 `evidence`。浏览器 QA 必须切换至少两个指数，确认组合状态和证据同步变化；未命中状态显示“未命中明确组合”，不得补成六类中的任意一类。

第 01 页每张指数卡的收盘指数值与右侧涨跌幅必须分别可复制；复制控件不得触发卡片选中，成功状态需可访问。涨跌幅在页面上保留百分号，写入剪贴板时去掉百分号并保留正负号和两位小数。浏览器或权限不支持剪贴板时只能显示明确失败或受控降级，不得显示“已复制”。桌面和 390px 检查均需确认复制控件、反馈文字和卡片内容不重叠。

`summary.syncPattern` 只记录五指数当日方向模式；`summary.synchronizationAssessment` 是独立的联合研判，返回总状态、稳定结论码、中文结论、置信度，以及 `breadth`、`trend`、`turnover` 三项确认维度。排查结论时先核对原始模式，再逐项核对上涨占比/中位数、MA20 上下方指数数和 5 日成交额比值/放量下跌数，不能只看最终文案。权重指数领涨不等于个股偏弱，普遍走弱也不自动等于系统性下降。

广度改善或恶化只比较精确上一交易日：服务从核心指数历史取得前一交易日期，再读取该日期的 PostgreSQL `breadth` 快照。上一日记录缺失时 `previousAsOf` 与变化值保持 `null`、维度标记不足且整体置信度不高于中；不得向更早日期回退，普通 GET 的 provider 调用数必须仍为 0。需要补齐时先显式采集缺失交易日，再通过既有 collection/rebuild 路径重建目标日期聚合，不要直接修改数据库行或复制其他日期 payload。

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

### Helm schedule 组件（合并所有权）

适用：TrueNAS k3s 1.26.6 上的盘后采集调度。release-derived `a-stock-data-collection` 与 Dashboard / PostgreSQL 同属 Helm release `a-stock`；仓库不再保留独立 operator override 清单、脚本或 `market-environment-data` PVC/PV/StorageClass。CronJob 通过 `a-stock-postgresql` ClusterIP Service 和同名 Secret 访问 PostgreSQL，不挂载数据库 PVC。

**fail-closed 默认：**

- chart 默认仍为 `scheduledCollection.enabled=false / suspend=true`；普通 `all` / `database` / `service` 发布不得渲染或激活 CronJob。
- `deploy/truenas/values-scheduled-baseline-20260917.yaml` 是 2026-09-17 合并所有权使用的受版本控制 baseline：冻结镜像 `localhost/a-stock-market-environment:20260917-113516-b5be526`，引用 `a-stock-postgresql` Secret 与 `a-stock-data` existingClaim，调度为 `enabled=true / suspend=true`。
- k3s 1.26.6 使用 `timezoneStrategy: controller`，省略 `spec.timeZone`。目标 controller 已验证为 `Asia/Shanghai`，因此上海 16:30 使用 `30 16 * * 1-5`。任何时区证据变化都必须停止 schedule write；不得把该值静默改成 `30 8`。
- `controllerCanaryVerified=false` 保持 suspended release；激活 overlay 只有在 canary evidence 完整并由本次操作责任人书面确认后才允许设为 `true`。

**独立 CronJob 迁移到 Helm（一次性）：**

迁移必须在 16:30 之外执行；先确认无 active Job。下列命令只描述受控顺序，任何失败都停止并保留 `suspend=true`：

```bash
# 1. 只读快照；保留到本次 plan 的 Completion Evidence
kubectl get cronjob,pvc,pv,sc,job -n a-stock
helm list -n a-stock
kubectl get cronjob market-data-collection -n a-stock -o yaml \
  > /tmp/legacy-cronjob-snapshot.yaml

# 2. 确认没有 active Job 后，删除非 Helm-owned 同名对象
kubectl delete cronjob market-data-collection -n a-stock

# 3. 由专用入口重新创建为 Helm-owned 且 suspended
bash scripts/deploy-truenas-k3s.sh \
  --component schedule \
  --release-suspended \
  --baseline-values deploy/truenas/values-scheduled-baseline-20260917.yaml \
  --scheduling-overlay deploy/truenas/values-scheduled-suspended.yaml \
  --kube-version 1.26.6

# 4. 精确读回
kubectl get cronjob a-stock-data-collection -n a-stock -o yaml
helm get manifest a-stock -n a-stock
```

读回必须同时满足：`app.kubernetes.io/managed-by=Helm`、`SUSPEND=True`、schedule `30 16 * * 1-5`、无 `spec.timeZone`、`concurrencyPolicy=Forbid`、deadlines 1800/3600、镜像与 baseline 一致、安全上下文完整。任一不满足都停止，使用 `/tmp/legacy-cronjob-snapshot.yaml` 与合并前 Helm revision 分析回滚；不得临时裸 apply。

**孤立存储清理：**

只有在 Helm-owned CronJob 已读回且确认没有 Pod 引用 `market-environment-data` 后，才按 exact 名称删除旧资源；这些资源不是 PostgreSQL PVC，也不是 `a-stock-data`：

```bash
kubectl delete job market-data-verify -n a-stock
kubectl delete pvc market-environment-data -n a-stock
kubectl delete pv a-stock-market-environment-data
```

`manual-local` StorageClass 不是孤立资源：现场只读发现确认 `a-stock-data` 与其它 namespace 的 `manual-postgres-pv` 都使用它，因此必须保留。删除主机目录前先记录 `/mnt/xiaomi/app-data` 与目标子目录权限；再删除 exact `/mnt/xiaomi/app-data/a-stock-market-environment` 子目录并把父目录权限恢复到与同级一致。禁止使用未展开变量、glob 或宽范围递归删除。

**后续激活与回退：**

- 激活只允许专用 `--activate-schedule` 入口，使用 `deploy/truenas/values-scheduled-active.yaml`，要求 `controllerCanaryVerified=true`、完整 `FROZEN_IMAGE_*` 三元组和明确 catch-up 策略。
- 回退只允许 `--disable-schedule` 或 `helm rollback a-stock <合并前 revision>`。不得执行 raw `helm uninstall`，不得重建独立 CronJob。
- 激活后第一次交易日 16:30 必须观察 Job/Pod、PostgreSQL collection run、dataset quality 与 `/api/market-environment` 响应；provider 失败保留 `partial` / `degraded` / `insufficient`，不得伪造 success。

2026-09-17 生产基线为 Helm revision 20：`a-stock-postgresql` 与 Dashboard 均 Ready，唯一 CronJob
`a-stock-data-collection` 为 Helm-owned 且 `suspend=true`。SQLite 历史已导入 PostgreSQL；验收读取使用
`/api/market-environment?as_of=2026-09-16` 和 `/api/market-environment/core?as_of=2026-09-16`，均返回
200、5 个指数且无顶层 data gap。盘中默认当天尚未采集时返回 503 属于 exact-date fail-closed，不得改为静默回退。

## 验证矩阵

| 检查 | 命令 / 方法 | 证据位置 | 必需 |
|------|-------------|----------|------|
| docs-contract | `python scripts/check-docs-contract.py --mode=full` | 终端输出 / plan 的 Completion Evidence | 是 |
| hooks 连通 | `git config core.hooksPath`（应为 `.githooks`） | 终端输出 | 是 |
| Build | `npm run build --prefix apps/market-environment-dashboard` | 终端输出 / plan | 是 |
| Backend tests | `.venv` Python 下运行 `python -m pytest tests -q` | 终端输出 / plan | 是 |
| k3s manifests | `kubectl kustomize deploy/k3s` 只渲染 Dashboard base；`python scripts/render-k3s.py --kube-version 1.27.0` 检查 `deploy/k3s-native-scheduled/render-policy.yaml` 后才渲染 native overlay；不得把该输出作为 TrueNAS 1.26 admission probe | 终端输出 / plan | 是 |
| Helm chart | `helm lint deploy/helm/a-stock` 与 `helm template a-stock deploy/helm/a-stock --namespace a-stock` | 终端输出 / plan | 是 |
| Snapshot refresh | `python -m src.market_environment.cli snapshots refresh --as-of <date>` | CLI JSON / plan | 是 |
| Collection management | 启用开发开关后验证状态 GET、单项 POST、全部 POST、轮询和 partial 结果 | pytest / 浏览器 / plan | 是 |
| Scheduled collection | scheduled-refresh success/partial/failed/skipped/settlement/lease-conflict 固定 fake-provider 回归；Kubernetes 1.26 controller-UTC/controller-Shanghai 与 1.27+ native 的 disabled/suspended/active Helm 矩阵；`kubectl kustomize` Dashboard base 与受版本门禁的 native overlay | pytest / CLI JSON / plan | 是 |
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
- **上一交易日广度为不足**：从指数 history 确认 `previousAsOf`，再检查 PostgreSQL 是否存在该精确日期的 `breadth` 成功快照；更早快照不会被采用，GET 也不会自动联网补采。
- **第 01 章证据显示 `missing` / `partial`**：先看对应对象的 `quality.warnings`。历史日期缺少广度、板块或成交额榜是当前快照源的预期边界；东方财富 403 或空 `data` 也必须保留缺失状态，不能用空数组伪造为 0。只有接口成功且明确返回空 `pool` 时，涨跌停计数才可为 0。
- **章节显示 `cacheState=stale`**：查看 `snapshotFetchedAt` 和 `refreshWarning`；旧值仍对应同一交易日，但后台刷新失败或尚在进行。不要删除旧快照后用其他日期数据替代。
- **refresh 一直显示被占用**：检查 PostgreSQL 中同 dataset/date 的 lease；正常 lease 会在有界时间后过期。仅在确认没有刷新进程后使用 CLI 强制重试，不要直接修改 lease/fencing 字段。
- **数据采集批次显示 `partial`**：查看每个 task 的 warning；成功 task 已独立保存，只对失败行执行重新采集，不要删除整批成功快照。
- **最近采集失败但数据仍可用**：这是 `failed-retained`，页面继续服务同日期最后成功值并展示刷新错误；只有 `failed-missing` 才表示该日期没有可用数据。
- **数据采集按钮不可用**：检查 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 是否被显式设为 `0`，并检查所选日期和 provider 日期能力；不要用强制参数把最新快照写成历史日期。
- **CronJob 没有启动**：检查资源是否被 Helm `enabled=false` 省略、`spec.suspend`、selected strategy、schedule、`startingDeadlineSeconds` 和控制器事件；1.26 controller strategy 还须复核时区证据与 canary。创建一次性 Job 必须经本次操作责任人书面确认后在 plan 中登记。
- **CronJob 为 Failed 但页面有部分数据**：检查容器 JSON 中的父状态和各 task warning；`partial` 有意返回非零且不自动整批重试，成功兄弟任务已经落盘，只补采失败行。
- **CronJob 卡住或错过下一次运行**：查看 `activeDeadlineSeconds`、Pod 外网访问和 PVC 挂载；`concurrencyPolicy: Forbid` 会跳过重叠触发，确认旧 Job 结束后再补跑一次性 Job。
- **节假日出现 failed/partial**：第一版预期会在周一至周五节假日触发；确认没有跨日期 snapshot 后保留审计记录，不要伪造当天成功。
- **行业板块采集偶发 `RemoteDisconnected`**：确认请求经过共享串行门；主域会先执行有限连接重试，再降级到 `push2delay`。若两个域都失败，查看 task warning 和同日期 snapshot 是否触发 `failed-retained`，不要删除旧值或跨日期回填。
- **容量方向采集为 `failed-missing`**：先检查 warning 是否为 `push2` 主域断连，并确认实现已继续请求 `push2delay`。延迟域成功应记录 `eastmoney-clist-delay` / `fallback`；若延迟域少于 30 个有效样本、缺少代码/名称/成交额或排序异常，必须继续视为失败。存在同日期成功值时应为 `failed-retained`，不要用其他日期或零值替代。
- **容量方向采集为 `failed-missing`**：先检查 warning 是否为 `push2` 主域断连或载荷无效，并确认实现已继续请求 `push2delay`。延迟域成功应记录 `eastmoney-clist-delay` / `fallback`；若延迟域少于 30 个有效样本、缺少代码/名称/成交额或排序异常，必须继续视为失败。存在同日期成功值时应为 `failed-retained`，不要用其他日期或零值替代。
- **涨跌停生态采集为 `failed-missing`**：逐池检查 `push2ex` 主域和兼容延迟域的请求记录。延迟池成功时必须在池证据中记录 fallback 来源和主域错误；缺少顶层日期但请求 `date` 明确时应记录 `dateEvidence=request-parameter`，显式行日期冲突、池格式无效或两端点均失败时仍保持 `failed`/`insufficient`，不得把空响应当作 0 或跨日期回填。
- **需要紧急回滚持久缓存**：设置 `MARKET_ENVIRONMENT_PERSISTENT_CACHE=0` 并重启 API；PostgreSQL 数据库和旧 SQLite 归档均保留用于诊断，不需要删除。
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


## 前端路由 history mode SPA fallback（2026-09-16）

市场环境看板从单一 App.vue 路由壳演进为
ue-router history mode 后，直接刷新或通过 URL 直接访问非根路径会先打到后端静态服务，必须配置 SPA fallback，否则返回 404。

### 触发条件

用户访问任一非 / 路径并触发浏览器刷新：

- http://host/dashboard/03 → 直接 404（如果未配置 fallback）
- http://host/settings → 直接 404
- http://host/data-collection → 直接 404

内部 <RouterLink> 与
outer.push 不会触发此问题，因为它们走 pushState / popstate，不重新加载 HTML。

### 部署侧要求

- 开发环境（Vite dev server）：自动 fallback，无需额外配置。
ite.config.ts 已配置 server.proxy 到 /api。
- TrueNAS k3s Ingress 部署：Ingress 必须配置
ginx.ingress.kubernetes.io/rewrite-target: / 或同等的 fallback annotation；Helm chart 尚未升级此配置（属于
rontend-component-split change 的 Phase 4 任务 4.8）。
- TrueNAS NodePort 直连：使用 kubectl port-forward 或 NodePort 直连 Vite 静态构建产物（pps/market-environment-dashboard/dist/index.html），需要在静态文件服务器（nginx / caddy）侧配置 SPA fallback：
  - nginx: 	ry_files \ \/ /index.html;
  - caddy: 	ry_files {path} /index.html
- 本地纯静态托管：同上，静态文件服务器需配置 SPA fallback。

### 与现有部署路径的交叉

- 当前 pps/market-environment-dashboard/dist/ 不存在（本次提交未构建），待首次
pm run build 后产出。
- Ingress / NodePort 部署清单（deploy/truenas/、deploy/k3s/）暂未升级 Vue 路由 + SPA fallback 配置；属于后续 Phase 4 任务 4.8 范围，本次提交不交付。

### 验证

- 部署后手动刷新任一 /dashboard/03 / /settings / /data-collection URL，必须返回 200 与前端 HTML。
- 测试命令（开发）：
pm run dev --prefix apps/market-environment-dashboard 后浏览器访问 http://localhost:5173/dashboard/03，应渲染 03 章节占位内容（本次提交占位为 DashboardPlaceholder）。

## legacy hash 重定向（2026-09-16）

旧版看板使用 #document-03 锚点定位章节。
outer/legacy-redirect.ts 在
outer.beforeEach 钩子里检测 window.location.hash，匹配 #document-(0[1-9])$ 时调用
outer.replace('/dashboard/N') 重写路径并清空 hash。

### 行为

- https://host/#document-03 → 重写为 https://host/dashboard/03，hash 清空，不留历史记录
- https://host/#some-anchor → 不动（路由按当前路径解析）
- 已经处于 /dashboard/03 的链接 → 不重复重写
- SPA fallback 不会与 legacy hash 冲突：fallback 服务返回 index.html 后前端 router 接管，legacy-redirect 在路由解析的 eforeEach 阶段生效。

## ECharts 生命周期（2026-09-16 frontend-component-split Phase A）

市场环境看板前端 ECharts 实例通过 composables/useChartLifecycle.ts 统一管理。每个图表面板组件（IndexPriceChartPanel / VolumeChartPanel / BreadthHistoryChartPanel）在 <script setup> 顶层调：

`	s
const lc = useChartLifecycle(elementRef, () => optionFactory(props))
``n
### 行为

- onMounted 调 echarts.init(elementRef.value) + setOption(optionFactory())。
- 若传入第三个参数 watchSources，则 watch(watchSources, () => setOption(optionFactory())))) 在数据源变化时重画（不重建实例）。
- window.addEventListener('resize', resize) 监听浏览器 resize，触发 chart.resize()，不 dispose。
- onBeforeUnmount 调 chart.dispose() 并清空引用——实例随组件生命周期一起销毁，不再有全局协调。

### 调用方约束

- **绝不**在组件外持有 let chart: echarts.ECharts | null = null 闭包变量；composable 自己负责。
- **绝不**在父组件里同时存在多个 chart 实例共享一个 DOM 节点——每个 panel 一个 ref + 一个 composable。
- 旧版 App.vue 里的 chart / volumeChart / breadthChart 三个全局闭包变量与 renderChart / disposeCharts / resizeCharts / renderBreadthChart / disposeBreadthChart 函数在 Phase C（App.vue 收尾）时删除。Phase A 只新增 composable，不动 App.vue。

### 调试

- 图表不显示：检查 elementRef.value 在 onMounted 时是否非 null（happy-dom 下 <div ref=...> 立即可用）。
- 图表不响应数据变化：检查 watchSources 是否返回 reactive 引用；直接传对象会丢失响应性。
- 图表 resize 后位置错乱：检查 chart.setOption(optionFactory(), { notMerge: true }) —— notMerge 确保选项整体替换而非合并。

## useDocumentContext 边界（2026-09-16 frontend-component-split Phase A）

composables/useDocumentContext.ts 是 9 章节组件的公共派生与 label 字典聚合。

### 边界

- **仅暴露** ComputedRef 与纯函数：breadth / limits 派生、quality / reason / environment / gap label 字典、formatRatioDelta / formatReturnDelta。
- **绝不暴露**任何 setXxx / loadXxx 写操作。章节组件如需触发刷新 / 日期变更等写操作，必须通过 defineExpose / emit 委托给 DashboardLayout 或 App.vue 路由壳。
- useMarketStore() 仅在 setup 顶层调用一次（不暴露给外部）。

### 调试

- 章节测试报错 Cannot read properties of undefined：检查 setActivePinia(createPinia()) 后是否手动 market.data = fixture 预填；composable 派生全部基于 market.breadth / market.limits，store 为 null 时返回空数组/默认值。
- 测试通过但运行时报 isSupportedTimeZone 异常：检查 fixtures 里的 timezone 字段是否使用 IANA 标准名（如 Asia/Shanghai），而非 CST / GMT+8。

## 章节页面组件（2026-09-16 frontend-component-split Phase B-01/B-02）

第 01、02 章已拆为独立页面组件（Document01IndexPricePage / Document02BreadthPage），配套三个 chart panel。

### 章节 fixture 预填约定

- 独立挂载页面组件时，fetch mock 不会自动生效——必须在 setActivePinia 后显式调用 market.loadCore()（或手动赋值 market.data）预填数据，再 mount。直接 mount 页面组件而 store 为 null 时，页面只渲染 page-flow-label 与空 section，测试会拿到空 DOM。
- 溢出断言：页面组件挂载后没有 App.vue 的 .content-shell 节点，390px 视口检查应针对 wrapper.element（页面根元素）而非壳层节点。

### chart panel 调试

- IndexPriceChartPanel 的 K 线 tooltip 由组件内 formatPriceTooltip 提供，从 App.vue 迁移时签名保持一致（接受 echarts params 数组）。
- BreadthHistoryChartPanel 的当日标记：advanceRatio / medianReturn props 非空且历史 points 为空时，图上只画当日单点；历史 points 非空时当日数据以 props 追加判断，与旧 App.vue renderBreadthChart 行为一致。
- 三个 panel 均 useChartLifecycle 持有实例；测试里 vi.mock('echarts') 后可断言 init/setOption/dispose 调用次数。

## Document03 预填与刷新约定（2026-09-16 frontend-component-split Phase B-03）

第 03 章（涨跌停）数据来自 chapter-01?section=limits，与第 01、02 章的 core 直出不同。独立挂载 Document03LimitsPage 时 fixture 预填必须走两步：先 market.loadCore()（满足 store 的 coreRequestedDate 前置条件），再 market.loadSection('limits')（拉取章节合并进 chapter01）。只调 loadCore 的话 market.limits 为 undefined，页面会渲染全部空态。

### section 刷新 emit 边界

- 组件内刷新按钮不直接调 store action，只 emit('refreshSection')。
- 测试在 mount 时通过 onRefreshSection prop 接线回 market.loadSection('limits', true)，验证 emit 边界的完整性。
- 刷新失败场景（fixture 第二次 chapter-01 返回 502）：store 的 sectionStates.limits 落入 error phase，组件的 limits-refresh-error 块显示 detail 并保留旧证据，与原 App.vue 行为一致。

## Document04 fixture 约定

第 04 章与第 03 章共享 `chapter-01?section=limits`：高/中/低位 fixture 写入 `limits.stratifications` 的 `risk_tier` 行，修复率写入 `limits.riskEvidence` 的 `failure-repair` 行。独立挂载时先 `market.loadCore()` 再 `market.loadSection('limits')`；每项缺失独立显示 `--`。

## Document05-09 章节组件约定（2026-09-16 frontend-component-split Phase B-05..B-09）

第 05 至 09 章均为 core 直出章节：独立挂载时 market.data = fixture 即可，无需 loadSection。第 09 章 meta.section = null，页面依赖已加载状态，不触发自己的预拉；NextSessionPanel(mode=summary) 读 market.nextSessionComparison。

### 事件时间显示

Document07EventsPage 的事件时间用纯 formatDateTime 并显式传入 preferences.effectiveTimeZone；fixture 的 publishedAt 必须带时区后缀（Z 或 +08:00），否则 parseTimestamp 按 '--' 处理，页面显示"时间未标注"。

### 09 章空态语义

assessment.state=insufficient 时页面显示：分数不足 / 暂无完整证据链 / 当前未返回已触发的风险否决 / 数据不足，等待新增证据。测试与 UI 均按这四个固定文案断言，改动文案需同步 Document09AssessmentPage.test.ts。

## 嵌套路由守卫与章节预拉（2026-09-16 frontend-component-split Phase C）

/dashboard 现为嵌套路由：父级 DashboardLayout，9 个 children 各带 meta.section。守卫在 router/guards.ts 的 registerRouterGuards(router) 工厂中注册，生产入口与测试共用。

### 守卫行为

- legacy hash（#document-N）一次性重写为 /dashboard/N。
- 进入 /dashboard/* 且 market.data 为空 → await market.loadCore()（阻塞，首次进入必须有核心数据）。
- 目标章节 meta.section 非空且未在 market.loadedSections → void market.loadSection(section)（不阻塞，fire-and-forget）。
- 07、09 两章 meta.section = null，不触发预拉。

### 章节写操作边界

章节组件唯一允许的 store 写通道是 emit 上抛：selectIndex（01 章选指数）与 refreshSection（03 章刷新）由 DashboardLayout 在 RouterView 的 slot props 上统一接线。剪贴板复制（01 章指数值/涨跌幅/复盘句、02 章验证项）为纯 UI 行为，组件内部消化，不经过 store。

### 测试挂载约定（更新）

- app.test.ts 挂 App 时必须 createRouter + registerRouterGuards（守卫不再挂在测试自建 router 上会直接导致 loadCore 不执行、页面停在 loading 态）。
- chart lifecycle 测试语义已更新：路由切换时旧章节组件卸载（dispose 其 echarts 实例）、新章节挂载（init 新实例），断言 init/dispose 累计次数（01→02→01 为 init 2→3→5、dispose 0→2→3）。
- 扶摇能力验证：使用脱敏 fixture 执行 `python -m src.market_environment.cli fuyao capability-probe --fixture tests/fixtures/market-environment/fuyao-market-data.json --as-of YYYY-MM-DD --path /tmp/fuyao-capability.sqlite3`。该命令不访问网络；报告为 `ineligible`/`unverified` 时不得填写批准 revision。
- 真实验证只能在盘后、显式本地隔离路径执行：`python -m src.market_environment.cli fuyao real-probe --allow-real --as-of YYYY-MM-DD --path /tmp/fuyao-real.sqlite3 --output /tmp/fuyao-real.json`，API key 仅来自 `MARKET_ENVIRONMENT_FUYAO_API_KEY`。缺 key、日期不一致、权限/限流错误均 fail closed。
- 回滚按数据集清除 `MARKET_ENVIRONMENT_FUYAO_<DATASET>_ENABLED` 或批准 revision；保留能力报告、任务元数据和同日期旧快照，不跨日期回填。Secret 不写入 values、日志、fixture 或 API 响应。
