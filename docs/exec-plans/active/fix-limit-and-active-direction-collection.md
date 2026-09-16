# 修复涨跌停生态与容量方向采集失败

## Stage（阶段）

Stage 1 — provider 响应兼容、同口径降级、精确日期与失败保留；不执行真实 provider、生产 SQLite/PVC 或部署写操作。

## Status（状态）

`completed-without-real-provider-smoke` · provider 修复、回归测试和离线门禁已完成；真实行情验证与生产部署仍需单独授权。

## Scope（范围）

- 修复日期化涨跌停/跌停/炸板池对真实 `push2ex` 响应形态的解析和可审计日期证据处理。
- 为涨跌停池补齐同口径的端点降级；每个池独立保留来源、错误和观察数，不能因一个池失败伪造完整数据。
- 加固容量方向 Top-N 响应兼容与主域到延迟域的统一校验，保留现有 `activeDirection` 字段和精确日期语义。
- 不修改 API 路径、旧五字段名称、规则 ID、SQLite 表结构或前端计算口径；不把失败改写为成功，不跨日期回填。

## Acceptance（验收）

- 涨跌停池能解析数组/键值对象池、顶层或明确查询日期证据；响应无可证明日期时仍为 `failed`/`insufficient`，不写入 V1 完整事实。
- 涨跌停池主端点失败后可请求兼容延迟端点；成功结果的 `quality.source`、`status`、`warnings` 和每池证据准确反映降级，双端点失败保留 `failed-retained`/`failed-missing`。
- 容量方向主域和延迟域使用同一字段、最小 30 行、成交额非递增校验，并兼容数组/键值对象和可识别字段别名；无效载荷不得保存为成功快照。
- 当前/历史日期边界、null/insufficient、旧五字段和 Top-30/Top-10 派生结果保持兼容；普通 GET 仍 provider-free。
- provider、collection、snapshot/service 回归测试通过；`git diff --check`、`python scripts/check-docs-contract.py --mode=full` 通过。

## Completion Evidence（完成证据）

- 基线：`.venv/bin/python -m pytest tests/test_market_environment_providers.py tests/test_market_environment_collection.py tests/test_market_environment_limit_facts.py tests/test_market_environment_limit_promotion.py -q` → 74 passed, 2 warnings。
- 修复后 provider + limits promotion：`.venv/bin/python -m pytest tests/test_market_environment_providers.py tests/test_market_environment_limit_promotion.py -q` → 39 passed, 2 warnings；provider 覆盖查询日期绑定、池对象/键值对象、主/延迟端点逐池降级、invalid date fallback、容量字段别名和双端点校验。
- 修复后 market-environment 全集：231 项中仅既有性能阈值测试一次超过 0.5 秒；隔离重跑通过。排除部署护栏文件的离线全集 258 项同样仅该性能阈值一次超时，隔离重跑通过。
- `.venv/bin/python scripts/check-docs-contract.py --mode=full` → 通过（代码 16 / 文档 6 / plan 1）；`git diff --check` → 通过；真实 provider smoke 未执行，本计划不包含生产访问授权或部署。

## Remaining Gaps（剩余缺口）

- 未证明真实 provider 在当前网络和当前市场日可用；需要后续显式授权的盘后隔离 smoke 验证来源、实际日期、字段覆盖和 checksum。
- 证券制度、ST、上市窗口、板块和收盘状态缺失时，limits V1 晋级/梯队/分层仍必须保持 `insufficient`，本次不扩展事实推断。
- 生产冻结镜像尚未因本次代码变更重新部署，不能把本地测试当作生产修复证据。

## Next Step（下一步）

在获得显式盘后隔离授权后，使用新的 SQLite 副本执行当前市场日 smoke，核对每池来源、`dateEvidence`、字段覆盖、checksum 和最终质量；在此之前不写生产 PVC、不改规则校准状态。

## Tasks（任务）

- [x] 更新产品规格、架构、runbook 和状态中的新降级/日期证据契约。
- [x] 实现涨跌停池与容量方向 provider 修复，保持现有公共 payload 和存储边界。
- [x] 增加 provider/collection 回归测试并运行聚焦测试。
- [x] 运行全量离线验证和 docs contract，回写完成证据、剩余缺口与下一步。
