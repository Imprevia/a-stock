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
- 2026-09-15 16:30 的 live CronJob 已触发，但冻结的 `20260906-005226-2075b6e` 镜像在独立 PVC 上于 `create_collection_run` 报 `sqlite3.OperationalError: attempt to write a readonly database`；当前仓库版本的 WAL 初始化修复已增加 reopen-write 回归测试（`.venv/bin/python -m pytest tests/test_market_environment_snapshot_store.py -q`：12 passed）。
- 2026-09-15 本机从含未提交变更的工作树构建 `linux/amd64` 候选 `localhost/a-stock-market-environment:20260915-210509-6f3cdb5-dirty`；镜像 ID `sha256:3918d366f46e57237530b3758e3543ea89a5326d0f9a2baf3570eafbdfe52033`，构建输入校验 `cc4a3d46028531dc22a274f3c84a6a0928774b1fcf1eaf40e0fcc91e203f2f8e` 前后一致。容器内独立 SQLite 两次 reopen-write 通过，本机 host 网络 `/api/health` HTTP 200；rootless 端口映射探测连接重置。镜像未传输、导入或应用到线上。
- `bash -n scripts/apply-truenas-operator-override.sh`、`git diff --check`、`python3 scripts/check-docs-contract.py --mode=full` 和 `openspec validate enable-truenas-scheduled-market-collection --strict --json` 均通过。

## Remaining Gaps（剩余缺口）

- 正式 Helm 生产发布仍需要独立 Gate B action authorization、Gate B 证据接受和 Gate C operation authorization。
- 交易日 CronJob 自然触发与 provider 结果仍需按既有 direct-apply 计划观察。
- 线上 operator override 仍冻结在旧镜像；需先构建并审核新的不可变镜像，再按 exact-resource 授权流程更新 CronJob，不能直接修改生产资源或复用旧镜像验证结果。
- 本地新镜像带 `dirty` tag：在代码提交与 exact packet 审阅、生产导入后的 containerd digest 绑定、独立操作/回滚授权完成前，不得作为可直接发布的冻结镜像。

## Next Step（下一步）

保留正式 Helm 的 Gate B action authorization、Gate B 证据接受和 Gate C operation authorization；先完成新镜像构建/离线验证和 exact-resource 更新授权，再在下一个交易日窗口观察自然触发，随后按授权决定是否迁回正式链路并归档相关计划。
