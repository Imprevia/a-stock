## Context

市场环境服务已经把 `core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 统一到 `CollectionCoordinator`。协调器为每次执行创建持久化 run/task，按数据集独立捕获失败，使用 `(dataset, as_of)` SQLite lease 去重，并在成功后重建 materialized aggregate。当前触发入口只有受开关保护的 HTTP POST 和需要显式日期的 CLI。

仓库的生产部署边界是单镜像、单副本 k3s Deployment 和一个保存 `snapshots.sqlite3` 的 PVC，同时提供 Kustomize 与 Helm。另一个 GitHub Actions 盘后工作流运行交易规则 snapshot/evidence，但其临时 Artifact 不连接部署实例的 PVC，因此不能填充看板数据。

该系统面向盘后复盘，目标是每天稳定准备本地数据而不是提供实时行情。调度必须继续遵守单机 SQLite、东方财富串行请求门、精确日期、失败保留和无认证 HTTP 写入口默认关闭等既有约束。

## Goals / Non-Goals

**Goals:**

- 在上海时区工作日结算后自动触发五类数据采集。
- 复用现有协调器、存储、lease、失败隔离和聚合重建能力。
- 让一个数据集失败时其他成功数据仍落盘，并在现有数据管理页可见和可补采。
- 为 k3s Kustomize 和 Helm 提供一致、可配置、可关闭的 CronJob 部署方式。
- 为调度运行提供结构化日志、明确退出码、并发禁止、超时和历史 Job 保留策略。

**Non-Goals:**

- 不增加 APScheduler、Celery、Redis 或常驻本机调度服务。
- 不通过 GitHub Actions 或公网 HTTP 写入部署实例。
- 不改变普通市场环境 GET、手工采集 API 或前端页面契约。
- 不解决多节点共享 SQLite；部署仍以单节点/单 PVC 边界运行。
- 不在本次引入交易所节假日日历；节假日运行必须失败安全且不得把其他日期数据写成当天数据。
- 不自动反复重采 partial 批次；失败项由页面或显式 CLI 补采。

## Decisions

### 1. 使用 Kubernetes CronJob 调用同镜像 CLI

新增 `batch/v1` CronJob，使用与 Dashboard Deployment 相同的镜像、`MARKET_ENVIRONMENT_SNAPSHOT_PATH` 和 PVC，直接运行 Python CLI。CronJob 不调用 HTTP POST，因此不需要打开 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED`，也不会扩大当前无认证写接口的攻击面。

相比在 FastAPI 进程内加入调度器，CronJob 的触发记录、并发策略、超时和失败状态由 Kubernetes 管理，应用重启不会丢失调度定义。相比 GitHub Actions，CronJob 能直接访问部署实例的持久卷。相比另建 worker 服务，它不需要新增常驻进程或队列。

### 2. 新增内部日期解析的 scheduled-refresh CLI

新增 `python -m src.market_environment.cli snapshots scheduled-refresh` 命令。命令在 Python 内按 `Asia/Shanghai` 获取当前日期和时间，周末返回结构化 `skipped` 且退出 0；结算时间之前拒绝运行；有效工作日把当天日期和默认五类数据交给现有 `CollectionCoordinator.collect()`。CLI 允许测试注入时间，并可提供显式数据集选择，但 CronJob 默认不遗漏任何一类。

CronJob 默认使用 `spec.timeZone: Asia/Shanghai` 和 `30 16 * * 1-5`，即工作日 16:30，晚于当前默认结算边界 `15:10`。Helm 暴露 enabled、schedule、timeZone、suspend、deadline、资源和历史保留配置；Kustomize 提供相同安全默认值。

标准 CronJob `spec.timeZone` 作为稳定能力要求 Kubernetes/k3s 1.27 或更高版本，因此 Helm Chart 的 `kubeVersion` 同步提升到 `>=1.27.0-0`。这比为旧集群静默退化为控制器本地时区更可验证；低于该版本的部署需要先升级集群，而不能假设 cron 使用上海时区。

不使用 shell `date` 拼接 `--as-of`，避免镜像 shell、UTC 和跨平台差异。现有 `snapshots refresh --as-of` 保留用于指定日期的人工诊断和补采。

### 3. 节假日依赖精确日期验证失败安全

第一版不增加交易所日历依赖。周一至周五的交易所节假日仍会触发一次协调器运行，但所有 provider 结果必须继续通过精确 `quality.asOf` 和日期能力校验。无法证明属于当天的数据记为 `failed-retained` 或 `failed-missing`，不得把上一交易日或最新快照写入当天。

该选择会在节假日留下一个可审计的失败或 partial run，但比维护可能过期的本地节假日表更可靠，也不阻止各数据集独立判断。未来若引入权威交易日历，可在 scheduled-refresh 日期解析边界增加 no-op，不改变 CronJob 或协调器契约。

### 4. partial 是完成采集但失败的 Job，不自动整批重试

