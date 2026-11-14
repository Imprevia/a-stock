## Context

上游 plan `docs/exec-plans/active/qts-04-stock-selection-pipeline-plan.md` 把第 04 章拆成十步，STEP 1 是板块层定向，对应规则 `QTS-04-01-01` ~ `-05`。这些规则在 `trading-rules/coverage.yaml` 中全部是 `documented-only`。

实测约束（本轮只读核查结论）：

```
k3s 生产 PostgreSQL
  ths_industry_rankings      19,502 行 / 23 个交易日 / provider=fuyao
  ths_sector_daily_bars      19,456 行 / 23 个交易日 / provider=fuyao
  ths_sector_breadth_evidence   880 行
  ths_sector_memberships       2,376 行

仓库 v2 接口
  GET /sectors/rankings   500  AmbiguousParameter (after_code IS NULL)
  GET /sectors/turnover   500  同上
  GET /sectors/breadth    500  同上

fuyao 官方 CLI（实测通过）
  index catalog --tag industry        可用
  index history-batch                 208 根日线 / 指数
  index constituents                  29 只成分股（881101.TI）
  market history                      个股前复权日线
```

三条结论决定了设计：

1. 本地库里板块历史只有 23 个交易日，无法支撑 250 日滚动分位；fuyao 的 `index history` 支持近 5 年，能补足。
2. 仓库 sector 三个列表端点在生产返回 500，不能作为 Skill 通道。
3. fuyao 官方的 `index history-batch` 一次可取 10 个指数，`index constituents` 按单指数取成分股。

## Goals / Non-Goals

**Goals**

- 让 STEP 1 能在任意已完成交易日重复执行，输出确定性的板块排名与四象限分类。
- 五指标、分位打分、覆盖率闸门、降级语义都可由 fixture 离线验证。
- 请求量可控：宽度只算前 N 个行业。
- 结论边界清晰：`needs-backtest`，观察候选而非买点。

**Non-Goals**

- 不实现 STEP 2 之后的题材、资金、角色、模式、基本面、仲裁与剧本。
- 不修改 `trading-rules/`、`coverage.yaml`、`src/`。
- 不修生产 sector 500 缺陷（本轮只报告）。
- 不写数据库、不做调度、不做生产部署。
- 不做回测校准，`needs-backtest` 不升级。

## Decisions

### D1 用官方 CLI 而非自写 HTTP 客户端

选择调用 `hithink-finance`（`@hithink-tech/hithink-finance-cli`）。

理由：命令契约稳定，官方随版本维护参数与分页；`capabilities` 和 `schema` 可自省，脚本不必硬编码端点细节；`--format json` 提供稳定信封 `{ok, command, data, meta}`。

代价：引入 Node.js 22.12+ 运行时依赖。缓解方式是把它降级为可检测的前置条件——缺失时输出 `insufficient` 并给安装指引。

替代方案（未采用）：自写 `requests` 客户端直连 REST。控制力更强，但要自己维护端点、重试、限流与分页，且与官方契约漂移。

凭据解析（2026-11-14 调整）：仓库已有 `deploy/truenas/deploy.env` 保存 `FUYAO_API_KEY`，且该文件已进 `.gitignore`。为避免用户在两处维护同一把 key，解析顺序定为 `FUYAO_API_KEY` 环境变量 → `MARKET_ENVIRONMENT_FUYAO_API_KEY` 环境变量 → `deploy/truenas/deploy.env` 的 `FUYAO_API_KEY` → `--env-file`。只按行取目标键，同文件的 `TUSHARE_TOKEN` 等其他机密不进入内存或输出；输出仅暴露 `credentialSource` 标签。代价是 Skill 读了一个含其他机密的本地文件，因此解析器必须逐行匹配而非整体加载。

### D2 取数通道与仓库 API 完全解耦

Skill 只调用 fuyao 官方命令，不读 `/api/v2/market-environment/*`，不连 PostgreSQL。

