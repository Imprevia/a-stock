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

## 产物契约

一次运行产出两份同源结果：

| 文件 | 写入开关 | 默认 | 读者 |
|---|---|---|---|
| JSON | `--output PATH` | 无（除非 `--format json` 打 stdout） | 机器 |
| Markdown | `--report PATH` | 给了 `--output` 时自动写同名 `.md` | 人 |

stdout 由 `--format` 控制：`json`（默认）/ `markdown` / `both`。

Markdown 报告由 `scripts/report.py` 的 `render_markdown()` 纯函数生成，只读 JSON，不重新计算任何指标，因此两份产物不可能出现数值分歧。渲染规则：

- 缺失的 `score` / `percentile` 渲染为 `—`，不渲染为 0。
- `normalizedWeight` 为 `null`（该指标未计分）时权重列渲染 `—`，避免权重列合计超过 100%。
- 短历史指标聚合成一句「全部 N 项指标均为短历史（观测 a—b）」，不逐条重复。
- `status=insufficient` 时报告改为「一、结论 / 二、数据质量 / 三、口径与边界」三节，并列出全部原因。
- 报告固定包含免责声明与 `calibration needs-backtest`，不出现 `validated`。

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