CLI 输出单行 JSON，包含 trigger、runId、asOf、父状态和五个 task 的状态、来源、样本数、耗时与 warning。`success` 和 `skipped` 返回 0；`partial`、`failed` 或输入/边界错误返回非零。CronJob 设置 `backoffLimit: 0`，避免因一个不稳定 provider 自动重新采集全部成功数据；失败项继续通过 `/data-collection` 的行级按钮补采。

Kubernetes Job 状态和容器日志提供运维可见性，SQLite run/task 让同一结果在数据管理页可见。无需新增状态 API 或前端字段。

### 5. 使用两层并发保护

CronJob 设置 `concurrencyPolicy: Forbid`，防止上一次计划 Job 未结束时再启动一个 Job，并设置 `activeDeadlineSeconds` 限制异常长运行。现有 coordinator lease 继续处理 CronJob 与手工 CLI/HTTP 同时触发、Pod 异常退出以及同日期重复请求，重复任务不得产生第二次 provider 调用。

`Forbid` 只约束同一个 CronJob，SQLite lease 才是采集语义的最终保护。两者都保留，因为仅依赖 lease 会产生无意义的额外 Pod，仅依赖 CronJob 又无法覆盖人工触发。

### 6. CronJob 继承部署的存储和安全边界

CronJob 挂载同一 PVC 到相同路径，使用相同非 root UID/GID、`RuntimeDefault` seccomp、只读根文件系统、drop all capabilities、`/tmp` emptyDir 和 `automountServiceAccountToken: false`。镜像、拉取策略、节点选择、容忍、亲和性和资源限制在 Helm 中可与主 Deployment 分别覆盖。

当前 local-path `ReadWriteOnce` PVC 和 SQLite 只承诺单节点运行。调度 Pod 由 PVC node affinity 放置到卷所在节点；多节点、多副本或网络文件系统协调仍需后续架构 change。

### 7. 调度默认启用但可以显式暂停或关闭

原生 Kustomize 清单包含启用的 CronJob，满足部署后自动准备数据的产品目标。Helm Chart 默认启用 scheduled collection，并允许通过 `marketEnvironment.scheduledCollection.enabled=false` 不渲染资源，或通过 `suspend=true` 保留资源但停止新 Job。回滚时优先 suspend/disable 调度，不需要删除 SQLite 数据。

手工 HTTP 写开关保持默认关闭；内部 CronJob 是否启用与该开关相互独立。

## Risks / Trade-offs

- [交易所工作日节假日仍会触发] -> 精确日期校验禁止跨日期落盘，运行以失败/缺失留痕；后续可在不改协调器的前提下接入权威交易日历。
- [CronJob 与 Dashboard 同时访问 SQLite] -> 使用 WAL/短事务和现有 dataset lease；保持单节点 PVC 与单副本边界，并验证读取在采集期间仍不阻塞。
- [partial 返回非零会把 Kubernetes Job 标记失败] -> 这是有意的运维信号；SQLite 中保留成功 task 和父批次细节，且 `backoffLimit: 0` 防止无差别重试。
- [CronJob 配置时间早于结算边界] -> scheduled-refresh 再次校验 `MARKET_ENVIRONMENT_SETTLEMENT_TIME` 并拒绝执行，避免仅依赖部署配置。
- [镜像升级期间 CronJob 使用不同版本] -> CronJob 与 Deployment 共享同一不可变 image tag 配置；发布文档要求同步升级并避免 `latest` 用于正式环境。
- [现有 Kubernetes 1.24-1.26 部署不支持稳定 timeZone 字段] -> 将 Chart 最低版本提升到 1.27，并在部署前置检查中明确验证 k3s 版本。
- [单次采集超过调度窗口] -> `concurrencyPolicy: Forbid` 和 active deadline 防止重叠；任务失败状态与 lease 过期恢复继续由现有存储处理。

## Migration Plan

1. 创建 active exec plan，并先更新市场环境产品规格、架构、runbook 和状态文档。
2. 扩展 CLI，增加 scheduled-refresh 日期/时间边界、结构化结果和退出码测试，并保持现有 refresh 命令兼容。
3. 增加 Kustomize CronJob，复用镜像、PVC、环境变量和安全上下文；用 `kubectl kustomize` 验证渲染。
4. 增加 Helm values 与条件模板，覆盖启用、禁用、暂停、时区、schedule、deadline、资源和 Pod 调度配置；执行 `helm lint` 与 `helm template`。
5. 用 fixture provider 验证 success、partial、failed、周末 skipped、结算前拒绝和并发 lease；确认普通 GET 在采集时仍只读本地数据。
6. 部署时先以 suspend 模式渲染并手工创建一次 Job 验证 PVC、外网和日志，再解除 suspend。
7. 回滚时将 CronJob suspend 或在 Helm 中关闭；保留 CLI、collection 记录和 SQLite 快照，不做破坏性数据迁移。

## Open Questions

无。第一版固定使用部署内 CronJob、工作日 16:30 上海时区、五类数据全量触发、partial 不自动整批重试和节假日失败安全语义。
