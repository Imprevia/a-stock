# 部署当前版本到 TrueNAS k3s（2026-11-28）

## Stage（阶段）

受控部署和发布后验收完成。

## Status（状态）

completed-with-production-write

## Acceptance（验收）

- 将用户授权的已提交 HEAD `8f1ed87c517c46aead901931a47f8530feecd484` 部署到既有 TrueNAS k3s `a-stock` namespace / release。
- 绑定干净的发布源，冻结当前 values 并核对候选差异、两个历史 CronJob identity、namespace Job、PostgreSQL 和访问边界。
- 将 PostgreSQL 备份保存在仓库外，验证恢复和 `0009_trading_pnl` 迁移。受控 `--component all` 只执行一次 schema hook。
- 核对上线镜像、Ready 状态、PVC/Secret identity、现有配置、首页、市场接口和台账读取。发布验收使用只读请求。

## Completion Evidence（完成证据）

- 源 HEAD 初始工作树干净。节点 `ix-truenas` Ready，Dashboard 与 PostgreSQL 均 1/1，两个 PVC Bound，现有 IPv4 LAN NodePort `/api/health` 返回 200。
- 现场 Helm revision 152 deployed，两个历史 CronJob 与 namespace Job absent，活跃采集 run/task/lease 为 `0|0|0`。冻结 values 后渲染 database、service、all；常驻资源与旧 stored manifest 相比仅应用镜像 tag 变化。
- PostgreSQL 16.4 custom dump 为 21,817,515 字节，SHA-256 `b92824eb0484a3b10df9db809802eaa037aceaac6570bef66a03983337dfed8d`。已在隔离 PostgreSQL 恢复并从 `0008_collection_idempotency` 升级到 `0009_trading_pnl`，新增十张台账表，历史 run/task/snapshot/aggregate 计数仍为 `170/578/337/61`。
- 部署护栏测试 178 passed、台账和 API 等定向后端测试 45 passed、前端 174 passed，Vite build、Helm strict lint、Kustomize 离线渲染和 docs-contract full 通过。线上发布前 12 项只读检查通过。
- 以干净的独立 worktree 和完整 `REVIEWED_GIT_HEAD` 执行 `--component all`。上海时间 11:40–11:42 完成 revision 153（database）、154（service）和 155（完整 release），最后两步使用 `--no-hooks`。唯一 schema Job UID `05879a4e-3e11-416d-a42f-043daa265ce3` 经 watch 观测为 `Complete`、单次成功，随后由 Helm 清理。
- 镜像 `localhost/a-stock-market-environment:20261128-111522-8f1ed87`，archive SHA-256 `58785400cb986393c9d3d142edefa4e4f1b1ac1dfb0be0eeba61b795601463bc`，containerd manifest digest `sha256:bda1a64e99ab08b05633c7d3d4ff21e3c7e313aaf89197a384b13860adb0371a`。Dashboard 和 PostgreSQL 均 1/1 Ready、0 重启，Dashboard runtime imageID `sha256:6b73e548f7689e20e27a063bfa117f3bde162fef4b7fe405b614b7cbd4712239` 与构建配置一致。
- 完整 values 和 stored manifest 仅应用镜像变化。NodePort `32001`、PostgreSQL StatefulSet/Service、业务 Secret UID 与两个 Bound PVC identity 保持一致。CronJob/Job absent。线上 schema 为 `0009_trading_pnl`，十张台账表可读。台账 revision 为 0，期初待确认，交易 0 笔。市场数据计数 `170/578/337/61`，活跃采集 run/task/lease `0|0|0`。
- LAN 发布后检查 17 项全部 HTTP 200，覆盖健康、首页、OpenAPI、历史日市场概览与池、盈亏月历和日期 API。Chromium 在 390px 和 1440px 验证月历、日期明细和导入页，最小可见字号 14px，页面无横向溢出。线上 Pod 用合成截图识别四行，状态和金额符合预期，耗时 2.17 秒。
- 补验 Tailnet 入口。`http://gyt.tail0007b1.ts.net/` 经 NGINX `80` 转发到 `192.168.1.20:32001`，首页、健康、盈亏日历页和盈亏月历 API 均返回 HTTP 200。同域名 HTTPS `443` 转发至 DeepSeek Harness，现有反代配置保持原样。
- 本地构建因 Debian 默认源吞吐过低重试，最终通过临时只读挂载镜像源配置使用阿里云 Debian 与 PyPI 镜像站。Debian 包保留签名校验，挂载配置未进入运行镜像。镜像构建与本地健康检查完成后才开始集群发布。备份、清单及验证记录保存在仓库外的私有发布目录。

## Remaining Gaps（剩余缺口）

- `npm ci` 报告 15 项依赖安全公告（9 中危、3 高危、3 严重），本次发布使用已提交锁文件。验证范围为部署护栏和功能相关测试、隔离数据库恢复迁移与线上只读验收，全仓 pytest 未运行。

## Next Step（下一步）

从 LAN 访问盈亏日历，待用户确认台账期初后录入历史流水。
