# 恢复 TrueNAS NodePort 直连

## Stage（阶段）

阶段 6：生产发布计划与授权门禁。仓库实施与离线验证已完成；生产基线、备份、发布、验证和回滚待另行授权。

## Status（状态）

`production-released / revision-5`

## Scope（范围）

- 将受版本控制的 TrueNAS values 从 revision 4 的 ClusterIP 保护入口改为固定 `NodePort:32001`，保留手工采集写开关为 `1`。
- 不改变不可变镜像、单副本、`a-stock-data` claim、`/data/snapshots.sqlite3`、Pod/容器安全上下文、关闭的 Ingress 与关闭的 CronJob。
- 文档明确记录：应用没有身份认证或 TLS，所有能路由到 `192.168.1.20:32001` 的客户端都可匿名触发 provider 调用和 SQLite 写入。
- 本阶段不得连接或修改 `192.168.1.20`，不得执行 SSH、kubectl、Helm upgrade、备份或真实采集。

## Acceptance（验收）

- 完整 TrueNAS values render 为 `NodePort`/`32001`，且 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1` 恰好出现一次。
- Helm render 证明镜像、单副本、PVC/SQLite 路径、安全上下文、Ingress/CronJob 状态不变，不产生 PVC 删除或替换。
- OpenSpec strict、Kubernetes 1.26 Helm lint/template、部署测试、docs-contract full 与 `git diff --check` 全部通过。
- 产品规格、架构、runbook、status 和 OpenSpec tasks 与已接受的匿名可路由网络边界一致。

## Deployment Candidate（部署候选）

唯一候选 values 为 `deploy/truenas/values-secure-manual-collection.yaml`，完整预期如下：

- image：`localhost/a-stock-market-environment:20260905-1904b66`，`IfNotPresent`
- replica：`1`
- service：`NodePort`，Service port `80`，nodePort `32001`
- persistence：existing claim `a-stock-data`，mount `/data`，SQLite `/data/snapshots.sqlite3`，keep `true`
- security：沿用 Chart 的 UID/GID/fsGroup `10001`、RuntimeDefault seccomp、只读根文件系统、禁止提权并 drop `ALL`
- ingress：disabled
- scheduled collection：disabled
- extraEnv：仅一项 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`

## Pre-deployment Baseline and Backup Checklist（发布前基线与备份清单）

以下项目必须在获准的维护窗口内完成并将输出追加到本计划，当前未执行：

- 确认节点和集群范围内 `32001` 未被占用；检查路由器/防火墙不存在公网端口映射，不得在无证据时声称设备或子网限制。
- 保存 `helm history` 与 revision 4 完整 values；保存 Service、Deployment、Endpoint/EndpointSlice、Pod 镜像和安全上下文。
- 记录 PVC 名称、UID、PV、容量和使用量，确认 `a-stock-data` 与 `/data/snapshots.sqlite3`；记录 Ingress/CronJob 均关闭。
- 使用 SQLite `Connection.backup()` 创建一致性备份到独立 TrueNAS 数据集；记录恢复路径、SHA-256，并对备份执行 `PRAGMA quick_check` 和只读查询。
- 对 revision 4 与候选 values 执行 Helm diff，拒绝任何 PVC 删除/替换，以及镜像、副本、安全上下文、claim、mount、SQLite 路径、Ingress 或 CronJob 的非预期变化。

## Authorized Release Procedure（获准后的执行顺序）

以下命令仅供维护窗口内、获得集群负责人明确授权后执行；本计划阶段不得提前执行或以输出猜测替代证据。

