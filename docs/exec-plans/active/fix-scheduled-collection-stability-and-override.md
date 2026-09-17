# 修复定时采集稳定性与 override 路径

## Stage（阶段）

修正 GYT-52 状态文案漂移、降低 SQLite 测试与运行时连接开销、修复本地读取性能测试的偶发失败，并把 TrueNAS 1.26 的调度收敛到 Helm fail-closed 的 schedule-only 入口。

## Status（状态）

`completed-without-production-write` · 稳定性、测试性能和 operator override 修复已完成；未执行正式 Helm 发布或其他生产写操作。

## Acceptance（验收）

- 不把离线授权评估误写成生产 CronJob 激活或回退的执行授权。
- SQLite WAL 仅在存储初始化时设置，普通连接不重复切换 journal mode；现有 snapshot/preference 行为不变。
- 全量测试不再出现 materialized local read 的偶发性能失败，部署相关与存储相关测试通过。
- TrueNAS 1.26 调度由 Helm release 统一管理，完成时区/镜像/安全上下文校验、server dry-run、apply 和 exact readback；缺失或漂移时 fail closed。
- `docs-contract`、OpenSpec 严格校验和受影响测试通过；不得删除或绕过专用调度入口的安全门（`enabled=false / suspend=true` 默认、`--release-suspended` / `--activate-schedule` / `--disable-schedule` rollback 引用）。

## Completion Evidence（完成证据）

- `SnapshotStore` 将 WAL 设置移到初始化阶段，并新增单事务 materialized state 读取；service 复用 limits 快照和批量 active lease，避免重复 SQLite 连接/锁等待。
- materialized local read 性能测试直接 seed 精确 core/breadth 快照并构造物化聚合，不再把完整 collection 编排写事务计入延迟断言；原有 `<0.5s` 断言保留。
- TrueNAS 1.26 调度清单已合并到 Helm chart 的 `controller` strategy，默认只读 + server dry-run，`--release-suspended` 后 exact readback；拒绝时区/镜像/安全上下文/资源漂移。
- 部署与调度联合测试：`193 passed`；market environment service/store：`39 passed`；全量离线 pytest：`592 passed, 2 warnings`（约 298 秒）。此前两个 `<0.5s` 失败均已通过。
- 2026-09-15 16:30 的 live CronJob 已触发，但冻结的 `20260906-005226-2075b6e` 镜像在独立 PVC 上于 `create_collection_run` 报 `sqlite3.OperationalError: attempt to write a readonly database`；当前仓库版本的 WAL 初始化修复已增加 reopen-write 回归测试（`.venv/bin/python -m pytest tests/test_market_environment_snapshot_store.py -q`：12 passed）。
- 2026-09-15 本机从含未提交变更的工作树构建 `linux/amd64` 候选 `localhost/a-stock-market-environment:20260915-210509-6f3cdb5-dirty`；镜像 ID `sha256:3918d366f46e57237530b3758e3543ea89a5326d0f9a2baf3570eafbdfe52033`，构建输入校验 `cc4a3d46028531dc22a274f3c84a6a0928774b1fcf1eaf40e0fcc91e203f2f8e` 前后一致。容器内独立 SQLite 两次 reopen-write 通过，本机 host 网络 `/api/health` HTTP 200；rootless 端口映射探测连接重置。镜像未传输、导入或应用到线上。
- `git diff --check`、`python3 scripts/check-docs-contract.py --mode=full` 和 `openspec validate --changes --strict` 均通过。

## Remaining Gaps（剩余缺口）

- 正式 Helm 生产发布仍需本次操作责任人书面确认，并在 plan 的 Completion Evidence 中记录 release/namespace/镜像 digest 与 catch-up 行为后再调用专用调度入口。
- 交易日 CronJob 自然触发与 provider 结果仍需按既有 direct-apply 计划观察。
- 线上 Helm release 的 CronJob 合并与孤立存储清理仍待执行窗口；在完成前不得恢复旧 operator override 路径。
- 本地新镜像带 `dirty` tag：在代码提交与 exact packet 审阅、生产导入后的 containerd digest 绑定、独立操作/回滚授权完成前，不得作为可直接发布的冻结镜像。

## Next Step（下一步）

保留正式 Helm 的专用调度入口（`--release-suspended` / `--activate-schedule`）与 `--disable-schedule` rollback 流程；完成合并计划中的 Helm 接管和孤立资源清理后，在下一个交易日窗口观察自然触发，再按操作责任人确认激活。
