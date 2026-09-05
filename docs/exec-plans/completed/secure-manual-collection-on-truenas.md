# TrueNAS 安全启用手工采集

## Stage（阶段）

实施与生产部署：OpenSpec `secure-manual-collection-on-truenas`。

## Status（状态）

`completed`

## Scope（范围）

- 将 TrueNAS `192.168.1.20` 上 `a-stock` Service 从匿名 NodePort 收回为 ClusterIP。
- 通过受认证的 SSH/kubeconfig 管理通道和仅绑定 `127.0.0.1` 的临时隧道访问 Dashboard。
- 在受保护网络边界内显式开启 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=1`。
- 原地复用现有单副本、不可变镜像、静态 PVC 和 SQLite；不启用 k3s 1.26 不支持的定时采集配置。

## Acceptance（验收）

- OpenSpec strict、部署测试、Helm lint/template 和 docs-contract full 通过。
- 升级前记录 Helm/release/工作负载/PVC 基线，并创建可读取的 SQLite 一致性备份。
- 生产 Service 为 ClusterIP 且不再暴露 `32001`；无其他 Ingress、hostPort 或代理暴露应用。
- 运行 Pod 仅定义一次手工采集开关且值为开启；镜像、单副本、安全上下文、PVC claim 与 snapshot path 保持不变。
- 通过仅监听本机回环地址的隧道验证 health、状态 GET、合法单项 POST、全量批次、日期校验和任务终态；关闭隧道后端口消失。
- 完成禁用写入口的回滚演练；任何回滚不删除或重建 PVC。

## Completion Evidence（完成证据）

- 用户已确认采用 ClusterIP + 临时认证隧道并明确授权实施部署。
- 线上基线：Deployment `a-stock` 为 `1/1`，镜像 `localhost/a-stock-market-environment:20260905-1904b66`；Service 为 NodePort `32001`；PVC `a-stock-data` 为 2Gi、Bound、Retain，静态路径 `/mnt/xiaomi/app-data/a-stock`；完整日期请求的 collection POST 返回 403。
- 管理网络验证：`192.168.1.20:6443` 从执行机连接超时；SSH TCP forwarding 返回 `administratively prohibited`，因此当前无法建立设计要求的仅回环浏览器隧道。
- 用户选择方案 1 后，TrueNAS middleware 已开启 TCP forwarding；`PermitOpen` 仅允许 `127.0.0.1:6443` 和 `172.17.182.246:80`，并保持 `GatewayPorts no`、`AllowAgentForwarding no`。应用和 API 回环隧道验证通过，其他目标被拒绝。
- Helm revision 1 完整 values/history 已通过临时 API 隧道读取；当前 image、PVC、单副本、NodePort、Ingress/CronJob 与手工开关基线已记录。
- SQLite 在线备份 `snapshots-before-secure-manual-20260905-1915.sqlite3` 保存于 TrueNAS 独立构建数据集，`PRAGMA quick_check=ok`，SHA-256 `575f3111eb9e7dc864678ede6b0fd6e068b8b146c5e942ddc1a832ed8675c60c`。底层卷可用约 420GiB，当前使用率 26%。
- 发布前门禁：部署清单测试 `7 passed`；Helm strict lint 与 Kubernetes 1.26 目标 values 渲染通过；OpenSpec strict、docs-contract full 和 `git diff --check` 通过。
- Helm revision 2 首次部署目标 values 成功；revision 3 完成手工开关禁用演练并验证 POST 403；revision 4 恢复最终启用状态。最终 Deployment `1/1`、Pod `Running`/0 重启、镜像不变，Service 为 ClusterIP `172.17.182.246` 且无 nodePort，PVC UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe` 未变化。
- 回环隧道内 `/api/health` 和 collection 状态 GET 成功，`manualRefreshEnabled=true`；隧道关闭后本机 `18001` 无监听，`192.168.1.20:32001` 拒绝连接。
- 单项 run `1d43139d1ed64cadb79738a170f53ff0` 对 `2026-09-04` core 返回 `success`，五指数各 280 条并按契约降级到东方财富历史 K 线。
- 五类 run `10bb9607b78a47b9bcc142ce5b93ef57` 返回 `partial`：core、breadth、limits、sectors 成功，activeDirection partial；来源、warning 和数据不足均原样保留。
- 历史 latest-only breadth 请求返回 422；并发 run 中首个 breadth 成功，第二个明确 `busy` 且引用活动 lease，没有产生重复 provider 调用。采集后 SQLite `quick_check=ok`、约 245KiB，PVC 使用率仍为 26%。
- 全量后端测试 `148 passed`；前端生产构建通过，保留既有大 chunk 警告。

## Remaining Gaps（剩余缺口）

- 应用级认证仍不在本次范围；日常访问依赖现有 SSH 登录组与临时隧道。TrueNAS 的 `tcpfwd` 是 SSH 服务级开关，`PermitOpen` 已限制目标，但所有获准 SSH 登录的账户均应纳入权限审计。
- 当前是周六，current-date provider 仍返回并保存 settled 数据；这是现有日期能力行为，本次未修改业务代码，后续应单独评估非交易日语义。
- 前端构建仍报告主 JS chunk 超过 500kB，该既有性能警告不影响本次部署。

## Next Step（下一步）

OpenSpec delta 已同步到主规格并归档；由操作者按 runbook 使用 `ssh -N -L 127.0.0.1:18001:172.17.182.246:80 admin@192.168.1.20` 临时访问，并另行跟踪应用级认证与非交易日采集语义。

## Operational Defaults（执行默认值）

- 维护窗口：本次授权后的当前窗口；允许单副本 `Recreate` 导致的短时中断。
- 首次采集：上海市场当天先运行 `core`，检查正常后运行五类批次。
- 回滚阈值：PVC 可用空间低于 20%、持续 provider 429、SQLite 锁/损坏、PVC/镜像/安全边界偏离基线，任一命中即先关闭写入口。
- 备份：使用 SQLite 在线备份语义，保存到 TrueNAS 专用 `REMOTE_IMAGE_DIR` 下的 release 备份目录；不提交仓库，保留到用户后续清理。
