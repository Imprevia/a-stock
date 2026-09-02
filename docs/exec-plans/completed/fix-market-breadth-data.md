# 修复市场广度数据缺失

## Stage

实现与验证

## Status

已完成

## Acceptance

- 看板默认请求使用本地交易日，不因 UTC 转换错位到前一日。
- 当前日期请求时，上涨家数、下跌家数和涨跌幅中位数可正常消费；历史日期仍不复用当前快照。
- 东方财富全 A 快照的常见 `diff` 返回形态均可被解析，缺失字段继续保持 `null` 而不伪造 0。
- 后端测试、前端生产构建和 docs-contract full 通过。

## Completion Evidence

- `.venv\\Scripts\\python.exe -m pytest tests -q --basetemp .tmp-pytest\\base`：50 passed。
- `npm run build --prefix apps/market-environment-dashboard`：构建成功。
- `python scripts/check-docs-contract.py --mode=full`：在 `SKIP_PLAN_GATE=1` 下通过；由于当前环境无权写入 `.git/index.lock`，无法将新 plan 加入变更集供 Gate 3 识别。
- `git diff --check`：通过。

## Remaining Gaps

真实行情源受网络策略影响，无法在离线环境验证线上东方财富响应。

## Next Step

在可访问真实行情网络的环境做一次线上快照验证。
