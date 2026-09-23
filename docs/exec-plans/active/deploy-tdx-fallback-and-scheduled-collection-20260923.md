# 部署 TDX fallback 与盘后定时采集

## Stage

生产部署与调度恢复

## Status

completed-final-image-activation-observation-pending

## Acceptance

- 目标固定为 Helm release `a-stock`、namespace `a-stock`、TrueNAS k3s `1.26.6+k3s-6a894050-dirty`。
- 先保存当前失败 Job、Helm values、镜像 tag/digest 和 CronJob 状态，再通过受控入口停用现有 active CronJob。
- 服务使用包含已验证 TDX daily-package parser 的不可变新镜像，Dashboard rollout、PostgreSQL、PVC 和 NodePort 不漂移。
- `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED=1` 只在 Eastmoney breadth 双路径失败后启用 TDX fallback；activeDirection 仍遵守未排序包的 fail-closed 规则。
- 使用同一新镜像创建 Helm-owned suspended CronJob，确认 exact manifest 和运行时镜像后，再按明确 catch-up 策略激活。
- 激活后记录首个 Job、每个 dataset 的质量状态、provider warning、数据库运行状态和 PVC 不变量；失败必须保持 `failed-missing`/`failed-retained`，不得跨日期补齐。

## Completion Evidence

- 2026-09-23/24 只读诊断：当前 CronJob `a-stock-data-collection` 为 active，schedule `30 16 * * 1-5`，旧镜像为 `20260923-185132-9a4910f`，containerd manifest digest 为 `sha256:8673aa5f24c55f3c95f0e67a5ccb5a57df47b13563bc84db3e6c8a9a4a3d23f2`；旧采集结果证明 TDX 派生 activeDirection 可写入，但暴露出 API schema 未接受 `fallback-derived` 的兼容缺口。
- TDX 2026-09-18 隔离 probe 已证明包日期、53,214 行、沪/深/北覆盖和名称/成交额字段；原始记录存在成交额逆序点，因此 activeDirection fallback 保持拒绝。
- 18:40 首次 `--disable-schedule` 按 fail-closed 规则拒绝直接删除 active retained CronJob，并将 exact resource 补偿为 suspended；18:41 重跑成功，Helm revision 37，CronJob 已读回 absent。
- 18:48 `--component service` 成功，Helm revision 38；新镜像 `localhost/a-stock-market-environment:20260923-184206-9a4910f`，containerd manifest digest `sha256:8673aa5f24c55f3c95f0e67a5ccb5a57df47b13563bc84db3e6c8a9a4a3d23f2`；Dashboard/PostgreSQL Ready，`/api/health` 返回 `{"status":"ok"}`，Deployment 读回 TDX 开关为 `1`。
- 18:53 `--component all` 完成 Helm ownership 收敛，revision 41；PostgreSQL StatefulSet/Service/PVC、schema migration Job、Dashboard/Service 均在 stored manifest，调度保持 disabled/absent。
- 18:54 `--release-suspended` 成功，revision 42；exact CronJob `a-stock-data-collection` 为 Helm-owned、`suspend=true`、schedule `30 16 * * 1-5`、`concurrencyPolicy=Forbid`、deadlines `1800/3600`、TDX 开关为 `1`，未创建 provider-backed Job。
- 18:55 `--activate-schedule` 成功，revision 43；preflight 与 pre-write 两次 `next-schedule` 窗口校验均通过，下一触发为 `2026-09-24 16:30 Asia/Shanghai`，写后 exact read-back 确认 `suspend=false`，未创建补跑 Job。
- 激活后核验：Dashboard/PostgreSQL 为 `1/1 Ready`，`a-stock-data` 与 PostgreSQL PVC 均 `Bound`，镜像 tag 为 `20260923-185132-9a4910f`，`/api/health` 返回 `{"status":"ok"}`；provider-free `/api/market-environment/data-collection` 无 active task/lease。
- 本地验证：`.venv/bin/python -m pytest tests -q` 为 `673 passed, 3 skipped, 2 warnings`；`.venv/bin/python -m src.trading_system.cli docs sync-check` 通过；`python3 scripts/check-docs-contract.py --mode=full` 通过；`openspec validate add-tdx-daily-package-fallback --strict --no-interactive` 通过；Helm lint 与 `bash -n` 通过。
- 19:05 通过已启用的手工采集 API 仅触发 `breadth` 的精确日期 `2026-09-23` 验证，run `653ef7f509f9468c80b211a122381135` 成功；来源 `tdx-daily-package`，观测 `51,921`，保留 Eastmoney 连接失败 warning，任务无 active lease。
- revision 44/45 通过父提交的 reviewed disable packet 停用并删除旧 retained CronJob；revision 46/47/48 完成前一版服务发布和 Helm ownership 收敛，随后发现 `fallback-derived` schema 兼容问题。
- revision 51/52 再次按 fail-closed 规则停用并删除 active CronJob；revision 55 使用修复后的镜像 `localhost/a-stock-market-environment:20260924-000048-188a2d9`、containerd manifest digest `sha256:c615af6199b53c42df4abd3350dfc7347f39dba8e9220c2e499e28f3aa9cbbb1` 完成 Dashboard rollout 和完整 Helm manifest 收敛。
- revision 56 `--release-suspended` 成功；exact CronJob 为 Helm-owned、`suspend=true`、schedule `30 16 * * 1-5`、`concurrencyPolicy=Forbid`、deadlines `1800/3600`、TDX 派生开关为 `1`，未创建 provider-backed Job。
- revision 57 `--activate-schedule` 成功；preflight 与 pre-write 两次 `next-schedule` 窗口校验通过，下一触发为 `2026-09-24 16:30 Asia/Shanghai`，写后 exact read-back 确认 `suspend=false`，未创建补跑 Job。
- 最终只读验收：Dashboard/PostgreSQL 为 `1/1 Ready`，两个 PVC 为 `Bound`，`/api/health` 返回 `{"status":"ok"}`；`/api/market-environment?as_of=2026-09-23` 返回 `activeDirection` 来源 `tdx-daily-package-derived`、质量 `fallback-derived`、文档 06 为 `partial`，`/api/market-environment/data-collection` 无 active task/lease。

## Remaining Gaps

- 首个自然 Job 尚未到触发时间；下一次触发为 `2026-09-24 16:30 Asia/Shanghai`。
- 行业映射覆盖为 `0.0`，生产看板只能显示股票榜，方向聚集保持 `unverified`；`sectors` 仍在 Eastmoney 双路径失败时保持 `failed-missing`，不得把 activeDirection 派生能力扩展到 sectors。
- 工作树当前 clean，生产写入使用受控 deployment/schedule 入口；未提交运行时产物或凭据。

## Next Step

在 `2026-09-24 16:30 Asia/Shanghai` 后观察首个自然 Job、TDX 请求结果、`breadth`/`activeDirection` 的 source/quality/warning 与 PostgreSQL collection run；若 activeDirection 仍因行业映射覆盖不足而无方向聚集结论，保持股票榜可用、方向聚集 `unverified` 的 fail-closed 结果。
