# 修复市场广度真实数据源降级

## Stage

实现与验证

## Status

已完成

## Acceptance

- 东方财富主 `push2` 域连接失败或只返回受限分页时，上涨家数、下跌家数、平盘家数和涨跌幅中位数仍可从可审计降级链路得到。
- 市场广度只统计有效涨跌幅，不把缺失值伪造为 0；历史日期仍不复用当前快照。
- 当前日期判断统一使用 `Asia/Shanghai`，不受 API 进程所在机器时区影响。
- provider、服务层和 API 回归测试、前端生产构建及 docs-contract full 通过。

## Completion Evidence

- 定向回归：`19 passed`。
- 全量测试：`.venv\Scripts\python.exe -m pytest tests -q --basetemp .tmp-pytest\full-breadth-fallback`，`52 passed`。
- 前端构建：`npm run build --prefix apps/market-environment-dashboard`，构建成功。
- docs-contract：恢复并重连 `.githooks/pre-commit` / `pre-push` 后，`SKIP_PLAN_GATE=1` 运行 full 模式通过；环境变量仅用于让 gate 识别未暂存的新 plan，代码与文档映射检查正常通过。
- 真实 provider fallback：上涨 1678、下跌 3756、平盘 121、有效样本 5555、中位涨跌幅 -0.81%，耗时约 12 秒。
- 完整 API 请求：健康检查为 `ok`；`chapter01.breadth` 返回上涨 1552、下跌 3903、平盘 99、有效样本 5554、中位涨跌幅 -0.95%，`source=eastmoney-clist-delay`、`status=fallback`。
- `git diff --check`：通过。

## Remaining Gaps

- 主 `push2` 域被连接级拦截时，依赖完整股票明细的 `activeDirection` 和行业排名仍可能失败；本次只为上涨家数、下跌家数和平盘/中位数建立排序统计降级，未用汇总数据伪造个股或板块明细。
- fallback 遵守东方财富共享串行限流，首次完整章节请求约需十几秒；30 秒服务缓存内不会重复计算。

## Next Step

- 后续若要恢复主动方向和行业排名，需接入不同风控面的完整股票/行业明细源，并保持当前质量状态与缺失边界。
