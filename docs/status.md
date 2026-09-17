# 仓库状态

## 已实现

- 2026-09-14 启动 `market-environment-multipage-rework`：目标是保持 01–09 独立页面，补齐第 01 页市场级句式和第 01/09 页精确下一交易日只读对照；实现进行中，尚未宣称完成。

- harness 骨架：`docs/` 事实源体系、exec-plans 落地位、本地门禁（`.githooks/` + `scripts/check-docs-contract.py` + `scripts/install-hooks.py`）。
  - 事实源：`docs/repository-guide.md`、`docs/architecture.md`、`docs/runbooks.md`
- `搭建交易系统/` 已完成目录归档：11 个章节各自使用唯一章节目录，章节总览和正文不再散落于下载批次子目录。
- `docs/trading-system-directory.md` 已记录交易系统知识库的完整目录和文件清单，并由 `AGENTS.md` 提供入口说明。
- `搭建交易系统-量化版/` 已按原目录的 70 个相对路径完成量化重写：统一 YAML 元数据、330 个稳定规则 ID、固定/分位混合阈值、五档评分、风险否决、缺失处理和校准状态。
- `docs/trading-system-quantified-directory.md` 已记录量化版完整目录和维护规则；所有经验阈值当前均为 `needs-backtest`，没有规则被宣称为 `validated`。
- 市场环境分析看板：`src/market_environment/` + `apps/market-environment-dashboard/`。
  - 已接入 5 个指数、MA5/10/20/60、20/60 日区间位置、成交额比值、趋势/量价状态。
  - 已实现 mootdx → 百度 → 腾讯历史降级、腾讯实时交叉校验、指数进程内短缓存、非交易日回退和错误质量标记。
  - 已新增一级导航 `如何判断市场环境` 与 01 至 09 二级文档视图，覆盖指数、市场广度、涨跌停生态、行业主线、容量方向、事件边界和综合判断。
  - 已通过可选 `chapter01` 契约接入精确市场广度、日期化涨停/跌停/炸板池、行业排名和成交额 Top-N 股票；历史日期不复用今日快照。
  - 已覆盖计算、provider、服务层和 API 契约测试，并通过前端生产构建与桌面/移动浏览器检查。
  - 已修复上证指数和中证500成交额缺失：新浪指数 K 线按腾讯实时成交额校准，量价状态不再误报“数据不足”。
  - 已实现第 01 页第四部分“指数、趋势位置和成交额结合判断”：每个指数输出六类明确组合或显式未分类证据，第 01 章汇总市场强弱、阶段、资金认可和交易模式；页面支持随指数切换同步更新，不使用兜底分类。
  - 第 01 篇学习资料已增加盘后最短操作闭环：每天抄录 7 项看板结果，归入偏强、分化、偏弱、未定型或数据不足，再从数据质量、指数方向、市场宽度、MA20 和成交确认中选择最可能改变结论的一项作为次日验证；配套确认/失效/仍不明确条件、假设示例和连续 20 日训练表。
  - 第 01 篇已补充置信度方法：区分联合确认、四问矩阵和章节覆盖率三个位置，明确高置信度表示证据一致或反驳明确，不表示上涨概率；量化版同步记录分支条件和覆盖率阈值。
  - 已将指数 K 线深度提升至 280 根，新增五态同步性、MA20 斜率/量价推进效率滚动分位、五指数均线多头比例、收束句与分层缺失原因；第四部分重组为四问结论条、五指数乘六组合矩阵和选中行证据。
  - 已补全五态 `syncPattern` 的联合研判：`synchronizationAssessment` 独立返回广度、MA20 位置和成交额确认，区分同步上涨、权重护盘、成长占优、普遍走弱和未定型分化；精确前一交易日广度缺失时不回退旧快照、不调用 provider，并以 `insufficient` 保留风险边界。第 01 页在四问矩阵前展示结论、置信度、三项维度、证据和风险；桌面与 390px 已完成无页面横向溢出检查。
  - 已修复看板日期错位和东方财富主域连接拦截导致的市场广度缺失：浏览器与 API 使用正确日期边界，全 A 完整快照兼容 `diff` 数组和键值对象；主域失败或分页受限时按排序分页降级计算，上涨家数、下跌家数和涨跌幅中位数只使用有效样本。
  - 已拆分数据加载：保留完整聚合接口，网页首屏改用指数核心接口，第 02、03、05、06、08、09 页按需加载章节证据；章节失败不会清空核心数据，同日期 provider 结果按数据集缓存并复用。
  - 已实现市场数据 PostgreSQL 持久快照与盘后预计算：`breadth` 直接走精确分页统计，`activeDirection` 使用成交额 Top-N；支持 exact-date、checksum、settled freshness、跨连接 lease/fencing、stale-while-revalidate、刷新 CLI、回滚开关和可选缓存质量元数据。SQLite 仅作为停写迁移输入与归档。
  - 已新增 `/data-collection` 数据管理页和五类独立采集任务：`core`、`breadth`、`limits`、`sectors`、`activeDirection` 支持单项或一键采集，单项失败不停止或回滚成功兄弟任务；核心指数进一步隔离五个指数子结果。
  - 已实现 collection run/task、失败保留、精确日期状态、lease 去重、重启恢复和 materialized aggregate；普通市场环境 GET 只读本地聚合/快照，手工 POST 默认开启并可由 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 显式关闭。
  - 数据采集页首次状态请求不再复用研究页的 15:00 截止日期；当前实现由后端按上海有效市场日初始化，09:30 开市前回退上一工作日/真实交易日并校验实际日期证据；用户改选历史日期后继续发送显式日期。
  - 东方财富请求已在进程内全局串行，并对连接/读取失败、429 和 5xx 有界重试，403 立即失败；行业排名支持 `push2` 到 `push2delay` 降级，领涨股名称按真实 `f128` 字段解析且不跨日期保留。
  - 容量方向已支持 `push2` 到 `push2delay` 的统一 Top-N 校验和可审计降级；当前市场日真实 smoke 在主域断连后保存 `eastmoney-clist-delay` / `fallback` 的 30 个观察样本，双端点失败继续使用精确日期的 `failed-retained` / `failed-missing`。本次新增修复计划将补齐响应形态兼容和涨跌停池逐池延迟降级。
  - 数据采集管理已通过 124 个 Python 测试、11 个前端测试和生产构建；当前市场日行业真实 smoke 在主域断连后由 `eastmoney-clist-delay` 成功返回 100 条记录。
  - 已提供单镜像 k3s 部署配置：`deploy/k3s/` 保留历史清单，`deploy/helm/a-stock/` 提供 PostgreSQL StatefulSet/ClusterIP/Secret 引用、应用资源与调度参数；运行时仅 PostgreSQL 持久化，应用工作负载不挂载数据库 PVC。
  - TrueNAS k3s 组件化部署已落地：`scripts/deploy-truenas-k3s.sh --component all|database|service|schedule` 共享一个 Helm release，`all` 固定按 `database -> service -> schedule` 执行；database 使用 PostgreSQL Retain RWO PVC，service/schedule 仅通过 existingSecret 连接配置访问，旧 SQLite PVC 仅作为迁移输入保留。离线 manifest 与 TrueNAS scheduling guard 套件未访问真实 TrueNAS、provider 或生产 PVC。
  - 已新增部署内盘后自动采集：k3s/Helm CronJob 的业务目标为 `Asia/Shanghai` 工作日 16:30，覆盖五类数据并与 Dashboard 共享 PostgreSQL、task/lease 和失败隔离；native timezone 限 1.27+，1.26 的 controller 兼容实现与 TrueNAS overlays 已形成离线实现。生产调度保持 fail-closed 默认（`enabled=false / suspend=true`）。
  - scheduled-refresh 在周末无 provider 调用并返回 skipped，结算前拒绝；`partial` 保留成功兄弟任务且不自动整批重跑。旧结构化 CommonMark/Bash AST 审计和发布测试结果均为历史证据：它们未覆盖 canonical rollback binding、label/shape drift 下的 active-to-off 补偿，以及 stdin/source/alias 等二次解释路径。focused/deployment/guard 与 fake-provider 测试范围绑定 `cd26dff3e6bebe012198dcd38074c354c1a9afac`；全库、OpenSpec、docs-contract、clean/review 证据绑定冻结 docs-only review/evidence tip `4f6d2b28b1694c78f53eb3ce007b8530b0667ead`，旧 SHA 结果不作为当前验收。
