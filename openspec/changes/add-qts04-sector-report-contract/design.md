## Context

见 `proposal.md` - Why。

现状约束（2026-11-14 实测）：

- `report.json` 顶层 15 个字段，无 `schemaVersion`、无 `reportId`、无 `config`。`ruleVersion: "0.1"` 是规则族版本，不是数据结构版本。
- `directions[].confirmation` 与 `invalidation` 是中文散文字符串，例如 `"次日收盘不低于 1765.32（当日收盘 1756.53 的 +0.5%） 且成交额不低于 13428120460（20日均额）"`。数值正确，但无法机器求值。
- `scripts/report.py` 的 `render_markdown()` 已实现纯渲染，57 个测试中 12 个覆盖它。
- 同仓库的 `a-stock-daily-tier-summary` 采用"脚本出 JSON、agent 按 SKILL.md 模板写复盘卡"，**没有校验环节**。本设计要把那条路的缺口补上，但不回改该 Skill。
- 归档顺序约束：`qts04-sector-direction-skill` 能力由尚未归档的 `add-qts04-sector-direction-skill` 引入，`openspec/specs/` 下尚不存在。本 delta 使用 MODIFIED，必须在归档前一个变更之后才能归档。

## Goals / Non-Goals

**Goals:**

- JSON 成为可跨 Skill 传递的接口：带版本、带身份、带冻结配置。
- 确认/失效条件变成可求值谓词，散文只是它的渲染结果。
- 人读文章由 agent 撰写，但必须过一道确定性校验才能呈现。
- 保持"无模型也能出报告"的兜底能力。

**Non-Goals:**

- 不实现 `verify` / `ledger` / `stats` 回测闭环。本变更只让报告**具备**被回测的条件，不实现回测执行。
- 不改 `trading-rules/`、`src/`、`coverage.yaml`，不接生产库。
- 不规定回测主口径（次日超额 vs 5 日累计超额），谓词带上 `horizonDays` 足以支持两者。
- 不做多语言报告。

## Decisions

### D1 谓词与散文同源生成，散文不可手写

`build_predicates()` 由当日收盘价、20 日均额等数值生成结构化谓词；`confirmation.text` 由同一组数值渲染。

理由：若散文单独手写，`text` 与谓词会在某次改动后悄悄分叉，而这正是回测最怕的。

替代方案（未采用）：只留谓词，散文交给 agent 生成。会让确认条件的措辞完全依赖模型发挥。

### D2 谓词采用扁平 `{field, op, value, basis}` 而非表达式树

单层 `all` 数组，评估窗口放在谓词顶层的 `horizonDays`，每条的 `basis` 记录阈值推导式（如 `referenceClose*1.005`）。字段限定在 `close` / `turnover` / `pctChange`，比较符限定 `>=` / `>` / `<=` / `<`。

理由：当前所有条件都是"与"关系，没有嵌套或析取。表达式树是过度设计，且求值器要处理优先级与括号。

代价：将来若出现"或"或分组条件，需要新增 `any` 或 `groups` 字段并升 `schemaVersion`。接受，因为可以演进。

### D3 `reportId` 排除易变字段

对 `{schemaVersion, asOf, benchmark, config, directions}` 取规范化 JSON 的 SHA-256 前 16 位。`generatedAt`、`providerCalls`、`cacheState`、`credentialSource` 不参与。

理由：同一交易日重跑应得到同一 `reportId`，否则无法把日报和验证结果对上号。`cacheState` 会因缓存冷热变化，必须排除。

替代方案（未采用）：对整份 JSON 取哈希。会把缓存状态和调用次数混进身份，同一天重跑就变号。

### D4 校验器只做三类机械检查

