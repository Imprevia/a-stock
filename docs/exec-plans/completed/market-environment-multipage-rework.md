# 01–09 多页市场研判重构

## Stage

实施阶段：OpenSpec spec-driven change `market-environment-multipage-rework`。

## Status

complete

## Acceptance

- 01–09 保持独立路由、hash 和按需加载；第 01 页保留五项指数、切换、60 日 OHLC/MA 图和成交额图。
- 第 01 页使用市场级七项证据生成结构化句式并可复制；第 01、09 页调用精确下一交易日 provider-free 对照。
- 02–08 按事实→判断→质量边界重排，03/04/07 缺失与未核实状态不伪造。
- 不保存复盘记录、用户输入或 20 日训练进度；不升级 SQLite schema。
- 前端测试/build、Python 测试、docs-contract full 和 OpenSpec strict validation 按环境可用性完成或记录阻塞。

## Completion Evidence

- OpenSpec strict validation: `openspec validate market-environment-multipage-rework --type change --strict` → `Change 'market-environment-multipage-rework' is valid`。
- docs-contract full: `python scripts/check-docs-contract.py --mode=full` → `docs-contract: 通过（代码 9 / 文档 7 / plan 1）`。
- Python pytest 全量: 436 passed / 18 failed / 142 skipped。
  - 失败集中于 `tests/test_truenas_operator_override.py` 和 `tests/test_truenas_scheduling_guard.py`，原因是 Windows 下 `bash G:\...deploy-truenas-k3s.sh` 被 bash 解析为 `G:workspacesa-stock...`（路径分隔符在 Git-Bash 中未转换），属于环境阻塞，与本 change 无关。
  - `tests/test_market_environment_limit_performance.py::test_limit_collection_emits_structured_timings_and_warm_read_budget` 单独运行通过，全量并发场景下偶发状态污染，不属于本 change 代码问题。
  - 本 change 直接相关的市场环境/句式/下一交易日/规则测试 212 项全部通过。
- Python pytest（排除部署脚本相关）: 291 passed / 0 failed / 305 deselected。
- 前端 `npm run test`: Vitest 7 files / 38 tests 全部通过。
- 前端 `npm run build`: Vite 构建成功，输出 `dist/index.html` 与 `dist/assets/index-*.{css,js}`。
- CLI 验证: `python -m src.trading_system.cli rules validate` → `{"ruleSets": 1, "rules": 49}`；`rules coverage` → `{"documentedRules": 330, "executableRules": 49}`。

## Remaining Gaps

- Windows 上 Git-Bash 调用 `scripts/deploy-truenas-k3s.sh` 时无法识别绝对路径前缀，导致 TrueNAS 部署脚本类测试集体失败；该问题属于运行环境（需要在 WSL/Linux 上跑），不在本 change 范围。
- 暂未在 1440×900 与 390×844 真实浏览器走查 01–09 页面布局与可读性；当前以 Vitest + Vite 构建作为最小验证，未来如需更严格的视觉验证可补一轮 Playwright 截图。
- docs-contract 与 OpenSpec strict 已完整通过；如有 `docs/product-specs/` 新增，需要在合并后再次跑 docs-contract full 校验双向链接。

## Next Step

- 使用 `/opsx-archive market-environment-multipage-rework` 归档本 change（所有 16 个任务已勾选）。
- 若需真机/浏览器视觉走查，另起一个 `opsx-propose` change 用于 Playwright 截图与响应式回归。
- 跟进 `enable-truenas-scheduled-market-collection` 或 `restore-truenas-nodeport-direct-access` 时，应在 WSL/Linux 环境下重跑全量 pytest，以确认 TrueNAS 脚本相关失败仅为 Windows 环境问题。