- 交易规则工程化产品范围已定义：`docs/product-specs/trading-rule-engineering.md`。
- OpenSpec change `engineer-trading-rules-ci` 已建立 proposal、4 份 capability spec、design 和 19 项实施任务。
- 已修正干净环境依赖冲突：`httpx` 采用 mootdx 0.11.7 支持的 `>=0.25,<0.26` 区间，保证 CI 可解析安装。
- 交易规则工程平台已实现：330 条覆盖清单、第 01 章 49 条 YAML 规则、确定性执行、证据、回测骨架、CLI 和两条 GitHub Actions workflow。
- 固定快照生成 49 条 trace；新增三条规则不进入 `QTS-01-00-01`，既有规则 trace 保持不变。
- `rework-market-breadth-page`（2026-09-16）已完成第 02 页复盘重构：`BreadthEvidence` 与 `BreadthAnalysis` 同步扩展 11 个字段（`declineRatio` / `advanceDeclineSpread` / 3 个 250 日分位 / `momentum` / `momentumPercentile` / `indexConsistent` / `widthLabel` / `widthLabelReason` / `history` / `percentile250`），新增 `BreadthHistoryPoint` 模型；`_enrich_breadth` 通过 `snapshot_store.get("breadth", date)` 拉取最近 5 个交易日历史快照计算 250 日滚动分位、5 日动量、指数广度一致性与 6 档宽度标签（含自然语言依据）；02 页由 2 section 替换为 5 section（复盘卡 / 量化证据 / 近 5 日趋势 / 指数一致性矩阵 / 次交易日验证项 + 质量元数据），新增独立 `breadthChart` ECharts 双轴折线；前端测试 46 项通过（含 7 项新增 breadth-page 渲染 + 390px viewport），Python 测试 278 项通过（市场环境 + 交易规则），docs-contract fast/full 通过；不修改 `QTS-01-02-01..05` 规则 ID、阈值与权重，`rules validate` 仍输出 49 条规则，不引入新 provider、新 API 路由、新 PostgreSQL schema 或新采集任务。

