# 接入通达信盘后包作为市场广度与容量方向备用源

## Stage

Stage 1 — 独立盘后包客户端、`breadth`/`activeDirection` fallback、离线契约与隔离验证

## Status

completed（实现与验证阶段完成；真实 `activeDirection` 资格仍因原始包未排序而保持 rollout gated，生产默认关闭）

## Acceptance

- Eastmoney 主域和延迟域均失败后，`breadth` 与 `activeDirection` 才允许尝试 `tdx-daily-package`。
- 盘后包必须证明请求日期、源侧日期、完整下载、证券身份、数值字段和所需样本；不得跨日期回填或把代码当名称。
- `breadth` 保留上涨/下跌/平盘/中位数契约；`activeDirection` 保留至少 30 行、名称和成交额非递增契约。
- 质量元数据记录 `tdx-daily-package`、观测数和前序 Eastmoney warning；失败继续使用 `failed-missing`/`failed-retained`。
- `sectors`、`limits`、`core`、数据库 schema、公开 API 字段和生产调度保持不变。
- feature flag 默认关闭；真实 provider 只通过显式盘后隔离 probe 验证，不进入 PR 离线门禁。

## Completion Evidence

- 已实现：盘后包客户端、规范化、`breadth`/`activeDirection` fallback、离线 fixture、collection integration、只读 probe 命令和文档。
- 上游来源：`simonlin1212/a-stock-data` revision `2e0ae6383c649b2bc5f68d3bc430d357f1c59ae7`，仓库声明 Apache-2.0；仅提取/重写盘后包所需逻辑，不运行时访问 GitHub。
- 2026-09-23 18:18 CST 隔离 probe：请求/源日期 `2026-09-18` 一致；ZIP 2,741,589 bytes；53,214 行；沪/深/北 `27,810/24,128/376`；成交额覆盖率 `1.0`；名称覆盖率 `1.0`；耗时 `10016.32 ms`；包解析质量 `ok`。输出位于被 gitignore 的 `.artifacts/market-environment/tdx-probe-20260918.json`，未写生产数据库或快照。
- 目标 provider/collection 测试：`71 passed in 43.03s`；Eastmoney primary/delayed 成功回归通过。
- 全量验证：`673 passed, 3 skipped, 2 warnings in 209.33s`；`docs sync-check` 输出 `documentedRules=330, executableRules=49`；docs-contract full 通过；`openspec validate ... --strict --no-interactive` 通过；`git diff --check` 通过。
- 未执行生产数据库写入、CronJob 操作或部署变更。

## Remaining Gaps

- 2026-09-18 真实包虽可解析，但原始记录不是成交额非递增顺序（约 5,209 个逆序点）；按当前规格 `activeDirection` 会拒绝该包，禁止本地排序伪造 provider-ranked 证据。需要单独更新规格并重新评审后，才能决定是否允许“完整包本地确定性排序”作为另一种质量状态。
- 真实 probe 证明了包级字段覆盖，但尚未证明 `activeDirection` 的真实资格；腾讯名称回退仅通过离线注入测试验证，未执行真实腾讯请求。
- feature flag 必须保持关闭，直到 active-direction 排序证据边界被明确接受；不能将 package `quality=ok` 误当作两个数据集均可启用。

## Next Step

归档本变更前，产品/数据质量负责人需要决定是否另开变更处理真实包未排序与 `activeDirection` 的证据边界；在该决策前保持 `MARKET_ENVIRONMENT_TDX_DAILY_PACKAGE_FALLBACK_ENABLED=0`，只允许复用已验证的包解析与 `breadth` fallback。
