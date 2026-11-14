# qts04-sector-direction-skill Specification

## Purpose
为 Agent 提供 QTS-04 第 04 章 STEP 1 的板块层定向能力：通过 fuyao 官方接口取数，按五条已登记规则计算行业板块的相对强度、成交额增量、宽度与持续性，输出 1—3 个候选方向及可验证的次日确认与失效条件。

## Requirements

### Requirement: 数据来源必须是 fuyao 官方接口

Skill SHALL 通过 fuyao 官方接口获取板块目录、板块日线、成分股清单与个股日线，MUST NOT 读取仓库自身的 `/api/v2/market-environment/*` 接口或直接连接仓库数据库。Skill SHALL 以 `hithink-finance` 命令作为唯一取数通道。

#### Scenario: 使用官方命令取数

- **WHEN** Skill 需要行业板块目录
- **THEN** 它调用 `hithink-finance index catalog --tag industry --format json`
- **AND** 它不发起任何指向仓库 API 或数据库的请求

#### Scenario: 取数命令不可用

- **WHEN** `hithink-finance` 命令在 `PATH` 中不存在或不可执行
- **THEN** Skill 输出状态 `insufficient`
- **AND** 它给出安装或诊断指引
- **AND** 它不返回任何合成或缓存替代的板块方向结论

### Requirement: 凭据解析有明确优先级

Skill SHALL 按固定顺序解析 API Key：`FUYAO_API_KEY` 环境变量 → `MARKET_ENVIRONMENT_FUYAO_API_KEY` 环境变量 → `deploy/truenas/deploy.env` 中的 `FUYAO_API_KEY` → `--env-file` 指定的文件。它 MUST NOT 把 Key 写入 Skill 文件、缓存、日志、结构化输出或命令行参数。读取凭据文件时 SHALL 只取目标键，MUST NOT 读取或回显同文件的其他变量。

#### Scenario: 缺少凭据

- **WHEN** 所有凭据来源都不可用
- **THEN** Skill 输出状态 `insufficient` 并说明缺少凭据
- **AND** 它不尝试其他凭据来源，也不猜测或复用集群内 Secret

#### Scenario: 从 deploy.env 取得凭据

- **WHEN** 环境变量未设置而 `deploy/truenas/deploy.env` 含非空 `FUYAO_API_KEY`
- **THEN** Skill 使用该值发起调用
- **AND** 输出中的 `credentialSource` 为 `file:FUYAO_API_KEY@deploy.env`，且不含 Key 任何片段

#### Scenario: 环境变量优先于文件

- **WHEN** `FUYAO_API_KEY` 环境变量与 `deploy/truenas/deploy.env` 同时存在
- **THEN** Skill 使用环境变量
- **AND** 输出中的 `credentialSource` 为 `env:FUYAO_API_KEY`

#### Scenario: 输出不含凭据

- **WHEN** Skill 生成任何 JSON 结果、缓存文件或错误信息
- **THEN** 输出中不包含 API Key 明文或其片段

### Requirement: 五指标确定性计算

Skill SHALL 计算 `QTS-04-01-01` 至 `QTS-04-01-05` 五条规则的指标值：5 日相对强度、20 日相对强度、成交额增量、板块宽度、持续与恢复。每条指标 MUST 同时输出原始值、分位、得分、状态、权重与有效观测数。分母为零、行情无效或样本归属不明时，该指标值 MUST 记为 `null`，MUST NOT 以 0 代替。

#### Scenario: 完整窗口可用

- **WHEN** 某行业具备不低于 20 个交易日的连续板块日线且基准指数同日数据齐全
- **THEN** 该行业的 5 日与 20 日相对强度、成交额增量均输出非空数值
- **AND** 每条指标附带其有效观测数

#### Scenario: 分母为零

- **WHEN** 某板块的近 20 日均成交额为零或缺失
- **THEN** 成交额增量指标输出 `null`
- **AND** 状态标记为 `insufficient`，不输出 0

### Requirement: 滚动分位打分与分级降级