理由：主控明确要求数据源直接从 fuyao 取；同时仓库这些端点在当前生产版本不可用。解耦后 Skill 也不受仓库部署状态影响。

代价：Skill 自行承担日期校验与质量传播，这些原本由 v2 的 `snapshotRevision` 与 quality 字段提供。

### D3 以 `index history` 为主干，`snapshot` 不用于历史复盘

`snapshot` 只返回最新行情且带自身 `timestamp`，无法指定历史日期。所有历史复盘走 `history` / `history-batch`。

历史 K 线是板块指数自身的 OHLC + volume + turnover，不含成分股明细，因此：

- 相对强度、成交额增量、持续性/恢复：只用板块日线，可完全从 `history` 算出。
- 宽度：需要成分股个股日线，走 `index constituents` + `market history`。

### D4 宽度只算前 N 个行业

`--breadth-universe N`，默认 30。

理由：全量 320 个行业 × 全成分股约需 900 次请求，会长时间占用限流预算。而 STEP 1 的语义是先排序再取前 3，宽度是候选确认项而非全市场枚举项。前 N 个行业计算宽度既满足语义又把请求量压到约 30 + 分批个股请求。

替代方案（未采用）：全量计算。完整但慢，且对本步骤没有额外决策价值。

### D5 250 日缓存优先，缺失才联网

缓存放在 Skill 目录下的可重建目录，不入库、不入 git，带明确 `cache_state`（`cold` / `warm`）。

理由：分位需要 250 个观测，每次现场拉 320 个行业 × 5 年不现实。缓存把一次性成本摊薄，同时保持可重建——删掉缓存不影响正确性，只影响首跑耗时。

### D6 分位降级分三档

`ok`（≥250 观测）、`reduced-confidence`（60—249）、`insufficient`（<60，得分为 `null`）。

上游量化文档的原文是"默认分位校准窗口为250个交易日，最少60个有效观测；不足时降低置信度或输出数据不足"。主控确认按**严格 60 个观测门槛**执行：低于 60 一律 `insufficient` 且不给分，60 至 249 给分但标记 `reduced-confidence` 并注明观测数，达到 250 才为 `ok`。不做 20—59 的中间档。

### D7 四象限只用原始值

四象限（真实流入 / 短线脉冲 / 权重拉升 / 资金撤退）由上涨覆盖率与资金强度决定，两者都是原始值。分位降级不影响四象限输出。

理由：上游文档把四象限写成一个基于"覆盖广/窄 × 强度高/低"的定性判定，本就不要求分位。这样即使缓存冷启动，Skill 仍能给出可用结论。

### D8 基准指数用上证综指 `000001.SH`

相对强度 = 板块收益 − 基准收益。主控确认用上证综指，与仓库现有指数体系一致。

### D9 只做 `industry` tag

`cn_concept`、`region`、`tszs` 不在本轮范围。概念板块属于 STEP 2 题材层的输入。

### D10 失败一律降级，不伪造

- CLI 缺失 / 凭据缺失：`insufficient`
- 429 或 `code=4001`：有界退避后仍失败则 `degraded`
- 目标日无数据：`insufficient`，不回退相邻日期
- 缓存存在但目标日缺失：不得用旧日期顶替

### D11 报告是纯渲染层，不参与计算

选择新增 `scripts/report.py`，用 `render_markdown(result)` 把已算好的 JSON 转成 Markdown。

理由：JSON 是唯一事实源。若报告自己再算一遍总分，两份产物迟早会分叉，用户无法判断信谁。纯渲染保证「JSON 里是多少，报告里就是多少」，也让报告可以离线用 fixture 复现。

代价：报告只能呈现 JSON 已有的字段，表达能力受 JSON schema 约束。接受这个约束——想加内容就先加字段。

渲染的四个硬约束：

