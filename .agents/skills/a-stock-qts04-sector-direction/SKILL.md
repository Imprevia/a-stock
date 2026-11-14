---
name: a-stock-qts04-sector-direction
description: 按 QTS-04 第 04 章 STEP 1 对 A 股行业板块做盘后定向：从 fuyao 官方接口取板块目录、板块日线、成分股与个股日线，计算 5 日/20 日相对强度、成交额增量、板块宽度与持续性，输出最多 3 个候选方向及其次日确认与失效条件。用于用户要求“板块定向”“今天/某日哪些板块值得跟”“板块四象限”“行业板块排名”时；不用于盘中预测、个股推荐、题材归因或自动交易。
---

# QTS-04 STEP 1 板块层定向

把 320 个行业板块压缩成最多 3 个可验证方向。所有结论是观察候选，不是买点；规则状态固定 `needs-backtest`。

数据只从 fuyao 官方接口取，不读本仓库的 v2 接口，也不连数据库。

## 前置条件

1. Node.js 22.12+ 与全局命令 `hithink-finance`（`@hithink-tech/hithink-finance-cli`）。
2. fuyao 凭据。解析顺序：`FUYAO_API_KEY` 环境变量 → `MARKET_ENVIRONMENT_FUYAO_API_KEY` 环境变量 → `deploy/truenas/deploy.env` 中的 `FUYAO_API_KEY`（该文件已被 git 忽略）。也可用 `--env-file` 指定其他文件。
3. 脚本只读取该文件里的 `FUYAO_API_KEY` 一行，不读同文件的其他变量；把 key 转成子进程的 `HITHINK_FINANCE_API_KEY`，不写进 argv、文件或日志。

任一缺失时脚本输出 `insufficient` 并给出原因，不返回任何替代数据。

## 工作流

1. 解析目标交易日：显式 `--as-of YYYY-MM-DD` 优先；未给时按 `Asia/Shanghai` 取当天，未到 15:10 结算则回退上一自然日。未来日期或当日未收盘一律拒绝。
2. 拉行业目录（`tag=industry`），再按每批 10 个代码拉板块日线（约 450 个自然日，覆盖 250 日分位窗口）。
3. 拉基准 `000001.SH` 日线。
4. 用只依赖日线的三个指标（5 日/20 日相对强度、成交额增量）加持续性做预排序。
5. 只对前 `--breadth-universe N` 个行业拉成分股与个股日线，算 `close > MA20` 比例。默认 N=30。
6. 组装五指标、做权重归一与滚动分位打分，套覆盖率闸门（<70% 不排名）。
7. 生成四象限归属与结构化确认/失效谓词（中文文本由同一组数值渲染），输出最多 3 个方向。
8. 写文章 → 跑 `check_report.py` → PASS 才呈现；FAIL 时回退事实骨架。

需要接入细节或排错时读 [数据合同](references/data-contract.md)；需要公式、权重、分位边界与四象限阈值时读 [打分规则](references/scoring-rules.md)。

## 脚本调用

离线 fixture（不联网，用于复算与测试）：

```bash
.venv/bin/python .agents/skills/a-stock-qts04-sector-direction/scripts/sector_pipeline.py \
  --as-of 2026-11-13 \
  --fixture tests/fixtures/a_stock_qts04_sector_direction/e2e.json \
  --breadth-universe 4 \
  --output /tmp/qts04.json
```

真实取数（需要前置条件与凭据）：

```bash
# 默认自动读取 deploy/truenas/deploy.env 的 FUYAO_API_KEY，通常无需额外设置
.venv/bin/python .agents/skills/a-stock-qts04-sector-direction/scripts/sector_pipeline.py \
  --as-of 2026-11-13 \
  --breadth-universe 30 \
  --output /tmp/qts04.json
```

需要临时覆盖凭据或指向别的文件时：

```bash
FUYAO_API_KEY=... .venv/bin/python .../sector_pipeline.py --as-of 2026-11-13
.venv/bin/python .../sector_pipeline.py --as-of 2026-11-13 --env-file /path/to/deploy.env
```

缓存默认落在 `.agents/skills/a-stock-qts04-sector-direction/.cache/qts04/`，已被 git 忽略；删除只影响首跑耗时。

## 三种产物：JSON 事实源、事实骨架、agent 文章

| 产物 | 生成方 | 用途 |
|---|---|---|
| JSON（`--output PATH`） | `sector_pipeline.py` | 唯一事实源：下游消费、回测、校验参照。带 `schemaVersion` / `reportId` / `config`。 |
| Markdown 事实骨架（`--report PATH`，或 `--format markdown`） | `report.py` 纯渲染 | agent 撰文底稿与无模型兜底；**不是对外主报告**。给 `--output` 而不给 `--report` 时写到同名 `.md`。 |
| 人读文章 | 你按下面的约束依据 JSON 撰写 | 唯一给用户看的版本，呈现前必须过 `check_report.py`。 |

`--format` 只控制 stdout：`json`（默认）/ `markdown` / `both`。

## 输出约束（四类，不是固定模板）

不规定小标题顺序，也不要求逐节照抄骨架，但四类约束必须满足：

