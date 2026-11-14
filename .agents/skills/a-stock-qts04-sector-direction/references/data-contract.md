# QTS-04 板块层定向数据合同

本 Skill 只从 fuyao 官方接口取数（`https://fuyao.aicubes.cn`），通过官方 CLI `hithink-finance` 调用。它不读本仓库的 `/api/v2/market-environment/*`，也不连接 PostgreSQL。

## 凭据

解析顺序（先命中者胜）：

1. `--env-file` 指定的文件中的 `FUYAO_API_KEY`
2. 进程环境变量 `FUYAO_API_KEY`
3. 进程环境变量 `MARKET_ENVIRONMENT_FUYAO_API_KEY`（兼容 k8s 部署形态）
4. 自动向上查找的 `deploy/truenas/deploy.env` 中的 `FUYAO_API_KEY`

说明：

- `deploy/truenas/deploy.env` 已被 `.gitignore` 覆盖，不得提交。
- 该文件同时保存 `TUSHARE_TOKEN` 等其他机密；解析器按行匹配，**只取 `FUYAO_API_KEY`**，其余键不进入内存、不进入输出。
- 支持 `KEY=value`、`export KEY=value`、单/双引号包裹、行尾 ` #` 注释。
- key 转成子进程的 `HITHINK_FINANCE_API_KEY`，不进入 argv、缓存、结构化输出或日志；错误信息做脱敏。
- 输出只暴露 `credentialSource`（如 `file:FUYAO_API_KEY@deploy.env`），不含 key 的任何片段。
- 全部来源都缺失时立即返回 `insufficient`，不尝试其他凭据通道，也不读取 k8s Secret。

## 前置条件

| 条件 | 检查方式 | 缺失时 |
|---|---|---|
| Node.js 22.12+ | `node --version` | 输出 `insufficient` 并给安装指引 |
| CLI 可用 | `shutil.which("hithink-finance")` | 输出 `insufficient` 并给安装命令 |
| 凭据存在 | `FUYAO_API_KEY` 或 `deploy/truenas/deploy.env` | 输出 `insufficient` |

安装命令：

```bash
npm install -g @hithink-tech/hithink-finance-cli
```

## 命令契约

四个命令均由 `hithink-finance capabilities --format json` 自省确认存在。字段变化时以该命令输出为准。

### 1. 行业目录

```bash
hithink-finance index catalog --tag industry --format json
```

- 端点：`/api/a-share-index/catalog/ths-index-list`
- 分页：无，单 tag 一次性全量返回
- 取用字段：`data.item[].thscode`、`data.item[].name`
- 实测约 320 个行业指数，代码形如 `881101.TI`

### 2. 板块历史日线（批量）

```bash
hithink-finance index history-batch \
  --thscodes 881101.TI,884001.TI \
  --start-ms <毫秒> --end-ms <毫秒> --interval 1d --format json
```

- 端点：`/api/a-share-index/prices/historical-batch`
- 窗口：近 5 年
- **单次最多 10 个代码**，超出必须分批
- 取用字段：`data.item[].thscode`，`data.item[].item[].date_ms`、`open_price`、`high_price`、`low_price`、`close_price`、`volume`、`turnover`
- `date_ms` 为毫秒时间戳，按 `Asia/Shanghai` 转交易日

### 3. 成分股

```bash
hithink-finance index constituents --thscode 881101.TI --format json
```

- 端点：`/api/a-share-index/constituents/ths-stock-list`
- 单次只接受一个指数代码
- 取用字段：`data.item[].thscode`、`data.item[].name`
- 返回的是**当前**成分，不带历史成分版本

### 4. 个股历史日线（批量）

```bash
hithink-finance market history-batch \
  --thscodes 000713.SZ,000998.SZ \
  --start-ms <毫秒> --end-ms <毫秒> \
  --interval 1d --adjust forward --format json
```

- 端点：`/api/a-share/prices/historical`
- 窗口：近 10 年
- 单次最多 10 个代码
- `--adjust forward` 取前复权，用于 MA20
- 取用字段同上

## 响应信封

CLI 统一输出 `{ok, command, data, meta}`。

- `ok=true`：读 `data`。
- `ok=false`：读 `error.code` 与 `error.message`。
- `code=4001` 或 HTTP 429：限流，需退避。
- `code=2001`：凭据无效或缺失。

## 日期口径

- 时区固定 `Asia/Shanghai`。
- 目标交易日必须有该日板块日线；缺失即 `insufficient`，不借相邻日期。
- 未给 `--as-of` 时：当天且已过 15:10 用当天，否则回退上一自然日并告警。
- 未来日期、当日 15:10 之前，一律拒绝。
- 自然日回退不等于交易日回退；若回退到的自然日不是交易日，后续取数会发现该日无日线并返回 `insufficient`，需由调用方显式指定 `--as-of`。

