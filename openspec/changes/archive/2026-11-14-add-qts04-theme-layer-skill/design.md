## Context

见 `proposal.md` - Why。现状约束（2026-11-14 实测）：

- STEP 1 已交付 `a-stock-qts04-sector-direction`：`schemaVersion 1.0`、`reportId`、`config` 冻结块、结构化谓词与事实骨架；57 个离线用例。
- 五个模块 `fuyao_client` / `cache` / `contract` / `predicate` / `check_report` 位于 STEP 1 的 `scripts/` 下，STEP 2 若复制会分叉。
- 当日 112 个涨停原因 token 与 390 个概念名：精确匹配 9、模糊 11、无法映射 92。
- 宽概念会系统性误判：新能源汽车 1068 只成员命中 10 只涨停（lift 1.33），短剧游戏 100 只成员命中 7 只（lift 9.95）。
- 催化主源不可枚举：`notice-detail` 需 opaque `seq`、`article-detail` 需 `encoded-seq`、`stock-timeline-list` 返 `FUYAO_5003`。
- 数据窗口：涨停池约 12—13 个月；竞价机会、热榜历史、交易日历恰好 1 年（242 个交易日）；深度题材约 6.5 个月；概念成分股仅当前快照。
- 归档顺序：`qts04-theme-layer-skill` 是全新能力，不依赖尚未归档的 `add-qts04-sector-report-contract`。

## Goals / Non-Goals

**Goals:**

- 题材层可以用一句话复现：给定交易日，同一输入必然得到同一 `reportId` 与同一分级。
- 把"共同催化"从选词问题变成统计问题：成员共现 + 共享 token。
- 把"伪题材"从定性形容变成硬闸门：lift。
- 把"催化证实"的四级标签钉死在可机械判定的判据上，并显式声明 `confirmed` 不可达。
- 允许空结果，使弱题材日不产出编造的核心题材。
- 让题材归属的事后偏差进入数据（`quality`），而不是留在脚注里。

**Non-Goals:**

- 不实现 STEP 3 的个股成交额排名；"共同资金行为"只用概念指数成交额。
- 不实现回测执行器，只保证 JSON 具备被回测的条件。
- 不做题材到个股的角色分配（STEP 4/5）。
- 不覆盖概念板块以外的题材容器（地域、特色指数、自定义题材）。
- 不接数据库、不写 `trading-rules/`、不改 `src/`，不做调度与部署。

## Decisions

### D1 题材归属用成员共现，不用名称匹配

概念名与涨停原因词表是两套语料（实测 92/112 无法映射）。因此题材单元定义为 `概念成分股 ∩ 当日涨停池`，共享 token 在该交集内部统计。

理由：名称匹配依赖维护一张不断漂移的同义词表，且新造词（如"词元服务"）永远来不及收录；成员共现不依赖词表，且天然抗造词。

替代方案（未采用）：维护 token→概念的同义词表并做模糊匹配。当日就只能覆盖 20/112，且冲突时无法判定谁的归属正确。

代价：概念成分股是"当前快照"，回测存在事后归属偏差。由 D6 的 `quality` 声明承担，不在实现里假装解决。

### D2 lift 是分级硬闸门，不是排序加分

`lift = 当日涨停命中数 / (成员数 × 全市场涨停率)`。核心题材要求 lift ≥ 3.0；1.5 ≤ lift < 3.0 只能进扩散；lift < 1.5 直接判伪题材。

理由：实测宽概念命中数最多但 lift 最低（新能源汽车 10 只 / 1.33）。若做成加分项，宽概念靠绝对命中数仍会排到前面，"伪题材"判据形同虚设。

替代方案（未采用）：只用"涨停家数 ≥ N"做门槛。会让成员数 1000+ 的概念长期垄断榜首。

代价：lift 对分母敏感，全市场股票数口径必须冻结进 `config`，否则跨日不可比。

2026-11-13 实测校准：短剧游戏 lift 9.95 / 算力租赁 2.26 / 新能源汽车 1.33。若核心 lift 取 1.5，算力租赁会被误判为核心；取 3.0 才能把"当日绝对主线"与"次强扩散"分开。分数闸门同步校准为核心 ≥50、扩散 ≥35，因为该日短剧游戏的成员宽度仅 31.7%、最高连板 1，按 70 分闸门会把实测主线判成无核心。

### D3 催化四级标签，`confirmed` 显式不可达

| 标签 | 判据 |
|---|---|
| `confirmed` | 主源原文可定位且与 token 语义一致 |
| `partial` | ≥2 个独立厂商源指向同一 token，且成员同向 |
| `speculative` | 仅单一厂商源，或价格未确认 |
| `unknown` | 无 token，或 token 全属属性类 |

主源三处不可达已实测，因此 v1 的 `confirmed` 恒为 `unavailable`，作为顶层声明而不是逐条重复。

理由：允许实现者用"厂商 AI 摘要"填 `confirmed`，等于把整条流水线的证据等级虚标一档，回测结论随之作废。宁可封顶，也不虚标。

替代方案（未采用）：先按 `partial` 上线，等拿到公告列表接口再升级判据。这正是本设计的选择，区别只在于**现在就把上限写进合同**。

代价：报告里不会出现"已证实"，用户可能觉得信息量不足。可接受：这是事实。

### D4 属性类 token 用停用表 + 跨概念共现检测

停用表覆盖回购、业绩、次新、重整、摘帽、国企改革、实控人变更等；第二条判据是"该 token 命中股票分属 ≥3 个互不相关的概念"。

