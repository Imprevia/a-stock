# 市场数据采集管理

## Stage（阶段）

实现数据集独立采集、状态管理、聚合快照和数据采集页面。

## Status（状态）

`completed` · OpenSpec change `manage-market-data-collection` 的 39 项任务已全部完成。

## Goal（目标）

为盘后市场环境看板提供独立的数据采集控制面，使核心指数、市场广度、涨跌停生态、行业板块和容量方向可以单独或一键采集；任一数据集失败不得阻止其他成功结果保存，普通看板只读取本地快照而不在用户请求中同步访问外部 provider。

## Scope（范围）

- SQLite collection run/task、核心指数子项和聚合响应持久化。
- 五类数据独立采集、精确日期隔离、lease 复用、失败保留和部分成功汇总。
- 异步采集 API、开发期开关、CLI 复用和 provider-free 状态查询。
- `/data-collection` 页面、单项重新采集、一键全部重新采集、核心指数明细和移动端适配。
- 现有市场环境查询接口的本地快照优先读取和兼容性验证。
- 产品规格、架构、runbook、状态、测试、浏览器 QA 和 docs-contract 证据。

不包含自动盘后调度、Redis、多 Pod 协调、完整身份认证、单指数独立重试和交易规则 validated 状态变化。

## Work Phases（工作阶段）

- [x] OpenSpec proposal、design、spec 和 tasks 完成并通过 strict validation。
- [x] 文档事实源和 active plan 更新。
- [x] SQLite collection state、核心指数和聚合快照实现。
- [x] 五类数据 collection coordinator、失败隔离和日期边界实现。
- [x] 异步 API、CLI 复用、能力开关和查询路径切换。
- [x] 数据采集页面、轮询、单项/全部采集和响应式实现。
- [x] 后端/前端测试、浏览器 QA、OpenSpec 和 docs-contract 完成。

## Acceptance（验收）

- 数据采集状态页不调用 provider，即使所有行情源不可用仍可打开。
- `core`、`breadth`、`limits`、`sectors` 和 `activeDirection` 独立执行；一个失败时其他成功结果仍提交，父批次为 `partial`。
- 核心指数显示五个子项；单指数失败时保留其他指数，同日期旧值可以显式 `failed-retained`。
- 单项按钮只采集目标数据集；一键按钮覆盖五类数据；重复点击不产生重复 provider 调用。
- 失败采集不覆盖同日期最后成功快照，不跨日期回填。
- 成功任务后重建并原子保存聚合响应；普通 GET 不自动启动采集，warm read 小于 500ms 且 provider 调用数为 0。
- 手工采集默认关闭；启用后按数据源日期能力校验，盘中数据标记 provisional。
- `/data-collection` 桌面和 390px 移动视口无页面级横向溢出、控件重叠或不可读状态。
- focused/full pytest、前端测试/build、浏览器 QA、OpenSpec strict 和 docs-contract full 全部通过。

## Completion Evidence（完成证据）

- 后端：`.venv\\Scripts\\python.exe -m pytest tests -q`，`97 passed`。
- 前端：`npm test`，`9 passed`；`npm run build` 通过。
- 浏览器：桌面 partial 场景确认 `sectors` 失败时其他四类数据保持可用，核心指数可展开五个子项；390px 全页截图无横向裁切或控件重叠。
- 截图：`test-results/data-collection-desktop-partial.jpeg`、`test-results/data-collection-mobile-390.png`。
- OpenSpec：`openspec validate manage-market-data-collection --strict` 通过。
- 文档门禁：`.venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full` 通过（代码 11 / 文档 5 / plan 1）。
- 代码差异：`git diff --check` 无 whitespace error。

## Remaining Gaps（剩余缺口）

- 自动盘后调度、完整认证和多节点任务队列仍是明确非目标，后续 change 单独处理。
- 前端构建仍有 ECharts 主 bundle 大于 500 kB 的既有告警，不影响本次功能与验收。
- 当前工作区中的看板默认日期改动保持原样，本计划未回退或重新归属该改动。

## Next Step（下一步）

归档 OpenSpec change；后续评估盘后调度和有认证的生产写入口。