## 批量与限流

- 行业日线与个股日线均每批 10 个代码。
- 宽度只算前 `--breadth-universe N` 个行业（默认 30），避免全市场枚举。
- 典型请求量：目录 1 + 板块日线 ⌈320/10⌉=32 + 基准 1 + 成分股 N + 个股日线 ⌈成员数/10⌉×N。`N=5` 实测 44 次调用。
- 限流采用有界指数退避：基数 1s、倍率 2、单次上限 8s、最多重试 3 次；耗尽后 `degraded`。

## 缓存

- 位置：`.agents/skills/a-stock-qts04-sector-direction/.cache/qts04/`，已被 `.gitignore` 忽略。
- 结构：`{kind}/{thscode}.json`，`kind` 为 `industry` 或 `stock`；文件内含 `fetchedAt` 与按日期排序的 `bars`。
- 合并写入：新拉取的区间与已有行按 `trading_date` 合并，不丢历史。
- 状态：`cold`（目标日全缺）、`partial`（部分有）、`warm`（全部有）、`fixture`（fixture 模式）。
- 缺口补齐只拉未覆盖区间，不整段重拉。
- 缓存是可重建派生物：删除只影响首跑耗时，不影响正确性，也不写入数据库。

## 报告契约（JSON 是唯一事实源）

一次运行产出三样东西：

| 产物 | 写入开关 | 默认 | 读者 |
|---|---|---|---|
| JSON | `--output PATH` | 无（除非 `--format json` 打 stdout） | 机器 / 下游 Skill / 校验器 |
| Markdown 事实骨架 | `--report PATH` | 给了 `--output` 时自动写同名 `.md` | agent 底稿、无模型兜底 |
| 人读文章 | 由 agent 另行撰写 | 无 | 用户（必须校验通过后才可呈现） |

stdout 由 `--format` 控制：`json`（默认）/ `markdown` / `both`。

### 顶层接口字段

`report.json` 顶层包含 `schemaVersion`、`reportId`、`config`，另有 `asOf`、`generatedAt`、`status`、`source`、`benchmark`、`breadthUniverse`、`breadthUniverseUsed`、`cacheState`、`credentialSource`、`quality`、`directions`、`ruleVersion`、`calibration`、`disclaimer`、`providerCalls`。

| 字段 | 语义 |
|---|---|
| `schemaVersion` | 数据结构版本，当前 `1.0`。与 `ruleVersion`（规则族版本 `0.1`）不是一回事。缺该字段的结果下游必须拒绝解析。 |
| `reportId` | `{schemaVersion, asOf, benchmark, config, directions}` 的规范化 JSON（`sort_keys`、紧凑分隔符、`ensure_ascii=False`）取 SHA-256 前 16 位。 |
| `config` | 本次判定实际使用的全部阈值；两份报告只有 `config` 相同才可直接比较。 |

`reportId` 明确排除 `generatedAt`、`providerCalls`、`cacheState`、`credentialSource`：同一交易日、同一配置重跑必须同号，缓存冷热与调用次数不能改变身份。任一阈值或 `breadthUniverse` 变化都会换号。

`config` 冻结的键：

```json
{
  "weights": {"QTS-04-01-01": 0.25, "QTS-04-01-02": 0.15, "QTS-04-01-03": 0.2, "QTS-04-01-04": 0.2, "QTS-04-01-05": 0.2},
  "percentileTiers": {"boundaries": [0.2, 0.4, 0.6, 0.8], "scores": [0, 25, 50, 75, 100]},
  "minObservations": 60,
  "fullWindow": 250,
  "ruleWindows": {"relativeStrength5": 5, "relativeStrength20": 20, "turnover": 20},
  "minBreadthCoverage": 0.7,
  "breadthUniverse": 30,
  "quadrant": {"strengthTurnoverRatio": 1.2, "broadAdvanceRatio": 0.5},
  "pool": {"focusTotalScore": 70, "focusPersistenceScore": 60, "watchTotalScore": 50},
  "confidenceCoverage": {"high": 0.9, "medium": 0.7, "low": 0.5},
  "confirmation": {"horizonDays": 1, "closeMultiplier": 1.005, "closeChange": 0.005, "turnoverMultiplier": 1.0},
  "invalidation": {"horizonDays": 1, "closeMultiplier": 0.97, "closeChange": -0.03, "turnoverMultiplier": 0.8}
}
```

### 确认 / 失效谓词

`directions[].confirmation` 与 `[].invalidation` 是对象，不是字符串：

