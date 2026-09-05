## Context

已上线实例是 TrueNAS `192.168.1.20` 上的 k3s 1.26、Helm release `a-stock` revision 1。Dashboard 为单副本、非 root 容器，SQLite 位于静态 PVC；集群没有 Ingress Controller，Service 以 HTTP NodePort `32001` 暴露。当前部署显式设置 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`，所以匿名 collection POST 返回 403。

应用的 collection API 没有用户身份、角色或请求级授权。打开开关后，调用者可以触发五类 provider 请求、占用 CPU/内存/出口带宽、创建 collection run/task 并写入 PVC。现有 `(dataset, as_of)` lease、东方财富串行请求门和日期校验限制并发与数据错误，但不构成访问控制，也不能阻止持续滥用。

本 change 只产出规划工件。没有修改代码、Helm values、集群资源或 release，也没有验证目标机当前网络策略、SSH 跳板或 kubeconfig 的实际授权人列表。

## Goals / Non-Goals

**Goals:**

- 让明确获授权的运维人员能够使用现有 `/data-collection` 页面和 collection POST。
- 在没有应用认证的前提下，消除局域网匿名访问写接口的路径。
- 最小化 Helm 和运行时配置变化，不更换镜像、不迁移数据、不增加数据库。
- 保留单副本、PVC、lease、provider 限流、日期能力和失败隔离不变量。
- 提供可验证、可快速撤销且不损失 SQLite 数据的发布步骤。

**Non-Goals:**

- 本次不实现应用用户、RBAC、OIDC、API token、审计数据库或多租户。
- 本次不执行生产部署，不修改 TrueNAS 防火墙、SSH 配置、kubeconfig 或 Helm release。
- 不把 CORS、前端按钮状态或不可猜 URL 当作安全控制。
- 不启用 k3s 1.26 不支持的 CronJob `spec.timeZone`；盘后定时采集保持现状。
- 不扩展数据集、provider、API payload、SQLite schema 或多副本能力。

## Decisions

### 1. 推荐使用 ClusterIP 加临时认证隧道

实施时把 `service.type` 从 `NodePort` 改为 `ClusterIP` 并清空 `service.nodePort`。操作者使用其已有的 kubeconfig 执行 `kubectl -n a-stock port-forward service/a-stock 18001:80 --address 127.0.0.1`；若 kubectl 只能在管理 VM 上运行，则通过已有 SSH 身份把该回环端口转发到操作者本机。浏览器仅访问本机回环地址。

该方案将认证和授权交给已有的 Kubernetes API/SSH 边界，无需把未实现的应用认证当作前提。`--address` 必须固定为 `127.0.0.1`（或明确需要的 IPv6 loopback），不得使用 `0.0.0.0`。隧道是临时会话，不是常驻公网入口；关闭终端即撤销访问。

目标 TrueNAS 的 SSH 初始配置禁用了 TCP forwarding，用户已选择最小化启用方案。持久配置通过 TrueNAS middleware 管理，不直接修改生成的 `sshd_config`；开启后使用 `PermitOpen` 将所有认证账户的转发目标限制为 k3s API 回环端口和当前应用 ClusterIP:80，保持 `GatewayPorts no` 与 `AllowAgentForwarding no`。这不会赋予新的 SSH 登录资格，但现有获准登录账户都能使用这两个目标，因此 SSH 登录组仍是必须审计的剩余权限边界。

代价是 `192.168.1.20:32001` 不再提供局域网直连，普通只读用户也必须使用隧道。若匿名只读页面必须继续常驻，应选择带路径授权的反向代理备选，而不是保留同一个无认证 NodePort，因为当前应用无法只保护 POST。

### 2. 仅通过显式运行时配置开启写能力

保持应用默认行为和代码不变，在目标环境 values 的 `extraEnv` 中显式设置 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`。渲染后的 Deployment 必须只出现一个同名环境变量，避免重复键顺序产生歧义。配置 Secret 不需要用于该布尔值；若未来引入凭证，必须使用 Secret 且不得写入仓库 values。

部署仍使用当前不可变镜像，避免把网络边界调整、功能代码和数据迁移混在同一变更窗口。Chart 模板若不能可靠表达环境配置，应先在独立开发阶段补齐并通过离线渲染测试，不能在目标集群临时 patch 后把实际配置留在版本控制之外。

### 3. Helm 发布以当前状态快照和受控 values 为准

实施前读取并保存 `helm get values --all`、`helm history`、Deployment/Service/PVC 描述和当前镜像摘要。环境 values 必须完整保留现有静态 `persistence.existingClaim`、单副本、镜像 tag、关闭 Ingress、关闭 k3s 1.26 定时采集以及安全上下文，仅改变 Service 暴露和手工采集开关。

