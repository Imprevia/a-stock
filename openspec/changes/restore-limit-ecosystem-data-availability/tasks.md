## 1. 规格与数据源边界

- [x] 1.1 更新产品规格、架构、runbook、状态和 active plan，明确 PostgreSQL、扶摇主源、东方财富降级、分层质量、Secret 与非生产边界；运行 docs-contract fast 验证。
- [x] 1.2 实现扶摇客户端的交易日历、代码表和三类池分页/信封/重试校验；用固定 fixture 覆盖成功、空池、非交易日、重复、分页缺失、限流和权限错误。
- [x] 1.3 实现扶摇与东方财富按规范身份合并及 source/warning/quality 映射；用一致、差异并集和主源失败 fixture 验证。

## 2. 事实存储与聚合

- [x] 2.1 增加 Alembic 0002 和 fresh bootstrap 加法字段，扩展 fact/dataset record、checksum 和 PostgreSQL store 映射；验证 0001 升级、fresh schema、幂等和旧记录兼容。
- [x] 2.2 将基础晋级改为两日 membership-complete 涨停集合交集并更新规则版本；验证高级属性缺失仍可计算、零分母、集合不完整和双源降级。
- [x] 2.3 按字段完整度拆分梯队、ST、上市窗口、制度和板块分层质量，并生成四组 securityDetails；验证每组 total/rows/quality 与 promoted 集合。
- [x] 2.4 为显式 refresh 增加 `--history-sessions` 六交易日回填并保持 scheduled/default 行为不变；验证升序采集、部分失败保留和五个晋级历史点。

## 3. 前端与公开契约

- [x] 3.1 扩展 Pydantic/TypeScript limits 明细契约和兼容验证；验证旧五字段 payload、明细行和非法比例约束。
- [x] 3.2 在第 03 页增加可展开四组明细、搜索、本地分页和移动端局部滚动；用 Vitest 验证交互、null 与行级 warning。
- [x] 3.3 将第 04 页改为读取 risk_tier 分层与 failure-repair 证据并移除 tierRisk 类型；验证单项质量和不足状态。
- [x] 3.4 修复日期切换及全局刷新后的当前 section 自动重载，并验证并发过期响应不会覆盖新日期。

## 4. 配置与发布安全

- [x] 4.1 增加扶摇环境配置和密钥脱敏/缺失 fail-closed 行为；验证日志和 API 不包含密钥。
- [x] 4.2 更新 Helm values/schema/templates 与原生 k3s 清单，通过独立 Secret 向 Dashboard/CronJob 注入密钥且 V1 默认关闭；运行 Helm lint/template 和部署测试。

## 5. 验证与完成证据

- [x] 5.1 运行后端定向及全量 pytest，验证 provider-free GET、lease/CAS、失败保留、性能和旧客户端兼容。
- [x] 5.2 运行前端 Vitest、Vite build、桌面/390px 溢出与字体检查。
- [x] 5.3 运行规则 validate/coverage/docs sync-check、OpenSpec strict、docs-contract full 和 git diff check。
- [x] 5.4 使用 Secret 注入和隔离 PostgreSQL 执行六交易日盘后 smoke，记录集合、五个晋级点、明细、质量与失败边界，不访问生产环境。
- [x] 5.5 更新 active plan 的 Status、Completion Evidence、Remaining Gaps 和 Next Step，确认未完成项与凭据轮换要求。
