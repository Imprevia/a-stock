# 发布盈亏日历 Fuyao 日线修复到 TrueNAS k3s

## Stage

生产发布与发布后只读验收完成。

## Status

completed-with-production-write。

## Acceptance

- 干净的受审提交只包含日线修复及相关文档。核验生产当前版本、PVC、Secret 引用、备份可恢复、无遗留 CronJob 或 Job。
- 按受控 `--component all` 流程发布并验证镜像、Ready Pod、NodePort 和数据库版本。候选完整清单只改变应用镜像，保持已有采集配置。
- 通过 LAN 和 Tailscale 对健康、盈亏日历和历史明细做只读验收。真实行情补齐属于用户发起的单独操作。

## Completion Evidence

- 干净的独立发布工作树使用提交 `31ceee356893539b36b547085b42c8a734f31896`。提交检查通过，含后端 111 项和前端 177 项。Helm strict lint、Kustomize 渲染、OpenSpec 严格校验和文档门禁通过。修复验收见[修复计划](fix-trading-pnl-fuyao-history.md)。
- 上线前备份为 PostgreSQL custom dump，21,837,777 字节，保存在仓库外私有发布包。隔离 PostgreSQL 16.4 单事务恢复后，Alembic `0009_trading_pnl`、台账 revision 和业务计数与现场一致。
- 上海时间 16:42 完成 Helm revisions 159（数据库）、160（服务）、161（完整发布）。Schema Job 的 Kubernetes 事件记载同一 UID `da879269-4595-4605-9a8a-1dad15785f46` 创建并完成。服务和完整发布阶段禁用 hooks。
- 镜像 `localhost/a-stock-market-environment:20261128-163242-31ceee3` 的归档 SHA-256 为 `c2aef41ae2d0d49ebd02358f378b520adf81165891322565115cfc3074fb32cb`，containerd manifest digest 为 `sha256:34b2c30d3100e5bbb1191d39e1f6be9c9ccc0b001813571f679c820d2cfa6c3a`。线上看板和 PostgreSQL 均为 1/1 Ready、0 重启。
- 完整 values 和 stored manifest 差异仅为应用镜像 tag。PostgreSQL StatefulSet、服务、PVC、业务 Secret 身份和 NodePort `32001` 通过前后对照。CronJob 和 Job 均为空，活跃 run/task/lease 为 `0/0/0`。采集与台账计数和 revision 前后一致。
- LAN 和 Tailscale 各通过 7 项针对盈亏日历的只读检查。另有 17 项 LAN 检查覆盖历史市场接口与盈亏日历。两个入口读取的 2026-01-21 状态一致，流水已录全，603019.SH 仍待补收盘价。

## Remaining Gaps

2026-01-21 的真实 Fuyao 收盘价和线上补齐结果待用户显式操作后核验。

## Next Step

在盈亏日历选择 2026-01-21，使用「从 Fuyao 补齐行情」重试该交易日。