- **数字溯源**：正则抽出 `+12.34%`、`1.57×`、`13.43 亿`、`总分 100` 这类带单位的 token，归一成 float 后在 JSON 全部数值中找匹配（相对容差 1%）。纯小整数（`3 个方向`）走白名单，不参与溯源。
- **禁用措辞**：`买入`、`加仓`、`仓位`、`必涨`、`已验证`、`目标价`。
- **必备项**：免责声明、`needs-backtest`、数据状态、每个方向的置信度。

理由：三类都能纯字符串/数值比对，不需要模型，因此校验自身可测试、可复现。

代价：数字溯源会有假阳性（文章引用日期、序号）。缓解是只校验带单位的 token，并对小整数开白名单。

### D5 `report.py` 降级为事实骨架，不删除

保留 `render_markdown()`，改称"事实骨架"，用途变为：

1. agent 撰文时的底稿，降低遗漏；
2. `--format markdown` 的无模型兜底；
3. 校验器的参照物。

理由：删掉会失去"离线、无模型也能出报告"的能力，而这是排障时的最后手段。保留但降级，避免两份人读产物争夺"主报告"地位。

替代方案（未采用）：删除 `report.py`，12 个测试一并删除。会让 CI 失去对渲染规则的守护。

### D6 SKILL.md 输出段落改为约束而非模板

约束包含四类：必备字段（方向标识、总分、置信、池位、四象限、确认、失效）、必备警告（`insufficient` / `reduced-confidence` / `degraded` 必须显式提到）、禁止措辞（同 D4 禁词表）、篇幅上限（方向 ≤3、每方向 ≤5 行）。

理由：固定模板会让每日报告长得一样，用户会停止阅读。约束保留结构底线，允许按当日情况压缩。

### D7 校验失败时降级，不阻塞

校验不通过时，Skill MUST 回退呈现 `report.py` 的事实骨架，并在末尾标注"文章未通过校验，以下为事实骨架"。

理由：宁可给用户一份干巴巴但正确的骨架，也不能因为措辞不合格就不给结论。

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| `confirmation` 类型由 string 变 object 是破坏性变更 | 任何依赖旧格式的下游会解析失败 | 用 `schemaVersion` 显式拒绝旧版；披露在 proposal 的 BREAKING 标记中；当前唯一消费者是尚未实现的 STEP 2 |
| MODIFIED 依赖前一变更先归档 | 归档顺序错误时 archive 被拒绝 | tasks 把归档列为 0.1 前置任务；`openspec validate` 已给出 INFO 提示 |
| 数字溯源假阳性 | 合格文章被误判失败 | 只校验带单位 token；小整数白名单；容差 1%；失败信息给出具体 token 便于判断 |
| 数字溯源假阴性（文章写了 JSON 之外的定性判断） | 越界措辞漏检 | 靠禁词表兜底；禁词表可扩充，作为配置而非硬编码 |
| agent 绕过校验直接呈现 | 校验形同虚设 | SKILL.md 规定呈现前必须运行校验；校验输出 PASS 才允许贴文章 |
| `horizonDays` 只支持单日，5 日窗口需多次求值 | 5 日口径求值变慢 | 明确记录为已知限制；回测执行阶段可在求值器上做批量 |

## Migration Plan

1. 先归档 `add-qts04-sector-direction-skill`，使 `openspec/specs/qts04-sector-direction-skill/` 存在。
2. 实施本变更，`schemaVersion` 从 `1.0` 起。
3. 由于当前无外部消费者，不提供旧格式兼容层；`schemaVersion` 缺失即拒绝。

回滚：删除 `scripts/check_report.py`、还原 `sector_pipeline.py` 与 `report.py`、SKILL.md 回退到模板措辞。JSON 字段为纯新增（除 `confirmation` / `invalidation` 类型），回滚不影响历史报告的可读性。

## Open Questions

- 回测主口径（次日相对基准超额 vs 5 日累计超额）尚未定。这不是本变更的阻塞项：谓词带 `horizonDays`，两种口径都能表达，待实现回测执行时再定。
- 文章篇幅上限的具体行数是经验值，需要在若干交易日后按实际阅读体验调整。