Skill SHALL 按 250 交易日滚动分位把指标映射为 0/25/50/75/100 五档得分，档位边界为 `≤P20=0`、`P20–P40=25`、`P40–P60=50`、`P60–P80=75`、`>P80=100`。有效观测达到 250 时状态 MUST 为 `ok`；60 至 249 时状态 MUST 为 `reduced-confidence`；不足 60 时状态 MUST 为 `insufficient` 且得分 MUST 为 `null`。

#### Scenario: 观测充足

- **WHEN** 某指标在滚动窗口内有 250 个有效观测
- **THEN** 状态为 `ok`
- **AND** 得分为五档之一

#### Scenario: 观测不足但仍可参考

- **WHEN** 某指标只有 60 至 249 个有效观测
- **THEN** 状态为 `reduced-confidence`
- **AND** 得分按同一五档边界计算
- **AND** 输出注明观测数

#### Scenario: 观测不足以下结论

- **WHEN** 某指标的有效观测少于 60 个
- **THEN** 状态为 `insufficient`
- **AND** 得分为 `null`
- **AND** 输出注明实际观测数

#### Scenario: 恰好达到 60 个观测

- **WHEN** 某指标的有效观测恰好为 60 个
- **THEN** 状态为 `reduced-confidence`
- **AND** 不得标记为 `ok`

### Requirement: 成分股覆盖率闸门

Skill SHALL 在给出行业排名前校验成分股有效覆盖率。有效覆盖率低于 70% 的行业 MUST NOT 参与排名，其状态 MUST 为 `insufficient` 并给出覆盖率数值。Skill MUST NOT 用不完整成分股样本推算宽度并当作有效结论。

#### Scenario: 覆盖率不足

- **WHEN** 某行业 100 只成分股中只有 60 只具备可用的 MA20 数据
- **THEN** 该行业覆盖率为 0.60
- **AND** 状态为 `insufficient`
- **AND** 该行业不出现在排名结果中

#### Scenario: 覆盖率合格

- **WHEN** 某行业成分股有效覆盖率为 0.85
- **THEN** 该行业参与排名
- **AND** 宽度指标附带 0.85 的覆盖率证据

### Requirement: 四象限分类只依赖原始值

Skill SHALL 依据上涨覆盖率与资金强度的原始值把行业归入四象限之一：真实流入、短线脉冲、权重拉升、资金撤退。该分类 MUST NOT 依赖分位是否可用。

#### Scenario: 高资金强度且覆盖广

- **WHEN** 某行业的成交额增量与相对强度处于高位，且上涨覆盖率为高
- **THEN** 该行业归入真实流入

#### Scenario: 分位不可用但原始值齐全

- **WHEN** 滚动分位因观测不足返回 `reduced-confidence`
- **THEN** 四象限分类仍然输出
- **AND** 输出注明分位维度已降级

### Requirement: 宽度计算的行业范围可配置

Skill SHALL 接受 `--breadth-universe N` 参数，只对综合分排名前 N 的行业抓取成分股并计算宽度。默认值 MUST 为 30。Skill MUST NOT 默认对全部行业逐个抓取成分股。

#### Scenario: 默认范围

- **WHEN** 调用方未指定 `--breadth-universe`
- **THEN** Skill 只对前 30 个行业计算宽度

#### Scenario: 扩大范围

- **WHEN** 调用方指定 `--breadth-universe 50`
- **THEN** Skill 对前 50 个行业计算宽度
- **AND** 输出中记录实际使用的范围值

### Requirement: 板块历史缓存

Skill SHALL 把板块日线缓存到本地可重建目录，缓存 MUST NOT 写入数据库、MUST NOT 提交到 git。缓存未命中或不足时 Skill SHALL 拉取所需窗口并补齐。

#### Scenario: 首次运行

- **WHEN** 本地没有该行业的板块日线缓存
- **THEN** Skill 拉取所需历史窗口并写入缓存
- **AND** 输出记录缓存状态为 `cold`

#### Scenario: 缓存命中

- **WHEN** 本地缓存已覆盖所需窗口且目标日期已存在
- **THEN** Skill 直接使用缓存
- **AND** 输出记录缓存状态为 `warm`

