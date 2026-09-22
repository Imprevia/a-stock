## 1. 能力报告与配置边界

- [x] 1.1 定义扶摇能力报告、数据集状态、证据字段、provider revision 和 checksum 模型，并为 `eligible`、`ineligible`、`unverified` 建立序列化契约；用固定样例测试 round-trip 和脱敏输出
- [x] 1.2 为 PostgreSQL 与 SQLite 增加 `provider_capability_reports` 加法 schema、迁移和读写接口；验证旧快照/旧 schema 可继续读取，且重复 revision 写入幂等
- [x] 1.3 增加 `core`、`breadth`、`sectors`、`activeDirection` 的按数据集扶摇开关、批准 revision 和 shadow 开关；验证默认关闭、类型错误 fail closed、limits 现有配置行为不变
- [x] 1.4 为 Dashboard 与采集 CronJob 注入独立扶摇 Secret/环境变量和新开关；用 Helm lint、离线 template 和部署清单测试证明 key 不出现在 values、日志或 API 响应

## 2. 扶摇通用请求与数据集适配

- [x] 2.1 在 limits 专用客户端之外实现通用扶摇请求层，统一 envelope、权限/限流/网络错误分类、有界重试、超时和请求预算；用脱敏 fixture 覆盖 2xx/业务错误/429/5xx/非法 JSON
- [x] 2.2 实现指数快照与历史 K 线适配，完成五个指数代码映射、OHLC/成交额到现有 `Bar` 契约的归一化和价格/日期交叉校验；缺字段时返回 `unverified` 或 `insufficient`
- [x] 2.3 实现全市场快照/分页能力探测与 breadth 适配；校验 total、分页稳定性、规范身份、涨跌幅有效样本和中位数，无法证明历史日期时拒绝历史采集
- [x] 2.4 实现 activeDirection 能力探测与适配；只有扶摇能证明成交额排序或完整市场下载时才生成 Top-N，继续执行至少 30 行、字段完整和非递增排序校验
- [x] 2.5 实现 sectors 能力探测与适配；校验行业排名、涨跌/成交额/资金字段和真实领涨股名称，字段缺失或代码冒充名称时保持 `ineligible`/`insufficient`
- [x] 2.6 将四个适配器输出归一化为既有 payload、quality、`asOf`、observations、warnings 结构；用契约测试证明缺失值保持 `null`/`missing`，不跨日期或用零值填充

## 3. Probe、shadow 与切换门禁

- [x] 3.1 增加离线 capability probe CLI，读取固定 fixture 生成逐数据集报告、证据清单和 checksum；验证 PR 运行不访问真实 provider
- [x] 3.2 增加显式盘后/本地 real probe 入口，写入隔离存储的 capability revision 和脱敏 JSON；验证无 key、非交易日、日期冲突和权限不足均 fail closed
- [x] 3.3 实现逐数据集 shadow comparator，按指数代码/规范证券身份比较集合、计数、排序和数值容差，并生成 `match`、`mismatch`、`degraded`、`insufficient` 结论
- [x] 3.4 将 shadow 结论、provider revision、比较样本数、差异和 warning 写入 collection task/result 元数据；验证 shadow 失败不覆盖正式快照、不改变正式 source 和 checksum
- [x] 3.5 在 collection coordinator 中加入 capability revision 校验和按数据集 opt-in 路由；未获批准的数据集在创建 provider lease 前拒绝，兄弟任务仍继续执行
- [x] 3.6 为扶摇正式采集实现运行时回退：扶摇失败时回到当前 provider 或保留同日期快照；验证 `failed-retained`、`failed-missing`、`partial` 和 warning 语义与现有契约一致

## 4. 测试与隔离验证

- [x] 4.1 补充指数、全市场、行业和排序响应的脱敏 fixtures，覆盖成功、分页变化、身份重复、字段缺失、日期不一致和超预算场景；验证 fixture 不含凭据
- [x] 4.2 增加 Fuyao adapter/provider 单元测试和现有 provider 回归测试；执行 `python -m pytest tests/test_market_environment_fuyao.py tests/test_market_environment_providers.py -q`
- [x] 4.3 增加 collection integration 测试，覆盖未通过能力门禁、shadow match/mismatch、单项失败隔离、同日期失败保留、provider-free status GET 和旧客户端字段兼容
- [ ] 4.4 在隔离 PostgreSQL 执行一次授权的 capability/shadow smoke，记录日期证据、来源 revision、请求预算、差异和最终质量；确认生产数据库未被访问
- [x] 4.5 执行完整离线验证：`python -m pytest tests -q`、`python -m src.trading_system.cli docs sync-check`、`python scripts/check-docs-contract.py --mode=full`，并记录真实 provider 未纳入 PR 门禁

## 5. 文档与发布边界

- [x] 5.1 更新 `docs/architecture.md`，说明扶摇通用能力层、limits 专用链路、逐数据集切换和 shadow/快照边界；用 docs contract 检查引用路径
- [x] 5.2 更新 `docs/runbooks.md`，补充 capability probe、隔离 shadow、Secret 注入、回滚、请求预算和禁止跨日期回填的操作步骤；验证示例命令不含真实凭据
- [x] 5.3 更新 `docs/product-specs/market-environment-dashboard.md` 与 provider 质量说明，明确正式来源、shadow 状态、`unverified`/`insufficient` 语义和 limits 不变范围
- [x] 5.4 更新本 change 的 `Status`、`Completion Evidence`、`Remaining Gaps`、`Next Step` 记录；归档前确认默认开关仍关闭，未通过能力验证的数据集没有被宣称为可替换
