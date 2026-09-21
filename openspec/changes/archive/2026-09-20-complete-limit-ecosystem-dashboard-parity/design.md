## Context

当前 main 的 `LimitEvidence`、limits provider 和 collection 只覆盖三个日期化池的五项事实；本地 SQLite 虽已有快照/任务基础，但当前工作区没有 limits 快照或证券明细。历史分支 `agent/backend/gyt-21-refresh-stale@066229a` 提供了严格 V1 晋级、交易日解析和证券事实的离线实现，不过它与 main 后续的 refresh/lease/materialized aggregate 及部署安全改动存在大范围冲突，不能整体合并。

本设计把历史 V1 能力作为选择性迁移参考，在当前 main 的数据边界上扩展完整文档看板。实现必须遵守已有市场数据快照、采集管理、provider-free GET、失败保留、单机 SQLite lease 和交易规则 `needs-backtest` 约束。

## Goals / Non-Goals

**Goals:**

- 为四类生态指标建立可复算的聚合、证券事实、相邻交易日和质量契约。
- 在现有五字段 API 上做兼容扩展，支持晋级、梯队、制度/板块分层、时间序列和规则证据。
- 让页面直接渲染后端证据，清楚区分 `null`、`missing`、`insufficient`、`degraded`、`failed` 和缓存状态。
- 保持普通读取无 provider 调用，采集任务独立、可重试、幂等、可回滚。
- 通过固定离线 fixture 验证数据、迁移、聚合、页面和响应式行为，再单独执行获授权的盘后真实 smoke。

**Non-Goals:**

- 不修改 `QTS-01-03-01` 至 `QTS-01-03-05` 的 ID、权重、覆盖清单或 `needs-backtest` 状态。
- 不把经验分位或分数渲染为已验证结论，不提供自动下单或投资建议。
- 不使用名称匹配、自然日减一、其他日期回填或浏览器端业务重算。
- 不整体 cherry-pick 历史分支，不带入其 NGINX、CronJob、调度、refresh handoff 或部署文档变更。
- 不在本 change 内执行生产部署、生产 SQLite/PVC 变更或未经授权的真实 provider 访问。

## Decisions

### 1. 采用“旧聚合 + 规范证券事实”两层模型

保留 `snapshot_entries(dataset='limits', as_of)` 中的五项聚合事实，并新增加法表保存证券级证据：

```text
trading_sessions(
  as_of PRIMARY KEY, previous_as_of, actual_as_of, is_session,
  source, schema_version, checksum, fetched_at, warnings
)

limit_security_facts(
  as_of, security_id, pool_type, code, exchange, name, board, is_st,
  listing_date, listing_days, limit_regime, close_price, previous_close,
  change_pct, touched_limit_up, closed_limit_up, failed_limit_up,
  streak_days, eligible, invalid_reason, source, fetched_at,
  schema_version, row_checksum, dataset_checksum,
  PRIMARY KEY(as_of, security_id, pool_type)
)
```

选择关联明细而不是把无限数组塞进聚合 JSON，是因为跨日身份 join、制度分层、幂等去重和校验和需要行级查询；旧聚合仍可被旧客户端读取。

### 2. 晋级计算只接受相邻、完整、可验证的交易日

采集层先保存当前日和精确前一交易日的 session evidence，再由 service 从本地事实计算：

```text
denominator = previous.eligible && previous.closed_limit_up
numerator   = same security_id in current.closed_limit_up
ratio       = numerator / denominator
```

任何日期不一致、证券身份冲突、制度不明、收盘状态不完整或样本集合不完整都会使晋级质量变为 `insufficient` / `failed`，而不是尝试自然日回退。`promotionRatio`、样本日期、规则版本、分子/分母 quality 和排除计数全部由后端返回。

### 3. provider 适配分为宽松旧路径和严格明细路径

旧 `fetch_chapter01_limits` 保持五字段兼容；新 limits detail path 负责验证 provider 顶层/逐行实际日期、规范证券身份、交易所/板块、ST/上市窗口、适用制度和收盘涨停。无法满足严格字段的 provider 结果可以保留旧事实，但不得生成完整晋级、分层或历史结论。

不在 provider 层猜测固定 10% 涨跌幅，也不以证券名称作为身份。每个排除原因进入数据集 warning 和字段 quality，保证真实 smoke 失败时可审计。

### 4. API 采用可选扩展和正交质量状态

在 `LimitEvidence` 追加可选字段：

- `todayPromoted`、`yesterdayLimitUpEligible`、`promotionRatio`
- `promotionSampleAsOf`、`promotionPreviousAsOf`
- `promotionSampleRule`、`promotionRuleVersion`
- `promotionQuality`、`fieldQuality`
- 梯队、制度/板块分层、5 日序列、250 日分位和规则证据对象

