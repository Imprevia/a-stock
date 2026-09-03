## Context

仓库已经包含 70 篇原始交易系统文档、70 篇量化版文档和 327 个稳定规则 ID，但机器无法可靠区分规则定义、经验阈值、输入缺失和验证状态。现有 `src/market_environment/` 只覆盖五大指数的部分日线指标；仓库暂无 CI，文档门禁仅在本地 hook 执行。首期需要在不破坏现有 API 的前提下，建立可逐章扩展的规则平台，并让第 01 章 46 条规则能够在固定快照上确定性运行。

约束包括 Python 3.11+、跨平台运行、PR 测试不得依赖网络、外部数据源可能限流或缺失、现有阈值均不能默认视为收益有效。完整行情回填与盘后网络运行属于独立执行路径，不能影响离线门禁的可重复性。

## Goals / Non-Goals

**Goals:**

- 用版本化 YAML 表达规则、输入、阈值来源、评分、否决、缺失处理和文档映射。
- 通过命名 evaluator 注册表调用类型化 Python 函数，生成稳定的逐规则执行轨迹。
- 让证据包可验证输入、规则、代码和结果之间的对应关系。
- 为 327 条规则建立覆盖基线，并完整执行第 01 章 46 条规则。
- 在 GitHub Actions 中提供离线 PR 阻断和盘后可降级运行。

**Non-Goals:**

- 自动下单、券商连接、实盘账户或资金控制。
- 在本阶段证明规则具有超额收益或把经验阈值升级为 `validated`。
- 在 PR workflow 中访问行情或资讯网络接口。
- 一次性实现第 02 至 11 章的全部 evaluator。

## Decisions

1. **YAML 是机器规则事实源，Markdown 是解释层。** YAML 易于审阅并能由 JSON Schema 严格校验；Markdown 继续承载业务背景和人工复盘。CI 检查所有文档规则 ID 都存在于覆盖清单，且所有可执行 YAML 都引用有效文档。

2. **规则文件只保存声明式参数，不保存表达式代码。** `evaluator` 必须解析到 Python 注册表中的稳定名称。相比 `eval` 或动态导入，这可以限制执行边界、支持类型检查并让未知 evaluator 在加载阶段失败。

3. **第 01 章使用通用 evaluator 原语组合。** 比较、区间、比率、滚动分位、布尔聚合、加权得分、事件影响和市场分类由少量可测试函数实现；46 条规则各自保留独立 ID、参数和 trace，而不是生成 46 个不可维护的函数。

4. **输入快照采用规范化 JSON。** 键排序、有限数值、ISO 日期和显式数据状态保证跨平台哈希稳定。快照可包含日线指标、市场宽度、涨跌停、分层收益、板块集中度、大成交额个股、流动性和人工事件。

5. **证据包由 manifest 驱动。** `manifest.json` 记录 Git SHA、规则集版本、输入及结果 SHA-256、provider 状态和文件清单；逐规则 trace 与汇总结果分开保存。校验器重新计算哈希并拒绝缺文件、篡改或规则版本不一致。

6. **生命周期是显式状态机。** 仅允许 `draft -> defined -> backtested -> validated -> retired` 及规则变化导致的降级。`validated` 需要样本内、样本外、成本、置信区间、版本和回滚证据，首期注册规则最高为 `defined`。

7. **网络 provider 与核心执行器隔离。** provider 负责获取并标准化数据，执行器只读取快照。东财 provider 统一使用串行 limiter，最小间隔 1 秒加抖动，403 立即降级；provider 失败必须写入质量状态，不能伪造成零值。

8. **CI 分为两个信任域。** PR workflow 安装依赖后只运行 schema、fixture、golden、pytest、文档同步和 docs-contract；盘后 workflow 才允许访问网络，失败时仍上传带 `degraded` 或 `insufficient` 状态的证据 Artifact。月度清单仅提交小型哈希摘要。

## Risks / Trade-offs

- [量化文档中的 46 条规则输入粒度不一致] → 用统一快照字段和通用 evaluator 表达，无法由公开数据直接判断的主体意图只接受带来源的人工事件输入。
- [真实数据源不稳定或覆盖不足 500 日] → provider 记录来源、覆盖期和降级链；回测输出覆盖缺口并禁止晋级。
- [YAML 与 Markdown 漂移] → 覆盖检查双向校验规则 ID 和文档引用，CI 阻断漂移。
- [通用 evaluator 过度抽象] → evaluator 保持小而类型化，业务组合留在 YAML；只有无法表达且具备独立业务语义时才增加新 evaluator。
- [Git 中证据体积膨胀] → 只提交验证清单与月度哈希，完整快照和 trace 使用 CI Artifact。

## Migration Plan

1. 建立 OpenSpec、产品规格和 active plan，记录当前 327 个规则 ID 基线。
2. 引入 schema、loader、coverage 和文档同步检查，不改变现有市场环境 API。
3. 引入快照、执行器和第 01 章 46 条 YAML，在固定 fixture 上建立 golden 结果。
4. 引入证据、回测骨架和 CLI，再接入 GitHub Actions。
5. 验证通过后完成并归档 exec plan；OpenSpec change 在用户确认后单独归档。

回滚时可以移除新目录和 workflow，现有 `src/market_environment/` 与原始文档不受影响。规则文件变更通过 Git 历史恢复，证据包通过 manifest 的 Git SHA 定位。

## Open Questions

无。首期数据源真实回填的可用覆盖长度作为运行证据记录，不作为平台代码完成的前置条件。