### Requirement: 方向输出包含确认与失效条件

Skill SHALL 输出 1 至 3 个候选方向，每个方向 MUST 包含板块总分、持续性分、四象限归属、五指标明细，以及带具体数值的次日确认条件与失效条件。数量 MUST NOT 超过 3 个。

#### Scenario: 存在合格方向

- **WHEN** 至少一个行业板块分不低于 50
- **THEN** Skill 输出最多 3 个方向
- **AND** 每个方向都带确认条件与失效条件的具体数值

#### Scenario: 无合格方向

- **WHEN** 所有行业板块分都低于 50 或全部被覆盖率闸门排除
- **THEN** Skill 输出空方向列表
- **AND** 它说明是被分数门槛还是覆盖率闸门排除

### Requirement: 同时产出机器可读与人工可读结果

Skill SHALL 在一次运行中同时提供 JSON 结果与 Markdown 报告。Markdown 报告 MUST 由 JSON 结果纯渲染生成，MUST NOT 重新计算任何指标，因此两份产物的数值 MUST 完全一致。

#### Scenario: 默认写出 Markdown 报告

- **WHEN** 调用方给出 `--output result.json`
- **THEN** Skill 同时写出 `result.json` 与 `result.md`
- **AND** `result.md` 包含结论速览表、每个方向的五指标表、次日确认与失效条件

#### Scenario: 缺分数不渲染成零

- **WHEN** 某指标 `score` 为 `null` 且 `normalizedWeight` 为 `null`
- **THEN** 报告把得分与权重渲染为 `—`
- **AND** 该方向的权重列合计 MUST NOT 超过 100%

#### Scenario: 报告不越界

- **WHEN** 生成 Markdown 报告
- **THEN** 报告包含免责声明与 `needs-backtest` 标记
- **AND** 报告中不出现 `validated`、买卖点、仓位或个股推荐

#### Scenario: 数据不足时报告不给方向

- **WHEN** 结果为 `insufficient`
- **THEN** 报告写明「本次不产出方向」并列出全部原因
- **AND** 它不渲染任何方向小节

### Requirement: 结论边界与规则状态

Skill SHALL 把全部规则状态标记为 `needs-backtest`。输出 MUST NOT 包含 `validated`、买入或卖出建议、仓位建议、个股推荐或交易指令。Skill MUST 说明结论是观察候选而非买点。

#### Scenario: 输出免责与状态

- **WHEN** Skill 生成任一方向结论
- **THEN** 输出中每条规则的状态为 `needs-backtest`
- **AND** 输出包含“候选与观察，不构成买卖建议”的说明

### Requirement: 取数失败按质量状态传播

Skill SHALL 在 fuyao 返回限流、空数据或调用失败时输出 `degraded` 或 `insufficient`，MUST NOT 用其他日期数据、历史缓存替代目标日期，或伪造成功。遇到 HTTP 429 或 `code=4001` 时 MUST 降低请求频率并有界退避。

#### Scenario: 触发限流

- **WHEN** fuyao 返回 429 或 `code=4001`
- **THEN** Skill 有界退避后重试有限次数
- **AND** 仍失败时输出 `degraded` 并说明限流原因

#### Scenario: 目标日期无数据

- **WHEN** 目标交易日不是第 04 章要求的已完成交易日，或该日板块日线为空
- **THEN** Skill 输出 `insufficient`
- **AND** 它不使用相邻日期数据顶替

### Requirement: 离线可测且默认不联网

Skill 的测试与校验 MUST 在无网络条件下通过。Skill SHALL 支持 fixture 输入模式，使五指标、覆盖率闸门、分位降级与四象限分类均可在离线状态验证。

#### Scenario: 离线测试运行

- **WHEN** 在无网络环境执行 Skill 的测试套件
- **THEN** 全部测试通过
- **AND** 测试过程中不产生任何外部请求

#### Scenario: fixture 模式

- **WHEN** 调用方提供本地 fixture JSON 而非真实取数
- **THEN** Skill 用 fixture 完成计算并输出结构化结果
- **AND** 输出记录数据来源为 fixture
