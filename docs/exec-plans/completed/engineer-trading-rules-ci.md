# 交易规则工程化与 CI 验证体系

## 目标

把 `搭建交易系统-量化版/` 从量化说明文档升级为可重复执行、可量化、可追溯并可接入 CI 的规则工程体系。YAML 规则注册表作为机器事实源，Markdown 保留为人读解释层；首期实现通用平台和市场环境第 01 章全部 46 条规则，并为全库 327 条规则建立覆盖清单。

## Stage（阶段）

- 当前阶段：**验证完成**
- 阶段序列：OpenSpec → 产品规格 → 架构与运行契约 → 注册表与执行器 → 证据与回测 → CI → 验证与归档

## Status（状态）

`completed` · 通用规则平台、第 01 章 46 条规则、证据、回测骨架、CLI 和 GitHub Actions 已完成并通过离线验证。

## 范围

- 包含：规则 YAML Schema、327 条覆盖清单、第 01 章 46 条可执行规则、确定性 evaluator、快照、证据包、回测骨架、CLI、离线 PR workflow 和盘后 workflow。
- 排除：自动下单、券商连接、实盘账户控制，以及未经证据支持的 `validated` 声明。

## 事实源

- `openspec/changes/engineer-trading-rules-ci/`
- `docs/product-specs/trading-rule-engineering.md`
- `docs/architecture.md`
- `docs/runbooks.md`
- `trading-rules/`

## 阶段任务

- [x] 创建 OpenSpec proposal、specs、design 和 tasks
- [x] 建立产品规格、架构、运行和仓库映射
- [x] 建立 schema、规则注册表和 327 条覆盖清单
- [x] 实现第 01 章 46 条规则的确定性执行
- [x] 实现证据、回测、CLI 和 CI
- [x] 完成离线回放、测试和文档门禁
- [x] 记录完成证据并归档

## Acceptance（验收）

- 量化版 70 篇与原版保持一对一映射，327 个规则 ID 唯一并全部进入覆盖清单。
- 第 01 章 46 条规则通过 schema、fixture、golden 和确定性执行测试。
- 相同规则版本与输入快照产生一致的规范化结果和 SHA-256。
- 缺失、异常、降级、硬否决、非法晋级和证据篡改场景均有阻断测试。
- GitHub Actions 包含无网络依赖的 PR workflow 和可上传降级证据的盘后 workflow。
- `python -m pytest tests -q` 与 `python scripts/check-docs-contract.py --mode=full` 通过。

## Completion Evidence（完成证据）

- OpenSpec：`openspec/changes/engineer-trading-rules-ci/`，`openspec validate ... --strict` 通过。
- 文档映射：原版 70 篇、量化版 70 篇；327 个规则 ID 全部唯一。
- 规则注册：`rules validate` 输出 1 个规则集、46 条可执行规则；`rules coverage` 输出 327 条文档规则、46 条可执行规则。
- 测试：`.venv` Python 下 `34 passed`；规则平台专项 `18 passed`。
- 确定性回放：固定 snapshot 生成 46 条 trace，result hash 为 `e1f00266212f623c004705e02405c84e18297384fabb47a29d5b700a4d78646c`。
- 证据校验：evidence ID `2026-08-28-market-environment-ef59933f7339`，3 个文件哈希验证通过。
- 文档门禁：`python scripts/check-docs-contract.py --mode=full` 通过。
- CI：`.github/workflows/trading-rules-pr.yml` 与 `.github/workflows/trading-rules-after-market.yml`。

## Remaining Gaps（剩余缺口）

- 全市场宽度、涨跌停池、板块、活跃成交和事件的真实 provider 尚未接入；盘后 snapshot 会因此明确输出 `insufficient`，不会生成伪结论。
- 真实历史数据回填与 500–750 日阈值校准需独立执行；当前所有规则最高为 `defined`，没有 `validated`。
- 第 02 至 11 章的 281 条规则已进入覆盖清单，但仍为 `documented-only`。
- Starlette TestClient 对 mootdx 所需的 httpx 0.25 发出弃用警告；待 mootdx 支持新版 httpx 后再升级。

## Next Step（下一步）

下一阶段接入第 01 章扩展真实 provider，积累至少 500 个交易日快照，再执行样本外校准；随后按覆盖清单推进第 02 章。
