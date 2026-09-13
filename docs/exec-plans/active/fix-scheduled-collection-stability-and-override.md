# 修复定时采集稳定性与 override 路径

## Stage（阶段）

修正 GYT-52 状态文案漂移、降低 SQLite 测试与运行时连接开销、修复本地读取性能测试的偶发失败，并把 TrueNAS 1.26 operator override 收敛到 fail-closed 的 schedule-only 入口。

## Status（状态）

`completed-without-production-write` · 稳定性、测试性能和 operator override 修复已完成；未执行正式 Helm 发布或其他生产写操作。

## Acceptance（验收）

- GYT-52 文案反映 2026-09-10 Gate A GO；不把 Gate A GO 误写成 Gate B/Gate C 生产授权。
- SQLite WAL 仅在存储初始化时设置，普通连接不重复切换 journal mode；现有 snapshot/preference 行为不变。
- 全量测试不再出现 materialized local read 的偶发性能失败，部署相关与存储相关测试通过。
- TrueNAS 1.26 override 只允许修正已存在的 exact 非 Helm-owned CronJob，完成时区/PVC/镜像校验、server dry-run、apply 和 exact readback；缺失或漂移时 fail closed。
- `docs-contract`、OpenSpec 严格校验和受影响测试通过；不得删除或绕过 Gate B/Gate C 安全门。

## Completion Evidence（完成证据）

- `SnapshotStore` 将 WAL 设置移到初始化阶段，并新增单事务 materialized state 读取；service 复用 limits 快照和批量 active lease，避免重复 SQLite 连接/锁等待。
- materialized local read 性能测试直接 seed 精确 core/breadth 快照并构造物化聚合，不再把完整 collection 编排写事务计入延迟断言；原有 `<0.5s` 断言保留。
- TrueNAS 1.26 清单与 `scripts/apply-truenas-operator-override.sh` 已固定 exact namespace/CronJob/image/PVC，默认只读 + server dry-run，`--apply` 后 exact readback；拒绝 Helm ownership、时区/PVC/安全上下文/资源漂移，sudo 使用 `sudo env KUBECONFIG=...`。
- `tests/test_truenas_operator_override.py`：`14 passed`；部署与 override 联合测试：`193 passed`；market environment service/store：`39 passed`；全量离线 pytest：`592 passed, 2 warnings`（约 298 秒）。此前两个 `<0.5s` 失败均已通过。
- `bash -n scripts/apply-truenas-operator-override.sh`、`git diff --check`、`python3 scripts/check-docs-contract.py --mode=full` 和 `openspec validate enable-truenas-scheduled-market-collection --strict --json` 均通过。

## Remaining Gaps（剩余缺口）

- 正式 Helm 生产发布仍需要独立 Gate B action authorization、Gate B 证据接受和 Gate C operation authorization。
- 交易日 CronJob 自然触发与 provider 结果仍需按既有 direct-apply 计划观察。

## Next Step（下一步）

保留正式 Helm 的 Gate B action authorization、Gate B 证据接受和 Gate C operation authorization；待既有 direct-apply 计划的下一个交易日窗口观察自然触发后，再按授权决定是否迁回正式链路并归档相关计划。