```json
{
  "text": "次日收盘不低于 1765.32（当日收盘 1756.53 的 +0.5%） 且成交额不低于 13428120460（20 日均额）",
  "horizonDays": 1,
  "all": [
    {"field": "close", "op": ">=", "value": 1765.32, "basis": "referenceClose*1.005"},
    {"field": "turnover", "op": ">=", "value": 13428120460.0, "basis": "mean(turnover,20)*1.0"}
  ]
}
```

- `field` 限定 `close` / `turnover` / `pctChange`；`op` 限定 `>=` / `>` / `<=` / `<`。
- `horizonDays` 表示报告日之后第几个交易日；`all` 内各条是与关系。
- `basis` 记录阈值的推导式，`value` 与 `text` 使用同一舍入（收盘两位小数、成交额取整），两者不会分叉。
- `horizonDays` 只支持单窗口单次求值；5 日累计口径需多次调用求值器（已知限制）。

求值入口 `predicate.evaluate(predicate, bars)`：`bars` 传入报告日之后的交易日（升序，`Bar` 或 `{date, close, turnover}`），返回 `met` / `unmet` / `unknown`。目标交易日缺行情、字段缺失或不支持的 `field`/`op` 一律 `unknown`，不抛异常，也不当作 `unmet`。

### 事实骨架与文章

`report.py` 的 `render_markdown()` 仍是纯函数，但定位已降级为**事实骨架**：agent 撰文底稿、`--format markdown` 的无模型兜底、校验器的参照物。它不再是对外主报告，也不承诺与文章逐字同源；文章是 JSON 的一个视图，回测只读 JSON。

骨架渲染规则：

- 缺失的 `score` / `percentile` 渲染为 `—`，不渲染为 0。
- `normalizedWeight` 为 `null`（该指标未计分）时权重列渲染 `—`，避免权重列合计超过 100%。
- 短历史指标聚合成一句「全部 N 项指标均为短历史（观测 a—b）」，不逐条重复。
- `status=insufficient` 时改为「一、结论 / 二、数据质量 / 三、口径与边界」三节，并列出全部原因。
- 标题为「板块层定向事实骨架」，首段声明它不是对外主报告；头部带 `契约 <schemaVersion> ｜ reportId <reportId>`。
- 固定包含免责声明与 `calibration needs-backtest`，不出现 `validated`。

### 机械校验

`scripts/check_report.py` 是确定性、离线的报告门禁：

```bash
.venv/bin/python scripts/check_report.py --result result.json --article article.md
```

- 退出码：`0` PASS / `1` FAIL / `2` 输入不可读或 JSON 非法。
- 输出 JSON：`status`、`checks`（`schemaVersion` / `numberProvenance` / `forbiddenWording` / `requiredItems`）、`issues`（含 `line` / `column`）、`report`（回显 `reportId` / `asOf` / `status`）。
- 检查一：**数字溯源**。抽取带单位 token（`%`、`×`、`亿`、`万`、`N 分`、`总分 N`）与无单位大数，归一后在 JSON 的全部数值中匹配，允许展示精度（半 ULP）加 1% 相对误差。日期、`QTS-04-01-*` 规则 ID、`881101.TI` 类代码与 `MA20` 类标识在校验前被屏蔽；无单位整数 ≤12 白名单（方向序号、小计数）。
- 检查二：**禁用措辞**。`买入` / `加仓` / `仓位` / `必涨` / `已验证` / `目标价` 逐处报行列。
- 检查三：**必备项**。免责声明（「不构成…建议」或「不是买点」）、`needs-backtest`、数据状态、每个方向的置信度（按 `confidence` 映射高/中/低/不足）。`insufficient` 时不要求方向小节，但必须写「本次不产出方向」并说明原因。
- 校验器不调用模型、不联网；同一 JSON 与同一文章重复校验结论一致。

呈现规则：PASS 才可贴文章；FAIL 时调用 `report.render_fallback(result, issues)`，它在首行标注「文章未通过校验，以下为事实骨架」，附失败项与行列位置后再拼接骨架。

## 降级语义

| 情况 | 输出状态 |
|---|---|
| CLI 或凭据缺失 | `insufficient` |
| 基准当日无日线 | `insufficient` |
| 行业当日无日线（全部） | `insufficient` |
| 行业当日无日线（部分） | 排除该行业 + 告警 |
| 成分股取数失败 | 该行业宽度记不足 + 告警 |
| 覆盖率 <70% | 该行业 `insufficient`，不参与排名 |
| 限流重试耗尽 | `degraded` |
| 任一方向存在 `insufficient` 指标 | 顶层 `degraded` |

任何情况下都不得用其他日期数据、历史缓存或合成值顶替目标日期。