1. `score` / `percentile` 为 `null` 时渲染 `—`，绝不渲染 0，否则「没算出来」会被读成「算出来是 0 分」。
2. `normalizedWeight` 为 `null` 表示该指标未计分，权重列渲染 `—`。若回退显示原始 `weight`，权重列会合计 120%，读者会以为归一算错了。
3. 短历史提示聚合成一句，不逐指标重复五遍。
4. `insufficient` 时改节结构为「结论 / 数据质量 / 口径」，不渲染空的方向小节。

替代方案（未采用）：让 JSON 自带 `markdown` 字段。会把展示逻辑塞进数据契约，且 JSON 体积翻倍。

## Architecture

```
                        ┌──────────────────────────────┐
                        │  SKILL.md（触发 + 工作流）    │
                        └──────────────┬───────────────┘
                                       │ 调用
                        ┌──────────────▼───────────────┐
                        │ sector_pipeline.py（编排）    │
                        └───┬──────────┬───────────┬───┘
                            │          │           │
              ┌─────────────▼──┐  ┌────▼─────┐  ┌──▼──────────┐
              │ fuyao_client.py│  │ cache.py │  │ scoring.py  │
              │ CLI 子进程封装  │  │ 日线缓存  │  │ 五指标+分位  │
              └────────┬───────┘  └────┬─────┘  └─────────────┘
                       │               │
                  hithink-finance      .cache/qts04/
                  (Node 22.12+)         (不入 git)
```

数据流：

```
Step 1  index catalog --tag industry           -> 行业清单
Step 2  index history-batch × ceil(N/10)       -> 板块日线（250 日）
Step 3  market history --thscode 000001.SH     -> 基准日线
Step 4  计算 5 日/20 日相对强度、成交额增量、
        持续性/恢复                            -> 四指标 + 原始值
Step 5  按原始值排序 -> 前 breadth-universe 个
Step 6  index constituents（每个板一次）        -> 成分股
Step 7  market history（分批，每批 10 只）      -> 个股日线 -> MA20
Step 8  宽度 = close > MA20 比例 + 覆盖率闸门
Step 9  滚动分位打分 + 加权总分
Step 10 四象限分类 + 排名 + 确认/失效条件
```

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| Node.js / CLI 未安装 | Skill 完全不可用 | 前置检测，输出 `insufficient` + 安装命令 |
| fuyao 动态限流 | 宽度阶段请求失败 | 有界退避；失败行业标 `degraded` 而非整体失败 |
| 缓存与真实数据漂移 | 分位基于旧缓存 | 缓存记录 `fetched_at`；目标日缺失即补拉；输出暴露缓存状态 |
| 320 行业 × 250 日首拉较慢 | 首次体验差 | 缓存复用；`--breadth-universe` 控制宽度请求量 |
| 严格 60 观测门槛导致冷启动期多数指标无分 | 首次运行结论偏弱 | D6 明确降级语义；靠缓存累积逐步达标；四象限仍用原始值输出 |
| 板块日线无成分明细 | 宽度必须额外取数 | 已在架构中拆成独立阶段 |
| 上证综指与行业指数口径差异 | 相对强度含系统性偏差 | 记录基准；D8 固定并写入输出 |

## Migration Plan

无迁移。这是纯新增的 Skill 与测试，不改动现有代码路径、规则或数据。

回滚方式：删除 `.agents/skills/a-stock-qts04-sector-direction/`、对应测试与 fixture，并撤回 `docs/` 映射条目。

## Open Questions

无未决的构建级问题。以下两项作为默认取值采用，落地时若与预期不符再调整：

1. 板块总分门槛沿用上游经验初值：`≥70` 重点池、`50—69` 观察池、`<50` 不参与，并叠加"持续性分 ≥60"的复合条件。
2. `--breadth-universe` 默认 30，按 STEP 1 "先排序再取前 3"的语义推导，未用真实数据验证覆盖率。