## 进行中

- SQLite 到 PostgreSQL 迁移实现已完成：已加入 SQLAlchemy/psycopg/Alembic 配置、原生 DATE/TIMESTAMPTZ/JSONB schema、SQLite 指纹/导入 CLI、Helm StatefulSet/ClusterIP/PVC/Secret 合同、schema migration Job，以及 TrueNAS operator override 的 PostgreSQL Service/Secret 合同；全量离线测试、部署渲染、文档和 OpenSpec 门禁通过。Helm/TrueNAS 运行时通过 Secret 注入 PostgreSQL URL 并 fail-closed；SQLite seam 仅保留给显式离线 fixture 和一次性导入工具。生产迁移、真实 provider smoke 和生产写入仍未执行，需独立维护窗口授权。

- `document-truenas-podman-k3s-deployment` 仍为 active exec plan；`schedule-after-market-data-collection` 实现已完成，OpenSpec change 已归档。
- `consolidate-helm-managed-scheduling` 仓库层已完成：operator override 清单/脚本和专用 `market-environment-data` PVC/PV 模板已删除，suspended/active overlay 对齐 live controller `Asia/Shanghai` 的 `30 16 * * 1-5`，全量离线 577 passed / 3 skipped，docs-contract full 通过。2026-09-17 只读发现确认 legacy CronJob 已 absent，但目标 namespace 尚无 `a-stock-postgresql` Service/Secret/StatefulSet；Helm CronJob 依赖 PostgreSQL，因此生产调度写入 fail-closed 阻断。`manual-local` SC 同时承载生产 `a-stock-data` 和其它 namespace 的 PV，必须保留；专用 PVC/PV/目录清理要等 PostgreSQL cutover + suspended CronJob 精确读回后执行。

## 最近完成

- `fix-market-collection-effective-date-and-timezone`（2026-09-15）已完成代码、离线验证及生产 15→14 覆盖迁移：API、采集协调器、刷新 CLI 统一使用上海有效市场日；09:30 前回退上一工作日并拒绝未来日期；提供 SQLite 迁移输入的 `relabel-date` dry-run/apply/rollback 审计迁移；采集页“最近尝试/最近成功”固定按北京时间显示。PostgreSQL 生产切换和包含修复的镜像重新部署仍未执行。
- Operator override 临时绕过路径已退役：2026-09-13 的 controller `Asia/Shanghai`、`30 16 * * 1-5` 与 PostgreSQL Service/Secret 证据保留在 completed plan；新的 schedule 资源统一由 Helm release `a-stock` 管理。仓库不再提供非 Helm-owned CronJob 清单或修正脚本。
- 市场环境看板 live server 已确认是 k3s `v1.26.6+k3s-6a894050-dirty`，主机时区 `Asia/Shanghai` 且 NTP 已同步；冻结镜像为 `localhost/a-stock-market-environment:20260906-005226-2075b6e` / `sha256:8fc74dcf37f5e6303e42f78811ef9de16759cb6e045aa57648e027cd1449754b`。Helm revision、Dashboard imageID 与网络边界不在本次 schedule-only override 范围，仍按后续受控 preflight 复核。
- `complete-limit-ecosystem-dashboard-parity` 的第 03 页完整涨跌停生态看板实现与受控验证已完成：契约、事实表迁移、严格 provider、相邻交易日晋级、梯队/制度/交易所分层、近 5 日与 60/250 日覆盖、前端状态和离线门禁均已落地；隔离 smoke 因 provider 缺少顶层交易日字段而 `failed-missing`，`promotionQuality=insufficient`，未写生产 PostgreSQL。limits detail/V1 开关默认关闭，旧五字段仍是兼容基线。
- `complete-limit-ecosystem-dashboard-parity` 的第 03 页完整涨跌停生态看板实现与受控验证已完成：契约、事实表迁移、严格 provider、相邻交易日晋级、梯队/制度/交易所分层、近 5 日与 60/250 日覆盖、前端状态和离线门禁均已落地；隔离 smoke 因 provider 缺少顶层日期字段而 `failed-missing`，`promotionQuality=insufficient`，未写生产 PostgreSQL。limits detail/V1 开关默认关闭，旧五字段仍是兼容基线；已验证 `push2ex` 缺顶层日期时的查询绑定路径和逐池延迟降级。
- `fix-limit-and-active-direction-collection`（2026-09-15）已完成 provider 响应兼容和离线修复：涨跌停池支持 `push2ex` 到 `push2delay` 逐池降级、键值对象池、查询日期绑定证据和显式日期冲突拒绝；容量方向支持统一字段别名/响应容器解析并继续执行 30 行与成交额排序校验。provider/采集回归和 docs-contract 已通过；真实 provider smoke、生产镜像部署和 PVC 写入仍未执行。

