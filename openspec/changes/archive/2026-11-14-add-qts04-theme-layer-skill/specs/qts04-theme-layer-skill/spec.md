## Purpose

把 STEP 1 选出的板块方向收缩到可验证的题材层：用概念成员共现确定共同催化、用基准率校正判定题材真伪、用四级标签限定催化证实程度，并输出可被下游 Skill 与回测直接消费的 JSON。

## ADDED Requirements

### Requirement: 题材单元由概念成员共现确定

Skill SHALL 以「概念板块 × 当日涨停池的成员交集」作为题材单元，MUST NOT 以概念名与涨停原因词表的名称匹配作为题材归属依据。共享催化 token MUST 只在某概念的成员交集内部统计，且节点至少被 2 只成分股命中才算共享。

#### Scenario: 概念名与涨停原因词表不重合

- **WHEN** 某日涨停原因 token 无法映射到任何概念名
- **THEN** Skill 仍能产出该概念对应的题材单元
- **AND** 其共享 token 来自成员交集内部的统计结果，而不是名称匹配

#### Scenario: 共享 token 只被一只股票命中

- **WHEN** 某概念成员交集中只有一个 token 只被单只股票命中
- **THEN** 该 token MUST NOT 计入共享催化
- **AND** 该题材的催化一致性 MUST 随之下降

### Requirement: 题材真伪经基准率校正判定

Skill SHALL 为每个题材候选计算 `lift = 当日涨停命中数 / (成员数 × 全市场涨停率)`，并把 lift 作为分级硬闸门而非加分项。当 lift 低于阈值时，即使涨停命中数排名靠前，该题材 MUST NOT 被判为核心题材。

#### Scenario: 宽概念命中数最多但 lift 不足

- **WHEN** 某概念成员数过千、当日涨停命中数为全场最多，但 lift 低于阈值
- **THEN** 该题材 MUST NOT 进入核心题材
- **AND** 输出 MUST 说明它是成员基数导致的标签重合

#### Scenario: 小概念命中数不多但 lift 显著

- **WHEN** 某概念成员数较少、涨停命中数为中位数水平，但 lift 显著高于阈值
- **THEN** 该题材 MUST 进入核心题材候选
- **AND** 输出 MUST 记录 lift 值与其分母口径

### Requirement: 催化证实分为四级且 confirmed 显式不可达

Skill SHALL 将每条题材的催化标注为 `confirmed` / `partial` / `speculative` / `unknown` 之一。当主源（公告、交易所、政府文件）原文无法枚举定位时，Skill MUST 输出 `confirmed` 为不可达并给出原因，MUST NOT 用厂商 AI 摘要冒充主源。

#### Scenario: 主源不可枚举

- **WHEN** 当日所有催化证据只来自厂商聚合摘要
- **THEN** 该题材催化标签最高为 `partial`
- **AND** 顶层 MUST 声明 `confirmed` 不可达及原因

#### Scenario: 属性类 token 混入

- **WHEN** 某 token 命中的股票分属多个互不相关的概念，或该 token 属于回购、业绩、次新、重整等属性类
- **THEN** 该 token MUST 被排除出题材催化
- **AND** 若排除后无共享 token，该题材催化标签 MUST 为 `unknown`

### Requirement: 题材分级允许空结果

Skill SHALL 将题材分为核心、扩散、事件、伪题材四级，并允许当日无核心题材。当所有候选项都不满足核心条件时，Skill MUST 输出 `noCoreTheme = true` 与原因，MUST NOT 为凑满报告而降级计入核心题材。

#### Scenario: 弱题材日

- **WHEN** 当日涨停总数很少且没有任何题材满足核心闸门
- **THEN** Skill 输出 `noCoreTheme = true`
- **AND** 说明是 lift 不足、共享 token 不足还是梯队不足
- **AND** 不产出核心题材条目

#### Scenario: 存在合格核心题材

- **WHEN** 至少一个题材同时满足 lift、共享 token、梯队与分数闸门
- **THEN** Skill 输出该题材为核心题材
- **AND** 输出题材数量不超过上限

### Requirement: 输出可被下游与回测消费的 JSON

Skill SHALL 以 JSON 作为唯一事实源，JSON MUST 包含 `schemaVersion`、`reportId`、`config`、`asOf`、`status`、`quality`、`noCoreTheme`、`themes`、`disclaimer`。每条题材 MUST 带标识、分级、分数、指标明细、催化标签与来源、结构化确认与失效谓词、`calibration`。`config` MUST 冻结本次判定实际使用的阈值与权重。

#### Scenario: 上游 STEP 1 结果可关联

