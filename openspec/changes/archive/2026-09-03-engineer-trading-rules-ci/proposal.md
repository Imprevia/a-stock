## Why

现有量化版交易系统文档已经为主观判断补充了规则 ID、阈值和缺失处理，但仍以 Markdown 为主要载体，无法稳定地重复执行、验证变更影响或在 CI 中阻断不可追溯的规则修改。需要把规则、输入、执行轨迹和验证证据连接为机器可检查的工程闭环，同时保留文档作为人工复盘与解释入口。

## What Changes

- 新增版本化 YAML 规则注册表，作为规则执行的机器事实源，并为全部 327 个 `QTS-*` ID 建立覆盖清单。
- 新增类型化规则加载器、稳定 evaluator 注册表和确定性评分执行器，首期实现市场环境第 01 章全部 46 条规则。
- 新增标准输入快照、人工事件输入、数据质量与 provider 降级契约。
- 新增不可变证据包、SHA-256 校验、逐规则 trace、回测结果和规则生命周期晋级检查。
- 新增离线 PR CI 与盘后定时 CI；PR 不访问网络，盘后任务可以拉取真实数据并上传完整 Artifact。
- 将 `搭建交易系统-量化版/` 定位为人读说明层，并通过规则 ID 和同步检查与 YAML 注册表保持一致。
- 明确首期不提供自动下单、券商连接或实盘资金控制，也不将未经证据验证的阈值声明为 `validated`。

## Capabilities

### New Capabilities

- `trading-rule-registry`: 定义规则 YAML Schema、全库覆盖清单、文档映射和生命周期状态约束。
- `trading-rule-evaluation`: 定义标准化输入、确定性 evaluator、评分、否决、缺失处理和执行 trace。
- `trading-rule-evidence`: 定义快照哈希、证据包、回测验证、状态晋级和篡改检测。
- `trading-rule-ci`: 定义离线 PR 门禁、盘后定时执行、Artifact 和月度证据汇总。

### Modified Capabilities

无。

## Impact

- 新增 `trading-rules/`、`src/trading_system/`、`tests/fixtures/trading-system/`、`evidence/` 和 `.github/workflows/`。
- 新增规则平台 CLI，并扩展 pytest 测试集及文档契约检查。
- 更新产品规格、架构、运行手册、仓库指南、状态和交易系统索引。
- Python 依赖增加 YAML 与 JSON Schema 校验库；现有市场环境 API 保持兼容。