1. **必备字段**：数据状态；每个方向写板块名与代码、总分、置信度、池位、四象限、次日确认、次日失效。五指标可压成一行，但不得省略总分与置信度。
2. **必备警告**：`degraded` 写明降级原因；`insufficient` 写明「本次不产出方向」并给出原因；任一指标为 `reduced-confidence` 时标注「短历史」。
3. **禁止措辞**：`买入`、`加仓`、`仓位`、`必涨`、`已验证`、`目标价`；也不写买卖点、个股推荐或交易指令。
4. **篇幅上限**：方向 ≤ 3 个；每方向 ≤ 5 行；全文 ≤ 40 行（不含免责声明行）。

数值必须直接取自 JSON，按事实骨架的精度书写（百分比两位小数、倍数两位小数、金额两位小数 + `亿`/`万`），不要自行换算或取整。校验容差按展示精度放宽，并额外允许 1% 相对误差。

## 呈现流程（必须按顺序）

1. 运行 `sector_pipeline.py` 拿到 JSON。
2. 依据 JSON 撰写文章；可以把事实骨架当底稿，但不能把骨架直接当最终文章。
3. 运行校验：

   ```bash
   .venv/bin/python .agents/skills/a-stock-qts04-sector-direction/scripts/check_report.py \
     --result /tmp/qts04.json --article /tmp/qts04-article.md
   ```

4. `status=PASS`（退出码 0）才可呈现文章，并在回复中贴出校验的 `status` 与 `checks` 摘要。
5. `status=FAIL`（退出码 1）时**不得**呈现文章：调用 `report.render_fallback(result, issues)`，首行标注「文章未通过校验，以下为事实骨架」，随后列出失败项及位置。退出码 2 属输入错误，按取数失败处理。

校验器确定性、离线、不调用模型：它只做数字溯源、禁词与必备项三类机械检查，不评价结论好坏。

## JSON 合同

JSON 顶层固定包含：`schemaVersion`、`reportId`、`config`、`asOf`、`status`、`source`、`benchmark`、`breadthUniverse`、`cacheState`、`credentialSource`、`quality`、`directions`、`calibration`、`disclaimer`。

- `schemaVersion` 是数据结构版本（当前 `1.0`），与 `ruleVersion`（规则族版本）不同；缺 `schemaVersion` 的结果下游必须拒绝消费。
- `reportId` 是 `{schemaVersion, asOf, benchmark, config, directions}` 规范化 JSON 的 SHA-256 前 16 位；同一交易日重跑不变，配置或任一阈值变化即变号。
- `config` 冻结本次判定实际使用的权重、分位五档边界、最少观测、覆盖率门槛、宽度范围、四象限/池位/置信度阈值与确认/失效系数。
- `directions[].confirmation` / `invalidation` 是对象：`{text, horizonDays, all:[{field, op, value, basis}]}`。`field` ∈ `close` / `turnover` / `pctChange`，`op` ∈ `>=` / `>` / `<=` / `<`；`text` 与 `all` 由同一组数值生成，禁止手写。
- 后验求值用 `predicate.evaluate(predicate, bars)`：`bars` 只放报告日之后的交易日（升序），返回 `met` / `unmet` / `unknown`；目标日缺行情返回 `unknown`，不得当作 `unmet`。

`credentialSource` 只标识来源（如 `env:FUYAO_API_KEY`、`file:FUYAO_API_KEY@deploy.env`），**永远不含 key 本身**。

`directions` 最多 3 条，每条必须带：

- `thscode` / `name` / `totalScore` / `confidence` / `persistenceScore` / `pool`
- `quadrant`（真实流入 / 短线脉冲 / 权重拉升 / 资金撤退，或 `null` 加原因）
- `metrics`：五条 `QTS-04-01-01`~`-05`，每条含 `value`、`percentile`、`score`、`status`、`weight`、`normalizedWeight`、`observations`、`missingReason`
- `confirmation` 与 `invalidation`：结构化谓词加同源中文 `text`
- `calibration: needs-backtest`

渲染给用户时保留方向数量上限与数值，不补写未出现的字段，不把 `null` 读成 0。

## 不变量

- 基准固定 `000001.SH`；只做 `industry` tag，不做概念、区域、特色指数。
- 分位窗口 250 个交易日；有效观测 <60 为 `insufficient` 且不给分，60—249 为 `reduced-confidence`，达到 250 为 `ok`。
- 五档边界固定：`≤P20=0`、`P20–P40=25`、`P40–P60=50`、`P60–P80=75`、`>P80=100`。
- 权重固定 25/15/20/20/20；指标缺失时按剩余有效权重重新归一，不得补 0。
- 成分股有效覆盖率 <70% 的行业不排名，状态 `insufficient`。
- 四象限只用原始值判定，分位降级不影响四象限输出。
- 池位：总分 ≥70 且持续性分 ≥60 为重点池；50—69 观察池；<50 不参与。
- 目标日没有日线时输出 `insufficient`，不得用相邻日期或旧缓存顶替。
- 限流（429 / `code=4001`）时有界退避后仍失败即 `degraded`。
- 不输出 `validated`、买卖点、仓位、个股推荐或交易指令。
- 不手写确认/失效散文；不为了让报告好看而改动 `config` 阈值。
- 校验未 PASS 的文章不得作为最终结论呈现。
- 不写数据库、不触发采集、不做部署、不修改规则库。