- **WHEN** 调用方提供 STEP 1 的 JSON
- **THEN** 输出的 `input.step1ReportId` MUST 记录上游身份
- **AND** 每个题材 MUST 给出与 STEP 1 方向成员的成员重叠度
- **AND** 缺 `schemaVersion` 的上游结果 MUST 被拒绝消费

#### Scenario: 同一交易日重跑身份稳定

- **WHEN** 同一交易日、同一配置重跑
- **THEN** `reportId` MUST 保持不变
- **AND** 缓存冷热、调用次数与生成时间 MUST NOT 影响 `reportId`

#### Scenario: 阈值变化可追溯

- **WHEN** 任一阈值或权重被修改
- **THEN** `config` MUST 反映新值
- **AND** `reportId` MUST 随之变化

### Requirement: 数据质量与回测边界必须显式声明

Skill SHALL 在 `quality` 中声明 `pointInTime`、`membershipAsOf` 与 `backtestGrade`。当概念成分股只有当前快照、没有历史版本时，Skill MUST 标注归属存在事后偏差，MUST NOT 声称该部分可严格回测。

#### Scenario: 成分股无历史版本

- **WHEN** 题材归属使用当日成分股快照
- **THEN** `quality.pointInTime` MUST 为 false 或标注受限
- **AND** 输出 MUST 记录 `membershipAsOf`
- **AND** 报告 MUST 披露题材归属不可严格回测

#### Scenario: 目标交易日无数据

- **WHEN** 目标交易日的概念日线或涨停池缺失
- **THEN** Skill 输出 `insufficient` 并说明缺失数据集
- **AND** MUST NOT 用相邻日期、旧缓存或合成值顶替

#### Scenario: 部分数据集限流

- **WHEN** 部分取数在退避后仍失败
- **THEN** Skill 输出 `degraded` 并列出受影响题材
- **AND** 受影响题材的分数 MUST 标为不可用而非 0

### Requirement: 独立运行与链式运行等价

Skill SHALL 支持两种入口：只给交易日独立运行，以及消费 STEP 1 JSON 的链式运行。独立运行 MUST 产出与链式运行相同结构的 JSON，差异只能体现在方向关联字段与 `input` 上。

#### Scenario: 独立运行

- **WHEN** 调用方只提供交易日
- **THEN** Skill 产出完整的题材 JSON
- **AND** 方向关联字段为 null 并说明原因
- **AND** 其余字段与链式运行保持同一合同

#### Scenario: 链式运行

- **WHEN** 调用方同时提供交易日与 STEP 1 JSON
- **THEN** 题材条目必须带方向重叠度
- **AND** 方向与题材的成员交集 MUST 可由 JSON 复算

### Requirement: 人读报告由 agent 撰写并通过机械校验

Skill SHALL 要求人读报告依据 JSON 撰写，并在呈现前通过确定性校验。校验 MUST 覆盖数字溯源、禁词、必备项与题材标签溯源；文章声明的题材分级与催化标签 MUST 能在 JSON 中找到对应值，否则校验失败。

#### Scenario: 文章把伪题材写成核心题材

- **WHEN** JSON 中某题材分级为伪题材，而文章称其为核心题材
- **THEN** 标签溯源校验 MUST 失败
- **AND** 文章 MUST NOT 作为最终结论呈现

#### Scenario: 弱题材日文章仍编造核心题材

- **WHEN** JSON 的 `noCoreTheme` 为 true，而文章写出核心题材结论
- **THEN** 校验 MUST 失败
- **AND** Skill 回退呈现事实骨架并标注失败项

#### Scenario: 校验通过

- **WHEN** 数字、分级、催化标签与必备项都与 JSON 一致
- **THEN** 校验返回通过
- **AND** 回复中 MUST 贴出校验状态与检查项摘要

### Requirement: 共享模块抽取不改变 STEP 1 行为

Skill SHALL 复用 STEP 1 的取数、缓存、合同与谓词能力，MUST NOT 复制出第二份实现。抽取共享模块后，STEP 1 的既有行为与输出契约 MUST 保持不变。

#### Scenario: STEP 1 回归

- **WHEN** 共享模块抽取完成后运行 STEP 1 的既有测试
- **THEN** 全部既有用例 MUST 通过
- **AND** STEP 1 的 JSON 字段与 `reportId` 计算方式 MUST NOT 变化

#### Scenario: 校验器兼容旧调用

- **WHEN** STEP 1 调用校验器且未提供题材标签映射
- **THEN** 校验器 MUST 保持原有的三类检查行为
- **AND** MUST NOT 因缺少标签配置而报失败
