# 修复沪市指数数据不足

## Stage（阶段）

行情降级源修复与验证

## Status（状态）

`completed`

## Scope（范围）

修复上证指数（`sh000001`）和中证500（`sh000905`）在 mootdx/百度路由歧义后降级到腾讯历史 K 线时成交额为 0、量价状态显示“数据不足”的问题。

## Acceptance（验收）

- 使用显式沪市指数 `secid` 的历史 K 线降级源返回收盘价、成交量和成交额。
- 上证指数和中证500正常响应时不再因成交额缺失显示“数据不足”。
- 保留数据源 warning、日期回退和错误处理语义。
- 新增适配器测试，现有全量测试、前端构建和 docs contract 通过。

## Completion Evidence（完成证据）

- 修复百度/mootdx 沪市指数歧义后的成交额缺失：新增新浪指数 K 线适配器，并以腾讯实时成交额校准历史成交量单位。
- 保留东方财富显式 `secid` 作为后备源，腾讯历史 K 线作为最后降级源。
- 自动化测试：`.venv\\Scripts\\python -m pytest tests -q` → `16 passed`。
- 真实接口验证：上证指数 `amountRatio5=1.06`、`amountRatio20=0.97`；中证500 `amountRatio5=1.07`、`amountRatio20=0.91`，两者均为 `sina-kline`，量价状态为“量价平稳”。
- Docs contract：`SKIP_PLAN_GATE=1 python scripts/check-docs-contract.py --mode=full` 通过；仅因本计划已归档且当前工作树没有 active plan 变更而使用仓库允许的显式 Gate 3 逃生口。

## Remaining Gaps（剩余缺口）

- 行情源仍受网络可用性影响；全部源不可用时继续返回 503。

## Next Step（下一步）

后续仅需关注新浪/腾讯行情源可用性，并在市场广度迭代中创建新计划。
