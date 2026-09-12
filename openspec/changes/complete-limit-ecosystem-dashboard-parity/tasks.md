## 1. 范围、基线与契约冻结

- [x] 1.1 创建并更新 active plan，记录完整第 03 页矩阵、旧五字段兼容边界、当前 main 的 dirty 状态和禁止整分支 cherry-pick 的迁移策略；用 `python scripts/check-docs-contract.py --mode=fast` 验证计划字段完整。
- [x] 1.2 将原版/量化版第 03 篇、规则 YAML 和本 change spec 的指标矩阵固化为离线 fixture 清单；验证 `QTS-01-03-01` 至 `QTS-01-03-05` 的 ID、权重和 `needs-backtest` 未改变。
- [x] 1.3 扩展 Pydantic/TypeScript limits 契约，覆盖晋级、梯队、制度/板块分层、历史序列、覆盖率、置信度、规则证据和正交 quality；用旧 payload、显式 null、20/8、零分母和非法比例测试验证兼容与拒绝规则。

## 2. SQLite 事实存储与交易日证据

- [x] 2.1 在当前 `SnapshotStore` 迁移体系中增加 `trading_sessions`、`limit_security_facts` 和数据集校验元数据表/索引；对复制的 v1 SQLite 重复迁移并用 `PRAGMA quick_check`、旧聚合读取和无删除断言验证。
- [x] 2.2 实现规范证券身份、交易所/板块、ST/上市窗口、适用涨跌幅制度、收盘状态和排除原因的规范化记录；用 malformed、duplicate、ambiguous、ST/IPO、intraday-touch、missing-close fixtures 验证不使用名称匹配或固定 10% 推断。
- [x] 2.3 实现精确交易日及前一真实交易日解析、请求/实际日期校验和 checksum；用周末、节假日间隔、provider 日期错位和缺少前序 session fixtures 验证不自然日减一、不跨日期回填。
- [x] 2.4 实现逐股事实和聚合的幂等、事务提交、generation fencing 和失败保留；用重复采集、过期 lease、错误 token、写入异常和回滚测试验证不产生重复或混合日期数据。

## 3. Provider、采集与后端聚合

- [x] 3.1 保留旧 limits provider 五字段路径，并新增严格 detail provider 的顶层/逐行日期、证券身份、制度和收盘状态验证；用固定 pool fixtures 验证完整、空池、部分池、全失败和 provider warning 的质量映射。
- [x] 3.2 扩展 limits collection task，按 dataset/date lease 协调当前日与前一真实交易日事实，保持与 core/breadth/sectors/activeDirection 的独立失败隔离；验证单项重试不会触发无关 provider 调用。
- [x] 3.3 实现严格晋级聚合、分子/分母、制度/板块分层和首板至四板以上梯队；用 20/8、零分母、身份不匹配、部分收盘状态和完整分层 fixtures 验证数值及 `insufficient` / `degraded`。
- [x] 3.4 实现近 5 日事实序列、连续跌停/炸板/断板/修复和板块集中度输入；验证缺失精确日期时只返回缺口，不搜索更早日期或启动普通 GET provider。
- [x] 3.5 实现 60 个有效观测门槛、250 日分位、覆盖率/置信度和经验规则证据聚合；验证少于 60 日时分位、分数、否决和周期结论保持 `insufficient` 或明确未校准。
- [x] 3.6 将 limits 聚合接入 materialized aggregate、API response validation 和缓存 quality；验证 provider-free warm read、component CAS、同日期 failed-retained 和 `MARKET_ENVIRONMENT_LIMITS_V1_ENABLED=0` 回滚路径。

## 4. 第 03 页看板实现

- [x] 4.1 重组第 03 页证据优先布局：交易日/来源/cache/warning、五项当日事实卡、晋级证据、梯队与制度/板块分层、时间序列和规则证据；用固定完整/缺失/部分 fixture 验证后端字段直渲染且无浏览器业务计算。
- [x] 4.2 实现局部 `loading`、`ready`、`refreshing`、`error`、`missing`、`failed`、`fallback`、`degraded`、`insufficient` 状态和重试；验证刷新或失败时保留同日期旧证据，其他章节不被清空。
- [x] 4.3 统一中文状态、null 占位、百分比精度、样本日期和质量文案；用 lint/静态检查验证不出现 `NaN`、`undefined`、伪造 0 或低于 14px 的可见文字。
- [x] 4.4 完成第 03 页 Vitest、桌面 1440px 和移动 390px 检查；验证梯队/分层/晋级/警告可读、宽表局部滚动、页面无横向溢出，且旧五字段响应仍可渲染。

## 5. 文档、运行与采集入口同步

- [x] 5.1 更新 `docs/product-specs/market-environment-dashboard.md` 和设计规范，明确第 03 页完整矩阵、未校准规则、质量状态、空数据行为和不展示伪结论；用文档审计确认与 spec/design 一致。
- [x] 5.2 更新 `docs/architecture.md`、`docs/runbooks.md` 和 `docs/status.md`，记录事实表、精确交易日、provider 限制、feature flag、失败保留、盘后 smoke 和回滚边界；验证不带入历史分支的调度/NGINX 无关内容。
- [x] 5.3 扩展 `/data-collection` 对 limits detail 的状态、样本日期、排除数、晋级依赖和独立重试可见性；验证状态读取不调用 provider，单项失败不回滚成功兄弟任务。

## 6. 集成验证与受控数据验证

- [x] 6.1 运行 limits contract/facts/promotion/provider/collection/service/store/API 测试和全量 Python 测试；验证固定离线快照、旧消费者兼容、provider-free historical GET、lease/CAS 和 `quick_check` 结果。
- [x] 6.2 运行前端测试、生产构建、桌面/390px 浏览器检查和页面溢出/字体静态检查；验证第 03 页完整、空、部分、失败和保留旧证据状态。
- [x] 6.3 运行 `openspec validate complete-limit-ecosystem-dashboard-parity --strict`、`python scripts/check-docs-contract.py --mode=full` 和 `git diff --check`；确认 active plan 的 Status、Completion Evidence、Remaining Gaps、Next Step 已更新。
- [x] 6.4 在获得新的明确授权后，使用隔离 SQLite 和精确两日参数运行盘后 limits smoke；验证最多请求预算、实际/前一日期、来源、制度/收盘状态覆盖、排除计数、checksum 和失败质量，禁止写生产库。
- [x] 6.5 根据 smoke 结果决定 `promotionQuality=ok`、`degraded` 或 `insufficient`；若字段仍不可证明，保留数据不足并记录缺口，不启动生产发布或修改交易规则状态。
- [x] 6.6 完成 release-readiness review 和可回滚证据；验证新功能默认关闭、备份/恢复、PVC/旧快照保留、关闭开关优先顺序和无生产部署授权残留。
