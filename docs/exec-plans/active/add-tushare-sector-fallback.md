# 接入 Tushare 行业板块独立回退执行计划

## Stage（阶段）

Stage 0 — OpenSpec 规划完成；待 Fuyao 通用 promotion 能力就绪后实施 Tushare transport、adapter、routing 和默认关闭部署配置。

## Status（状态）

`planned-awaiting-implementation` · proposal/spec/design/tasks 已完成；当前 token 尚未证明具备 `ths_index`、`ths_daily`、`moneyflow_ind_ths` 全部权限，未执行任何真实 Tushare 请求或生产写入。

## Scope（范围）

- 通过共享 transport gateway 增加 `sectors-tushare-ths` 官方 JSON POST adapter 和 exact `trade_date` 合并校验。
- 固定顺序为 Eastmoney primary → Eastmoney delayed → Tushare THS → Fuyao THS；未满足 capability gate 时零 I/O 并继续后续来源。
- 只映射已证明的 code/name/changePct/mainNet/leader；amount、mainNetPct、upCount、downCount 始终为 `null`。
- 补充 JSON body 凭据回显脱敏、默认关闭开关、approved revision、Secret 引用、fixture/real probe 契约；不接入网页爬虫或 TDX 派生行业。

## Acceptance（验收）

- Transport 测试证明 body/auth digest 隔离、token 不进入日志/provenance/cache key、POST 默认不缓存、权限错误不盲重试。
- Tushare fixture/adapter 测试覆盖权限失败、错日/混日、重复身份、缺页缺行、单位换算、排序稳定性、缺失字段和完整 fallback 顺序。
- Helm lint/template 与 docs-contract full 证明 Tushare 默认 disabled、Secret 只引用不渲染，调度/Scrapling/enrichment 保持关闭。
- 只有三接口权限、exact-date、字段单位和限流证据全部合格，才允许生成 eligible report 并由通用 promotion 命令晋升。

## Completion Evidence（完成证据）

- `/home/gyt/a-stock/openspec/changes/add-tushare-sector-fallback/` 已包含 proposal、design、两份 delta spec 和 tasks。
- `openspec validate add-tushare-sector-fallback --type change --strict --no-interactive` 通过；`git diff --check` 通过。
- `.venv/bin/python scripts/check-docs-contract.py --mode=full` 通过（代码 0 / 文档 3 / plan 2）。
- 当前仅完成规划产物；实现、离线测试和部署渲染结果待 apply 阶段回填。

## Remaining Gaps（剩余缺口）

- 当前 token 权限不足，不能执行或授权 Tushare 生产 fallback；真实 probe 应输出 `ineligible` 并保持开关关闭。
- Fuyao 通用 capability promotion 是前置依赖；不能重复实现或绕过其事务/脱敏门禁。
- 代码、文档同步、全量测试、OpenSpec strict 和 docs-contract full 待下一阶段。

## Next Step（下一步）

先使用 `$openspec-apply-change activate-fuyao-sector-fallback` 完成通用 promotion 边界，再使用 `$openspec-apply-change add-tushare-sector-fallback` 实施 Tushare 适配器和 routing。