先在本地执行 `helm lint`、目标 values 的 `helm template` 和 `helm diff`（若插件可用），确认 PVC 不被删除或重建、Deployment 仍为单副本、Service 不再有 nodePort、CronJob 不被意外启用。再执行一次 Helm upgrade 并等待 rollout。禁止为了方便使用未经复核的 `--reuse-values` 或在线 `kubectl set env` 作为最终状态。

### 4. PVC 原地复用并在变更前做一致性备份

变更不修改 `MARKET_ENVIRONMENT_SNAPSHOT_PATH`、volumeMount、PVC claim 或 SQLite schema。发布前记录文件大小和可用空间，并使用 SQLite 在线备份机制或在短暂停止写入后复制数据库；不得直接复制一个可能正在写入的 WAL 数据库而忽略 `-wal` / `-shm`。

Deployment 使用 `Recreate` 且单副本，短时不可用是预期。Helm rollback 不应删除 PVC；回滚和卸载是不同操作，禁止用卸载 release 作为常规回滚。即使手工采集失败，旧成功快照也必须按现有 `failed-retained` 语义保留。

### 5. Provider 风险由限权、现有协调器和操作规程共同约束

隧道将触发权限限制为持有 kubeconfig/SSH 权限的操作者；应用继续依赖 dataset/date lease 合并重复任务，东方财富请求继续单进程串行，403 不盲目重试，429/5xx 仅有界退避。单次验证先采集一个数据集，再在确认日志、PVC 空间和 provider 质量后采集全部五类。

手工采集不保证 provider 成功。`partial`、`degraded`、`insufficient`、`failed-retained` 和 `failed-missing` 都是有效且必须保留的结果；验收不得要求把缺失值伪造为 0，也不得使用 `--force` 把最新快照写成历史日期。

### 6. 回滚优先关闭能力，再恢复暴露方式

出现异常调用、provider 压力、SQLite 锁等待或容量快速增长时，第一步将运行时开关恢复为 `0` 并 rollout，阻止新的 POST；活动任务按现有超时/lease 语义收敛。第二步按需 `helm rollback` 到已记录 revision。PVC 和 SQLite 备份保持不动，不执行清库。

是否重新开放 NodePort 是独立业务决策。若需恢复原来的匿名只读页面，可在手工写开关已确认关闭后恢复 revision 1 的 Service 形态；不得在手工写能力仍开启时恢复无认证 NodePort。

## Alternatives Considered

### 持久认证反向代理

在应用前部署 NGINX/Traefik/oauth2-proxy 等入口，TLS 终止后对 collection POST 要求身份认证和操作者角色，后端 Service 保持 ClusterIP。该方案能同时支持常驻只读访问与受保护写操作，但需要选择身份源、证书、凭证轮换、路径匹配、真实客户端 IP 和高可用策略，超出当前“未假设已有认证”的最小变更。只有用户确认常驻访问、身份源和 TLS 运维责任后才应选用。

### 保持 HTTP 写入口关闭，使用一次性 CLI Job

通过 Kubernetes 权限创建一次性 Job，直接调用现有 CLI 并挂载同一 PVC。攻击面最小且无需网页 POST，但不提供数据管理页按钮，目标从“开启手工模式”降级为“受控补采”。适合偶发运维补数。

### NodePort 加源 IP 限制

主机防火墙、路由 ACL 或 `loadBalancerSourceRanges` 可以作为纵深防御，但 NodePort 的真实流量路径和源地址保留受 kube-proxy/CNI 配置影响，且 IP 不是用户身份。除非先在目标环境验证规则覆盖 IPv4/IPv6、同网段横向流量和回滚通道，否则不能作为唯一授权边界。

### 直接开启现有 NodePort

拒绝。任何能访问局域网端口的客户端都可触发写操作和外部 provider 调用；CORS 只约束浏览器，不约束 curl 或恶意客户端。

## Risks / Trade-offs

- [隧道权限过宽] -> 使用最小 Kubernetes RBAC，仅授予目标 namespace 的 pod/service get/list 与 port-forward 所需权限；SSH 账户禁用共享凭证并审计登录。
- [ClusterIP 使原有读者失去直连] -> 发布前由用户确认是否接受；不接受则转入认证反向代理方案，不能偷偷保留匿名写入口。
- [错误 values 导致 PVC 变化] -> 渲染与 diff 必须证明 existingClaim、mountPath 和 reclaim 行为不变；先备份，再 upgrade。
- [手工重复触发产生 provider 压力] -> 权限限缩、先单项验证、现有 lease 和串行门共同约束；监控 run/task、429/403、耗时与出口错误。
- [SQLite 并发或空间耗尽] -> 保持单副本，验证 WAL/锁告警、PVC 使用率和写入结果；达到预设空间阈值时关闭开关并停止新采集。
- [隧道绑定到非回环地址] -> 命令和验收显式检查监听地址；发现 `0.0.0.0` 或管理 VM 局域网地址立即终止进程。
- [回滚恢复 NodePort 时开关仍开启] -> 回滚顺序固定为先验证 POST 403，再恢复网络暴露；两项不得合并为未检查的单步操作。

