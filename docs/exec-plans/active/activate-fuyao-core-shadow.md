# 启用 Fuyao Core Shadow 执行计划

## Stage（阶段）

Stage 0 — 规划已被 `activate-fuyao-core-provider` 替代；本文件仅保留历史审计记录，不再等待 apply。

## Status（状态）

`superseded-by-activate-fuyao-core-provider`（2026-10-19：用户决定不启用 shadow、不做跨 provider 对账，改为将 Fuyao v2 直接作为 capability-gated 正式首选源；本计划未实施）

## Scope（范围）

- 以 shadow-only 方式验证 Fuyao `fuyao-market-v2` 的五个核心指数历史 K 线与直接成交额，不改变现有正式 provider 链。
- 固定运行时不变量：`core.enabled=false`、`core.approvedRevision=fuyao-market-v2`，仅在 reviewed off/on 配置之间切换 `core.shadowEnabled`。
- shadow 只写脱敏、有限、精确日期的对账证据，不得成为正式快照、聚合来源或 capability 批准依据。
- 至少观察五个完整已结算交易日；成交额口径或其他差异未解释清楚时，正式 Fuyao core 切换继续关闭。
- 不改变公开 API、数据库 schema、交易规则、调度所有权、其他数据集、Secret/PVC/Service 或普通 GET 的 provider-free 边界。

## Acceptance（验收）

- OpenSpec strict 校验通过，delta spec 明确 shadow 非破坏性、精确日期/脱敏证据和独立 cutover 决策门槛。
- 离线测试证明 Fuyao shadow 成功或失败都不改变正式 core 候选、同日留存、正式快照来源和任务终态；五指数证据完整性可确定性判定。
- reviewed shadow-off/on 完整 Helm renders 使用同一镜像、同一资源集合，且唯一 off/on 语义差异为 `MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED: 0 -> 1`。
- Helm render 不包含 application-owned CronJob/Job；Secret 只引用不渲染，Service、PVC、数据库、调度、其他数据集和正式 core 开关保持不变。
- 真实生产 preflight、off 收敛、shadow-on、额外 provider-backed collection、观察读取和回滚分别取得明确授权后才可执行。
- 至少五个完整已结算交易日形成脱敏 review packet；任何 unresolved mismatch、`degraded`、`insufficient`、跨日期、缺指数或成交额口径不明均阻止正式切换。

## Completion Evidence（完成证据）

- 已创建 OpenSpec change：`openspec/changes/activate-fuyao-core-shadow/`。
- 已完成 `proposal.md`：限定 shadow-only、正式切换关闭及五日观察边界。
- 已完成 `specs/market-data-collection-management/spec.md`：新增三项 requirement，覆盖非破坏性/可回滚、精确日期/脱敏证据、独立连续证据决策。
- 已完成 `design.md`：确定 paired off/on overlays、typed acquisition 单一事实源、成交额 basis 归因、activation/cutover 分离和逐步授权。
- 已完成 `tasks.md`：包含离线实现与验证、文档同步，以及必须另行授权的生产激活和五日观察任务。
- 规划校验：`openspec status --change activate-fuyao-core-shadow` 显示 `4/4 artifacts complete`；`openspec validate activate-fuyao-core-shadow --strict` 通过。
- 文档门禁：环境不存在 `python` 命令，未将该次启动失败计为通过；改用 `python3 scripts/check-docs-contract.py --mode=full` 后通过（代码 0 / 文档 2 / plan 1）。
- `git diff --check` 通过。
- 本规划阶段未调用真实 Fuyao、未读取或修改 Secret、未连接生产数据库、未执行 Helm/kubectl 写操作、未触发市场数据采集。
- 2026-10-19：用户否决 shadow 与对账路径；后续规划转移到 `docs/exec-plans/active/activate-fuyao-core-provider.md` 和 OpenSpec change `activate-fuyao-core-provider`，旧 change 保留但不得 apply。

## Remaining Gaps（剩余缺口）

- 本计划已终止且不会进入 apply；其中所有 shadow、对账和五日观察任务均取消。
- 正式 Fuyao core 的实现、验证与外部授权缺口由替代计划 `activate-fuyao-core-provider` 跟踪。
- 旧 OpenSpec change 保留作审计记录，不得将其 `tasks.md` 作为当前实施清单。

## Next Step（下一步）

不要 apply 本计划或 `activate-fuyao-core-shadow`。如需继续，显式请求 `$openspec-apply-change activate-fuyao-core-provider`，并以替代计划的授权边界为准。