理由：停用表会滞后，跨概念共现能抓住新出现的"伪催化"（例如某日大量股票以"预重整"涨停，它只是状态描述而不是题材）。

代价：停用表需人工复核（记录为 Open Question）。

### D5 允许 `noCoreTheme`，并让它成为一等输出

弱题材日（如当日 38 只涨停）强行产出核心题材必然编造。`noCoreTheme = true` + 原因（lift / 共享 token / 梯队 / 分数）是合法输出，且报告必须有对应分支。

理由：这是唯一能同时约束脚本与 agent 的机制——agent 想写核心题材，校验器就能凭 `noCoreTheme` 判它失败。

### D6 `quality` 承载 point-in-time 声明

`quality = {pointInTime, membershipAsOf, backtestGrade}`；`backtestGrade` 按数据窗口分 A/B/C/D（价格资金 A、涨停与竞价 B、深度题材 C、成分股 D）。

理由：把"哪部分可回测"写在数据里，回测执行器就能按题材分别降级，而不是整份报告一刀切。

### D7 抽 `qts04-core`，STEP 1 改为引用

把 `fuyao_client` / `cache` / `contract` / `predicate` / `check_report` 移到 `.agents/skills/qts04-core/scripts/`，STEP 1 与 STEP 2 各自 `sys.path` 引入。

理由：`check_report` 要新增标签溯源；若两边各有一份，校验语义必然分叉，而校验分叉比代码重复更难发现。

代价：STEP 1 的 57 个用例需要调整导入路径；用 import shim 让旧路径继续可用，测试只改导入一行。

### D8 校验器新增标签溯源，但默认不启用

`check_report` 接受可选的标签映射 `{tier: [...], catalyst: [...]}`；未提供时只做原有三类检查。

理由：STEP 1 的 spec 明确是三类检查，新增必检项会改变它的行为。用"可选参数"实现，STEP 2 传入映射，STEP 1 不传，两边 spec 都自洽。

### D9 确认/失效沿用 STEP 1 的扁平谓词，不扩 schema

v1 用 `close` / `turnover` / `pctChange` 三个字段表达题材层的确认与失效（如概念指数收盘不低于某价位、成交额不低于 20 日均额）。

理由：`schemaVersion` 的扩张应留给真正需要的字段。题材专属字段（成员涨停数）留到 v1.1，避免一上线就有两套求值器。

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| 成分股仅当前快照 | 历史回测存在事后归属偏差 | `quality.backtestGrade=D` 显式声明；每日落盘 top 10 成员作为 point-in-time 起点 |
| lift 分母口径漂移 | 跨日 lift 不可比 | 把全市场股票数来源与取值冻结进 `config` |
| `confirmed` 永久不可达 | 报告证据等级偏低 | 顶层声明原因；把"公告列表接口"列为独立后续变更 |
| 概念板块只有 390 个 | 新题材可能无对应概念 | 输出 `unknown`/事件级并记录未映射 token，作为后续概念扩充输入 |
| 共享模块抽取引入回归 | STEP 1 57 个用例可能失败 | import shim 保持旧路径；先抽模块再改 STEP 1 引用，分两个任务验证 |
| 涨停池只有约 1 年 | 回测样本不足 | `backtestGrade=B`；回测报告必须写明样本区间 |
| 弱题材日空结果被误读为失败 | 用户以为脚本坏了 | SKILL.md 明确"空结果是合法结论"，文章必须写"今日无核心题材"及原因 |

## Migration Plan

1. 先在 STEP 1 旁新增 `qts04-core/scripts/`，把五个模块**复制**过去并加旧路径 shim。
2. 跑 STEP 1 全部用例，确认行为不变（`reportId` 不变）。
3. 改 STEP 1 的 import 指向 core，再跑一次用例。
4. 实现 STEP 2 的 `theme_pipeline.py`、`theming.py`、`theme_report.py`、`theme_check_report.py`，复用 core；文件名带 `theme_` 前缀，避免与 STEP 1 的 `report.py`/`check_report.py` 在共享 `sys.path` 下互相覆盖。
5. 校验器加可选标签映射，STEP 1 调用点不传。
6. 从 STEP 1 删除重复模块，保留 shim 一段时间。

回滚：删除 `.agents/skills/a-stock-qts04-theme-layer/` 与 `qts04-core/`，STEP 1 恢复原 import（shim 使两态都可用）。不涉及数据迁移与生产状态。

## Open Questions

以下四项已按 v1 默认值固化，实施时若需调整，先改本节再改代码：

- **题材成员快照位置**：v1 默认写入 `.agents/skills/a-stock-qts04-theme-layer/.cache/qts04/point-in-time/{asOf}.json`，与取数缓存同源、同样被 git 忽略。理由：缓存可重建，快照不可重建，两者放同一根但不同子目录，便于分别备份。
- **停用 token 表维护**：v1 默认内置在 `references/scoring-rules.md` 与 `config.stopTokens`，每次改动都进 `reportId`，因此谁改谁留痕；不做自动学习。
- **`overlapJaccard` 是否参与分级**：v1 默认**只记录不参与**分级。理由：重叠高可能只说明题材与板块同义，让它参与分级会把"板块即题材"的退化情形奖励成核心题材。该字段留作 STEP 4/5 的输入。
- **概念容器是否足够**：v1 只做 `cn_concept`。未映射 token MUST 写入 `unmappedTokens`，作为后续扩充概念的输入，不自行造题材。