## Migration Plan

1. 用户审核并选择访问模型：接受“仅操作者临时隧道”，或要求进入持久认证反向代理的独立设计；确认普通局域网只读直连是否可以下线。
2. 新建 active exec plan，先同步产品规格、`docs/architecture.md` 和 `docs/runbooks.md`；不得在文档事实源更新前修改 Helm 配置。
3. 盘点目标 release、完整 values、镜像、Service、Deployment、PVC、存储空间、SSH/kubeconfig/RBAC 持有人和可用回滚 revision；创建并验证 SQLite 备份。
4. 在受版本控制的 TrueNAS 环境 values 中保留现有集群兼容配置，仅把 Service 改为 ClusterIP，并显式注入 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`。
5. 本地运行 docs-contract、部署清单测试、Helm lint/template，并审查差异：无 NodePort、无意外 Ingress/CronJob、PVC claim 和镜像不变、环境变量唯一。
6. 在批准的维护窗口执行 Helm upgrade；等待 Deployment ready，验证健康检查、本地快照读取和 PVC 挂载，确认 `192.168.1.20:32001` 已不可达。
7. 以最小权限身份建立绑定 `127.0.0.1` 的 port-forward/SSH 隧道；验证状态 GET 显示手工采集已启用，未通过隧道不存在访问路径。
8. 先对上海市场当天触发一个受支持数据集，轮询至终态并核对日志、provider quality、SQLite/PVC；再触发五类批次并接受可解释的 partial/degraded 结果。
9. 观察一个约定窗口，记录调用者、runId、日期、数据集、provider 错误、任务耗时、PVC 使用率和回滚判据；关闭隧道后确认本机端口不再监听。

## Rollback Plan

1. 通过当前受控管理通道将 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 应用到 Deployment，并确认 collection POST 返回 403。
2. 终止本次建立的精确 port-forward/SSH 子进程，不按进程名批量终止其他会话。
3. 若发布本身异常，执行 `helm rollback a-stock <previous-revision> --namespace a-stock --wait`，再验证 Deployment、Service 和 PVC；仅在写开关已关闭后才允许恢复 NodePort。
4. 保留 PVC、collection 记录和备份。只有确认数据库损坏且用户批准时才从备份恢复；普通 provider 失败不触发数据恢复。

## Verification

- 网络：Service 为 ClusterIP、无 `nodePort`；节点 `32001` 不再提供应用；port-forward 只监听 loopback，关闭后端口消失。
- 配置：运行 Pod 中手工采集开关为开启且仅定义一次；镜像摘要、单副本、安全上下文、snapshot path、existingClaim 和定时采集关闭状态符合基线。
- 数据：升级前后 SQLite 文件可读，历史快照和 run/task 仍在；PVC 未重建，容量有余量。
- API：隧道内 health 与状态 GET 成功；合法当前日期单项 POST 返回 202；非法历史 latest-only 请求返回 422；禁用开关的回滚演练返回 403 且不调用 provider。
- 任务：轮询 run 至 `success` / `partial` / `failed`，核对五类 task 独立状态、失败保留、重复 lease 和聚合重建。
- provider：记录 source、quality、warning、429/403、耗时；任何失败都表现为 `degraded` / `insufficient` 等既有状态，不以 0 代替缺失。
- 回滚：上一 Helm revision 可用，关闭写能力不删除 PVC，恢复后健康和历史读取正常。

## Open Questions

以下关键决策必须由用户审核，未确认前不得进入开发或生产部署：

1. 是否接受取消 `192.168.1.20:32001` 的局域网直连，改为仅授权操作者使用临时隧道？
2. 哪些人员/设备应持有 SSH 或 namespace 级 port-forward 权限，现有 kubeconfig 是否需要收敛 RBAC？
3. 若普通只读页面必须常驻访问，身份源、TLS 域名/证书和反向代理运维责任分别由谁承担？
4. 可接受的发布维护窗口、最大中断时间、观察窗口和 PVC 空间告警阈值是什么？
5. SQLite 备份的目标位置、保留期、加密与恢复责任人是什么？
6. 第一次验证允许触发哪些数据集和日期，provider 调用失败或限流达到什么条件立即回滚？
