# 默认开启市场数据手工采集

## Stage（阶段）

调整手工采集访问开关的默认值，并同步安全边界、运行说明和回归测试。

## Status（状态）

`completed`

## Goal（目标）

让未配置 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 的本地服务默认允许数据采集页面发起单项或全部采集，同时保留环境变量显式关闭写入口的能力。

## Scope（范围）

- 更新产品规格、架构、runbook、仓库状态和 OpenSpec 主规格中的默认策略。
- 将后端手工采集开关默认值由关闭改为开启。
- 更新 API 测试，覆盖未设置变量时默认开启和显式设置 `0` 时关闭。
- 验证后端测试、前端相关测试与构建、OpenSpec 和 docs-contract。

不包含身份认证、授权、CSRF 防护或公网部署安全增强。

## Acceptance（验收）

- 未设置 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 时，状态接口返回 `manualRefreshEnabled=true`，合法 collection POST 可创建任务。
- 设置 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 时，页面动作保持禁用，collection POST 返回 403 且不启动 provider 工作。
- 日期能力、运行中任务和数据集限制继续控制单项及全部采集按钮。
- 产品规格、架构、runbook、状态和 OpenSpec 与代码行为一致。
- 相关测试、构建和 `python scripts/check-docs-contract.py --mode=full` 通过。

## Completion Evidence（完成证据）

- 后端全量测试：`.venv\Scripts\python.exe -m pytest tests -q`，`124 passed, 3 skipped`。
- 前端测试：`npm test --prefix apps/market-environment-dashboard`，`11 passed`。
- 前端生产构建：`npm run build --prefix apps/market-environment-dashboard` 通过；保留既有 ECharts bundle 大小告警。
- OpenSpec：`openspec validate market-data-collection-management --type spec --strict` 通过。
- 运行接口：未设置开关时 `/api/market-environment/data-collection` 返回 `manualRefreshEnabled=true`。
- 浏览器：`/data-collection` 的“全部重新采集”按钮为 enabled，页面不再显示“手工采集未启用”。
- 文档门禁：`scripts/check-docs-contract.py --mode=full` 通过；使用隔离临时索引对本次未提交变更执行 fast gate，`代码 2 / 文档 6 / plan 1` 通过。
- 差异检查：`git diff --check` 通过。

## Remaining Gaps（剩余缺口）

- 无认证外部部署必须显式设置 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`；认证能力仍未实现。
- OpenSpec 全库严格校验仍有其他既有 capability 的占位 Purpose 问题；本次修改的 `market-data-collection-management` 已单独通过。

## Next Step（下一步）

提交后归档本计划；对外部署前显式关闭无认证写入口，后续另建认证授权 change。