1. **基线与网络门禁**：在目标集群读取 `helm history`、revision 4 values 和资源快照；逐节点确认 `32001` 无监听/NodePort 冲突，并从预期 LAN 客户端验证路由。检查路由器、防火墙和 Tailnet/公网配置没有把该端口映射到公网；若无法取得 ACL 证据，记录边界为“所有实际可路由网络”。任一门禁失败即停止。
2. **一致性备份与恢复验证**：在应用仍运行时使用 Python `sqlite3.Connection.backup()` 将 `/data/snapshots.sqlite3` 备份到独立 TrueNAS 数据集；记录绝对路径、UTC 时间、文件大小和 SHA-256。对备份副本以只读方式执行 `PRAGMA quick_check`、schema 查询和一条精确日期快照查询；失败或 hash 未记录不得继续。恢复演练只在独立临时路径进行，不覆盖生产 PVC。
3. **渲染与差异门禁**：固定 chart、候选 values 和 Kubernetes 1.26.6 进行 `helm lint --strict`、`helm template`，再对 revision 4 与候选执行 `helm diff upgrade`。差异只允许 Service type/`nodePort` 和手工开关；出现 PVC 删除/替换、镜像/副本/安全上下文/claim/mount/SQLite 路径/Ingress/CronJob 变化，立即停止。
4. **单次发布**：执行一次 `helm upgrade`，等待唯一 Deployment `Ready`，确认 Pod 镜像 digest/tag、重启次数为 0、PVC UID 未变。禁止 uninstall、删除 PVC 或并行升级。
5. **验收与观察**：从预期 LAN 客户端验证 `/api/health`、页面 `/data-collection`、provider-free 状态 GET；提交一次上海市场当天且受支持的数据集，确认 HTTP `202`、collection run/task 合法终态、成功数据落盘且 warning 可解释。历史不支持日期必须仍返回 `422`。观察至少一个采集周期：Provider warning/限流、SQLite lock、任务耗时、Pod 重启、PVC 容量和 NodePort 可达性，并记录最终 Helm revision。

## Rollback Triggers and Order（回滚触发与顺序）

- 触发条件：健康探针失败、非预期公网可达、异常请求/Provider 压力、SQLite 锁或写入错误、PVC 异常增长、镜像/安全/存储不变量变化、采集终态非法。
- 第一动作：使用审阅后的 values 将 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`，等待 rollout，验证 POST 返回 `403` 且无新的 provider 调用；保留 NodePort 只读健康与快照读取。
- 第二动作：若仍需移除直连入口，恢复受保护的 revision 4 ClusterIP values（或记录的 Helm revision），确认 Service 无 `nodePort`。两个动作均复用原 `a-stock-data`，禁止 uninstall 或删除/替换 PVC。
- 回滚后复核 PVC UID、SQLite `quick_check`/历史读取、镜像、单副本、安全上下文和 Ingress/CronJob 状态，并保留备份和事件日志供复盘。

## Completion Evidence（完成证据）

- `openspec validate restore-truenas-nodeport-direct-access --strict`：通过，change valid。
- `helm lint --strict deploy/helm/a-stock`：通过，1 chart linted、0 failed。
- `helm template a-stock deploy/helm/a-stock --namespace a-stock --kube-version 1.26.6 -f deploy/truenas/values-secure-manual-collection.yaml`：通过；仅生成 NodePort Service 与单副本 Deployment，端口为 `32001`。
- 使用同一完整 values 加 `--set service.type=ClusterIP --set-json service.nodePort=null` 渲染 revision 4 基线：Deployment 与候选一致，Service 仅移除 nodePort 并恢复 ClusterIP；两者均不生成 PVC、Ingress 或 CronJob。
- `.venv/bin/python -m pytest -q tests/test_deployment_manifests.py`：`7 passed`。
- `.venv/bin/python scripts/check-docs-contract.py --mode=full`：通过。
- `git diff --check`：通过，无输出。

## Remaining Gaps（剩余缺口）

- 尚未获取 revision 4 在线基线、端口占用、网络可达边界或路由器/防火墙证据。
- 尚未创建并验证 SQLite 备份，也未执行 Helm diff、生产发布、LAN 验证、真实采集、观察或回滚演练。
- NodePort 是连通性而非认证/授权边界，流量为明文；长期仍需认证与 TLS 入口。
- 尚未获得本次生产维护窗口和“可执行上述命令”的明确负责人授权；在授权前本计划只能作为审核材料。
- 已获负责人授权并完成 revision 5 发布；公网映射/路由器 ACL 未能从集群主机取得，实际边界只能记录为所有可路由网络。

## Next Step（下一步）

下一步：持续观察 provider 降级、SQLite 锁、PVC 容量和 NodePort 可达性；补齐路由器/防火墙 ACL 证据，并长期接入认证与 TLS。若出现 P0，先将手工开关设为 `0`，再按本计划恢复 revision 4 ClusterIP。
