# 发布入账后盘后盈亏计算到 TrueNAS k3s

## Stage

生产发布与只读验收完成（2026-11-28，上海时间）。

## Status

completed-with-production-write。已按用户授权将 `a44cbe5bbdeb797824cb9bc4b7fdd9aafc61d211` 发布到既有 `a-stock` release。

## Acceptance

- 冻结候选提交和现场 Helm values，保存 PostgreSQL 备份并在隔离实例演练恢复与 `0010_pnl_calculation` 迁移。
- 使用普通 Helm 发布入口执行迁移和应用更新，核对镜像、Ready Pod、NodePort、PVC 和 Secret 引用。
- 通过 LAN 和 Tailscale 只读检查首页、健康和盈亏接口，核对既有台账计数。

## Completion Evidence

- 推送门禁通过，后端 164 项、前端 181 项。发布前生产为 Helm revision 161，Alembic `0009_trading_pnl`，Dashboard 和 PostgreSQL 均为 1/1 Ready，Job 与 CronJob 为空。
- 生产 PostgreSQL custom dump 已保存在仓库外私有发布目录，SHA-256 为 `4b63b1eb8f28d54798ca7065bff9109351a133e459c75af3b6eb5f8b101d57ee`。

- 21,838,185 字节的 custom dump 在隔离 PostgreSQL 16.4 中单事务恢复，并从 `0009_trading_pnl` 迁移到 `0010_pnl_calculation`，验证三个新表。
- 普通 `--component all` 于 19:09 完成。Helm revisions 162、163 和 164 分别执行数据库迁移、服务更新和完整清单收敛。迁移 Job UID `e4d5c1f3-b915-431e-83f7-b727ce436d62` 对应创建与完成事件，后续两个阶段禁用 hooks。
- 镜像 `localhost/a-stock-market-environment:20261128-190311-a44cbe5`，镜像归档 SHA-256 `b4db6ad523b3f056ff678fda26ba1a2197e6e1e61df8bd6bd3693b8da9a055ee`，containerd manifest digest `sha256:4eecd72e093a32c44306d243fe207e9c834fcb4293c80187165e470fa02b14f5`。
- 两个 Pod 均 1/1 Ready、0 重启。完整 values 与清单仅切换应用镜像标签，资源 UID、PVC、业务 Secret 和 NodePort `32001` 一致，Job 和 CronJob 为空。
- LAN 和 Tailscale 各通过 9 项 GET 检查，包含直接打开导入与明细路由、OpenAPI、月历与日期明细金额和状态一致，以及不存在批次的预期 404。既有台账和采集表计数、台账 revision 前后一致，新表为空。

## Remaining Gaps

生产验收为只读检查。真实截图入账、计算提交和 Fuyao 请求由实际使用时触发。

## Next Step

发布及只读验收完成。
