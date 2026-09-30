# 统一 Provider 请求层

## Stage

Implementation

## Status

completed-with-unrelated-environment-test-gaps

## Acceptance

- Tencent、Baidu、Sina、TDX 和 Eastmoney provider 请求经过统一 host policy，具备超时、有限退避、Retry-After、请求门、请求预算和失败分类。
- 每个 host session 使用稳定的现代随机 UA；并发相同 GET 请求单飞，成功响应按安全 key 使用短 TTL，日期不同不得共享缓存。
- 可重试失败达到阈值后进入短熔断并由既有 provider fallback 接管，冷却后只执行一次受控探测；403 不盲目重试。
- 现有 provider 路由、质量状态、精确日期、失败留存和 feature flag 保持兼容。
- focused/full pytest、OpenSpec strict、docs-contract fast/full 通过；真实 provider smoke 仅在授权隔离盘后环境执行。

## Completion Evidence

- `.venv\Scripts\python.exe -m pytest -q tests/test_provider_http.py tests/test_trading_rule_platform.py tests/test_market_environment_providers.py tests/test_market_environment_tdx_daily.py`：**105 passed**。
- `.venv\Scripts\python.exe -m pytest -q`：**643 passed, 103 skipped, 4 failed**；失败为既有 `mcp` 可选依赖缺失 1 项，以及 Windows 环境运行 bash 部署脚本导致路径错误 3 项，未涉及本变更代码。
- `openspec validate unify-provider-http-collection --strict`：通过。
- `.venv\Scripts\python.exe scripts/check-docs-contract.py --mode=full`：通过（代码 3 / 文档 5 / plan 0）。
- `.venv\Scripts\python.exe -m src.trading_system.cli docs sync-check`：通过（330 documentedRules / 49 executableRules）。
- `.venv\Scripts\python.exe -m src.trading_system.cli rules validate`：通过（1 rule set / 49 rules）。
- `.venv\Scripts\python.exe -m src.trading_system.cli rules coverage`：通过（330 documentedRules / 49 executableRules）。
- `git diff --check`：通过，仅有 Windows 行尾转换提示。

## Remaining Gaps

- 真实网络环境中的供应商封锁策略、出口质量和生产冷却阈值仍需盘后隔离 smoke 观察。
- 代理部署、供应商切换和跨进程分布式限流不在本阶段范围。
- 全量测试仍受本机缺少 `mcp` 依赖和 Windows bash 路径兼容问题影响；需在 CI/Unix 或补齐依赖后复核。

## Next Step

进入 OpenSpec archive 流程；生产启用前按 runbook 进行授权的盘后网络 smoke，并记录 host 请求预算、冷却探测和实际 provider 质量。