## 未实现

- 高位股、中位股和低位股的分层亏钱效应尚未形成独立可追溯数据集。
- 第 03 页 limits detail 的真实 provider 证券制度、ST/上市窗口、板块和收盘状态覆盖仍未完成证明；本次修复允许对明确 `date` 查询记录 `request-parameter` 日期绑定，但在真实 smoke 重新证明字段覆盖前，晋级率、梯队/分层和 250 日分位必须保持 `insufficient` / `degraded`，不视为 `validated`。
- 公告、政策、外围和突发事件仍需结构化来源、发布时间、有效期与失效条件；当前保持 `unverified`。
- 第 02 至 11 章 281 条规则仍为 `documented-only`。
- 尚未积累 500–750 日历史快照，没有规则可晋级为 `validated`。

## 当前风险

- 真实行情源受网络可用性影响；页面会显示降级来源、过期报价和部分失败 warning。
- `push2` 与 `push2delay` 同属东方财富，供应商整体不可用时行业和容量方向采集仍会失败；同日期成功快照会保留，不会用其他日期替代。
- 手工采集接口仍无应用级认证或 TLS。TrueNAS NodePort 候选上线后，所有能路由到 `192.168.1.20:32001` 的客户端均可匿名触发 provider 调用和 PostgreSQL 写入；持久共享入口仍需后续接入认证授权，异常时先将 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`，再按现场捕获的 pre-release 网络与 release 基线回退。
- 第一版定时任务不维护交易所节假日日历；周一至周五节假日会留下 failed/partial 审计记录，但精确日期校验禁止跨日期落盘。
- 当前 PostgreSQL 为单主实例；事务 lease/fencing 可支持 Dashboard 与 CronJob 并发访问，但多主/跨节点 HA、复制和自动故障切换仍不在本次范围。
- 通达信不可用时五个指数仍串行进入降级链，本机冷缓存核心请求约 34 秒；章节拆分已避免额外证据继续阻塞首屏，但指数 provider 仍需独立优化。
- 真实历史数据能否达到目标 750 日取决于 provider 覆盖；不足 500 日时不得形成验证证据。
- `.codex/`、`.opencode/` — agent 工具会话目录（是否入库待确认）
- 本机无 Python 时本地 gate 退化为警告放行（记录于 `docs/runbooks.md`）。

## 下一步

- 评估指数 provider 的连接失败熔断、可复用探测或线程安全并发方案，缩短冷缓存核心响应。
- 定时采集下一检查点是受审 packet 的只读 preflight、审核与生产激活决策；激活或回退由本次操作责任人书面确认后通过专用入口（`--release-suspended` / `--activate-schedule` / `--disable-schedule`）执行，候选 diff 仅允许已审阅的 `spec.suspend: true -> false` 字段变化。生产 CronJob 激活或回退必须由本次操作责任人书面确认。
- operator override 下一检查点是受控 PostgreSQL 切换后的首次自然触发；需核对 Job/Pod 日志、五类数据状态、schema migration 证据与数据库备份校验，失败或 partial 必须保留真实质量证据。
- 后续评估交易所节假日日历、认证和多节点 HA；当前版本保持单主 PostgreSQL、ReadWriteOnce PVC 与有界进程内 executor。
- 另行定义东方财富多层级行业板块筛选口径，并评估独立供应商备胎。
- 为分层亏钱效应建立稳定样本口径，并补齐文档 04 的真实 provider。
- 积累 500–750 个交易日快照，回测市场环境阈值与分类稳定性。
- 后续按覆盖清单逐章实现第 02 至 11 章 evaluator。

## 最后更新

2026-09-16