Pydantic/API 校验拒绝分子大于分母、零分母携带比例、比例精度不符、逆序样本日期和缺少 quality 元数据。`quality.status`、metric quality 和 `cacheState` 独立表达 provider、字段和缓存状态；旧 payload 的新增字段保持省略或显式 null 的兼容语义。

### 5. 历史指标分阶段开放

当前日事实和相邻日晋级在完整数据可用时展示；近 5 日趋势只使用精确日期快照；250 日分位、规则分数和风险否决要求至少 60 个有效观测，并在返回中保留覆盖率和校准状态。五条 QTS 规则仍标记为 `needs-backtest`，因此页面将其作为经验研究证据而非 validated 评分。

### 6. 页面按证据层次重组

第 03 页结构固定为：

```text
交易日/quality/source/cache/warning
  -> 当日事实卡（涨停、跌停、炸板、炸板率、最高板）
  -> 晋级证据（分子、分母、比例、相邻日期、规则版本）
  -> 梯队与制度/板块分层表
  -> 近 5 日趋势和 250 日覆盖状态
  -> 次日反馈/风险扩散/规则证据
  -> 缺失、确认和失效条件
```

浏览器只格式化后端数值，不从分子分母重新计算指标。章节刷新使用局部状态；有旧证据时刷新中或失败时保留旧内容并显示非阻塞 warning。页面宽表在自身滚动容器内适配 390px，页面不发生横向溢出。

### 7. 按当前 main 进行函数级迁移

迁移顺序为 schemas → SQLite migration/store → trading-session/fact normalization → provider strict path → collection/refresh → service aggregation → API → Vue/types/styles。可复用历史分支的纯模块和离线 fixtures，但必须重新绑定当前 main 的 lease fencing、materialized aggregate CAS 和部署文档，不覆盖无关文件。

### 8. 以开关和离线证据控制发布

新增 detail/V1 写入开关默认关闭。关闭时旧五字段路径继续服务；开启前必须通过迁移、幂等、provider-free GET、失败保留、页面状态、性能和 `PRAGMA quick_check`。真实 provider smoke 只接受显式本地/盘后命令，且不得写生产数据库；真实字段无法证明时保持 `failed` / `insufficient`。

## Risks / Trade-offs

- [Eastmoney 无法稳定提供交易所、制度或收盘状态] → 严格排除不完整行，保留旧五字段，晋级和分层输出 `insufficient`，禁止推断。
- [完整梯队与制度分层增加 SQLite 写入和聚合成本] → 使用行级事实、复合索引、数据集 checksum 和同事务提交，测量 join/store/rebuild 时间。
- [历史 provider 覆盖不足 60/250 个交易日] → 只显示可验证的近 5 日事实，并将分位、评分和周期结论标记为数据不足。
- [旧快照缺少新字段] → 读取层保持 additive null/omitted 兼容，不回填旧日期，不改写旧 payload。
- [refresh/lease 与逐股事实事务发生竞争] → 复用现有 dataset/date lease 和 generation fencing，所有 aggregate/fact 写入在当前 token 和 CAS 条件下提交。
- [旧分支包含无关部署和 refresh 改动] → 只做函数级迁移，逐文件复核 diff，禁止整分支 cherry-pick。
- [真实 smoke 结果不可预测] → 先用固定离线 fixture 完成所有 PR 验收，真实 smoke 单独记录 source、日期、排除数和 warning，不将失败转成成功。

## Migration Plan

1. 建立 active plan 和新 OpenSpec change，冻结完整页面矩阵与旧五字段兼容边界。
2. 先迁移/重写契约、固定 fixtures、交易日和证券事实表；对复制的 v1 SQLite 执行幂等迁移和 `quick_check`。
3. 接入严格 provider、当前/前一交易日 collection、原子事实写入和本地晋级/梯队/分层聚合。
4. 接入 API 可选字段和第 03 页证据优先 UI；补齐局部加载、保留旧证据、错误重试和移动端检查。
5. 运行固定离线测试、全量 Python/Vitest/build/docs-contract，并记录与既有 refresh/stale 并发基线的归属。
6. 在独立授权下运行两日盘后 smoke；只有日期、身份、制度和收盘状态均可证明时才允许晋级质量为 `ok`。
7. 生产前保持 detail/V1 和手工写入开关关闭；若回滚，先关闭新写入，再恢复应用版本，保留 PVC、旧快照和新表，不删除数据。

## Open Questions

- 真实 provider 最终能否稳定提供板块、ST、上市窗口和收盘涨停字段，需要在获授权的隔离盘后 smoke 中确认；若不能，规格中的 `insufficient` 路径即为正式结果。
- 250 日历史快照的实际覆盖量和性能预算需要在固定 fixtures 与本地历史库上测量后确定，不改变页面的缺失语义或规则校准边界。
