# 仓库状态

## 已实现

- 2026-09-27 新增本地交易知识 MCP：`src/trading_knowledge/` 将原版/量化版 Markdown、YAML 规则、coverage 和 Git 证据摘要离线索引到 `.artifacts/knowledge-base/`，提供中文检索、精确引用、规则/证据/索引状态和五个只读 stdio MCP 工具。索引记录来源层级、行号、规则 ID、生命周期、证据状态和内容 hash；当前构建为 143 个源文件、3,699 个 chunk、330 个规则记录，`evidence/rules/index.yaml` 的 `latestEvidence: null` 保持 `insufficient`，不把经验阈值解释为已验证收益。

- 2026-09-14 启动的 `market-environment-multipage-rework` 已完成：01–09 独立页面、第 01 页市场级句式和第 01/09 页精确下一交易日只读对照均已落地。

- harness 骨架：`docs/` 事实源体系、exec-plans 落地位、本地门禁（`.githooks/` + `scripts/check-docs-contract.py` + `scripts/install-hooks.py`）。
  - 事实源：`docs/repository-guide.md`、`docs/architecture.md`、`docs/runbooks.md`
- `搭建交易系统/` 已完成目录归档：11 个章节各自使用唯一章节目录，章节总览和正文不再散落于下载批次子目录。
- `docs/trading-system-directory.md` 已记录交易系统知识库的完整目录和文件清单，并由 `AGENTS.md` 提供入口说明。
- `搭建交易系统-量化版/` 已按原目录的 70 个相对路径完成量化重写：统一 YAML 元数据、330 个稳定规则 ID、固定/分位混合阈值、五档评分、风险否决、缺失处理和校准状态。
- `docs/trading-system-quantified-directory.md` 已记录量化版完整目录和维护规则；所有经验阈值当前均为 `needs-backtest`，没有规则被宣称为 `validated`。
- 市场环境分析看板：`src/market_environment/` + `apps/market-environment-dashboard/`。
  - 已接入 5 个指数、MA5/10/20/60、20/60 日区间位置、成交额比值、趋势/量价状态。
  - 已实现 Fuyao v2 capability-gated core 主源及 mootdx → 百度 → 新浪 → 腾讯 → 东方财富历史降级、当前日期腾讯实时交叉校验、指数进程内短缓存、非交易日回退和错误质量标记；默认开关仍关闭。
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
  - 已提供单镜像 k3s 部署配置：`deploy/k3s/` 与 `deploy/helm/a-stock/` 提供 PostgreSQL StatefulSet/ClusterIP/Secret 引用和应用资源；运行时仅 PostgreSQL 持久化，应用工作负载不挂载数据库 PVC。当前部署合同不再提供 Kubernetes 市场数据调度创建或激活参数。
  - TrueNAS k3s 普通组件固定为 `all|database|service`，共享一个 Helm release；database 使用 PostgreSQL Retain RWO PVC，service 仅通过 existingSecret 连接配置访问，旧 SQLite PVC 仅作为已停写迁移输入保留。普通入口在任何 build/write 前只读检查 Helm stored manifest、release-derived former identity 和 legacy `market-data-collection`；任一旧 CronJob 存在或状态不确定即 fail closed，且脚本不做暂停、删除、接管或激活，遗留处置必须另建计划。
  - 当前盘后自动采集合同为 Hermes Agent 调用默认关闭的七数据集 full endpoint；上海日期、结算、provider、PostgreSQL、lease 和失败隔离仍由后端掌握。Hermes caller/prompt 已作为版本化资产落地，但生产 automation gate、Hermes job 与投递目标尚未启用。
  - **历史审计（已退役，不可执行）**：旧 k3s/Helm CronJob、schedule component 与 `scheduled-refresh` 曾承担五数据集工作日采集；旧 CommonMark/Bash AST、fake-provider 和发布测试结果分别绑定 `cd26dff3e6bebe012198dcd38074c354c1a9afac` 与 `4f6d2b28b1694c78f53eb3ce007b8530b0667ead`。这些只证明当时实现，不是当前命令、部署或回滚入口。
  - TDX 盘后包已新增 `tdx-stock-universe-v1` 普通 A 股过滤边界：`breadth` 和 TDX 派生 `activeDirection` 只消费过滤后的普通股票，质量对象保留原始/保留/排除/未分类数量、按市场保留统计和排除原因；过滤后不足时返回失败/保留语义，不把约 5 万行全证券包作为 A 股广度样本。2026-09-23、2026-09-24 已在新镜像中按原日期完成生产重采集，保留数分别为 5560 / 5561，未分类均为 0。
- 交易规则工程化产品范围已定义：`docs/product-specs/trading-rule-engineering.md`。
- OpenSpec change `engineer-trading-rules-ci` 已建立 proposal、4 份 capability spec、design 和 19 项实施任务。
- 已修正干净环境依赖冲突：`httpx` 采用 mootdx 0.11.7 支持的 `>=0.25,<0.26` 区间，保证 CI 可解析安装。
- 交易规则工程平台已实现：330 条覆盖清单、第 01 章 49 条 YAML 规则、确定性执行、证据、回测骨架、CLI 和两条 GitHub Actions workflow。
- 固定快照生成 49 条 trace；新增三条规则不进入 `QTS-01-00-01`，既有规则 trace 保持不变。
- **历史审计（2026-10-09，不可执行）**：`activate-fuyao-sector-fallback` 当时获授权完成真实 probe、production capability 写入、配置 rollout 与一次 collection。revision 95 上曾通过当时存在的 `snapshots scheduled-refresh --dataset sectors` 得到 runId `e7c06da411124f5097f26c44b08f3820`、source=fuyao、status=fallback、10 obs；该 CLI 与 Kubernetes 调度路径现已退役，不得复制为当前操作或回滚方式。`provider_capability_reports` 的历史 checksum `b763a32e…b2a`、CronJob/Job absent 和 Secret/PVC identity 证据继续保留。

- `unify-market-data-acquisition-adapters`（2026-10-08）已完成五数据集 typed `CollectionOutcome`、dataset acquisition plan、source adapter、typed committer/local projector 与进程内共享 transport policy gateway 的实现和离线验证；normal runtime 不再继承 legacy provider，Fuyao raw HTTP 已纳入共享 gateway，稳定 alias 与有调用者的兼容路径按退役矩阵保留。`requests` 保持默认；Scrapling 仅为独立、默认关闭、空生产 allowlist 的静态 HTTP profile。focused 为 `448 passed, 3 skipped`，全量为 `1104 passed, 6 skipped`，规则三门禁和 OpenSpec strict 通过；未访问真实 provider、写生产 PostgreSQL/PVC、部署 Kubernetes、修改 Secret 或激活调度。

- `refactor-market-environment-backend-architecture`（2026-10-07）已完成 OpenSpec 1–7.4：应用/领域/基础设施分层、provider-free 查询、五类 collector、PostgreSQL repository/UoW、aggregate CAS、API boundary mapper、架构 AST/import 门禁和兼容矩阵均已落地。兼容矩阵为 API/provider/exact-date/failure-retention/lease/CAS/import `152 passed, 2 skipped`，调度/部署/验证器矩阵 `206 passed, 100 skipped`；当前进入文档同步、全量 pytest 和最终门禁。未访问真实 provider、生产 PostgreSQL、Kubernetes 写入口或激活调度。

- `unify-provider-http-collection` 已完成现有 requests-bound host policy 基线：腾讯、百度、新浪、TDX 和 Eastmoney 的已接入路径具备现代 session UA、请求门与抖动、连接/读取/408/429/5xx 有界重试、`Retry-After`、single-flight、短成功缓存、日期隔离、请求预算和失败冷却探测；Fuyao 与部分兼容调用仍保留专用 session/API-key request gate，待 `unify-market-data-acquisition-adapters` 纳入 composition-root gateway。focused transport/provider 回归为 105 passed，OpenSpec strict、docs-contract full 和规则门禁通过；全量 pytest 的 4 个失败是本机缺少 `mcp` 依赖及 Windows bash 路径兼容问题。默认不引入代理池、Cookie 伪造或 TLS 指纹模拟，真实网络 smoke 仍需授权的盘后隔离环境。
- `evaluate-fuyao-market-data-provider` 已完成 Fuyao v2 core/breadth 契约、共享请求门、分数据集路由、activeDirection 保持 Eastmoney/TDX、离线 fixture/回归和架构/runbook/产品规格同步；真实 probe、core shadow 差异归因、breadth/sectors 日期与字段完整性修复，以及隔离 PostgreSQL capability/shadow smoke 均已完成并记录在 active plan。所有新开关保持关闭，未批准生产 revision；全量测试本轮 735 passed、3 skipped，另有 2 个既有性能阈值抖动失败（非本变更逻辑）。
- `restore-sector-data-via-independent-provider` 代码、离线验证和 2026-09-29 受控隔离观察已完成：扶摇 `THS` 行业目录/快照/交易日历适配、Eastmoney 双端点失败后的 capability-gated fallback、同日期失败留存、provider-free status/run API 和前端日期归一均已落地。当次 `fuyao-market-v2` 隔离证据为 320/320 覆盖、10 行结果、精确 `asOf=2026-09-29`、四个已证明字段；`mainNet/mainNetPct/upCount/downCount/leader` 全部保持 null 并记录 warning。**截至 2026-09-29 该观察时点** `FUYAO_SECTORS_ENABLED=0`、`FUYAO_SECTORS_SHADOW_ENABLED=0`，未写入正式 sectors 主源快照；该历史关闭状态已被 2026-10-09 Helm revision 95 的受控启用与一次正式 collection 取代，不代表当前生产开关。
- `enrich-fuyao-sector-fields-from-eastmoney-dataapi` 已完成离线实现：扶摇行业成功后可选调用东方财富 `dataapi/bkzj/getbkzj`，固定字段为 `f3,f6,f62,f104,f105,f128,f184`、过滤为 `m:90+s:4`；共享 host policy、latest-only/结算后门禁、严格身份匹配、百分比归一、fill-only 合并和 same-vendor lineage 已通过 focused 测试。默认 `MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED=0`，尚未执行真实 probe 或正式快照写入。
- `activate-scheduled-collection-20260929` 的历史 revision 70 已被 2026-09-30 应用发布取代；当时的激活与首个自然触发证据记录在 `activate-scheduled-collection-20260930`，只作为五类质量和 `collection_runs` 的历史审计，不代表当前调度状态。
- `restore-limit-ecosystem-data-availability` 正在接入扶摇三类池和交易日历，拆分 membership 与高级分层质量，补齐六日回填、证券明细以及第 03/04 页真实 limits 数据消费；生产部署和生产写入不在范围内。
- `document-truenas-podman-k3s-deployment` 仍为 active exec plan；已归档的 `schedule-after-market-data-collection` 只保留历史审计，已由 Hermes 调度替换 change 明确取代，不再代表可执行能力。

## 进行中

- `fix-ths-catalog-revision` 的仓库内离线修复和生产控制门禁 1.1–6.7、生产 7.1–7.3 已完成。7.1 收口 revision 110 安全停写基线，已丢失的原 `Failed=True` Kubernetes Job 继续作为获准的不可恢复缺口；7.2 创建 2,885,212-byte custom dump（SHA-256 `8d459ecc3a8d3dc4cc09428afceef263ffa54d976583738b51db22a596a188c5`）并在全新 loopback-only PostgreSQL 16.4 中证明 `0007`、跨日期共存与 37 表历史不变。7.3 从 clean reviewed HEAD `021071cbb7e3ce87dd59806226642cb916db6d75` 发布镜像 `20261015-100802-021071c`（archive SHA-256 `35d412a2b9e3be1fefad99630a3ae3e653d2b20b4b8eea04ead364dec46900bd`，containerd digest `sha256:ada52cb449d09ed3def9290a732d3d6925e23cbdcbe00893d38525affc8ed4fc`）；revisions 111/112/113 完成 migration/service/full release，生产现为 v10/0007。Deployment→ReplicaSet→Ready Pod、PVC/Secret、4 capability、旧 846 事实、3/11 审计与 THS operation 均未漂移；5 个 provider-free GET 为 200 且调用前后 run/task/operation 总数与哈希一致，manual POST=403、writer=0、CronJob/Job absent。下一步受上海 2026-10-15 15:10 结算边界阻塞，边界后仅运行一次获授权的 THS 三任务。
- `add-fuyao-ths-sector-datasets` 的 revision 幂等/nullable `changePct` 修复已于 2026-10-14 部署到 TrueNAS k3s。revisions 106/107 的 CronJob 受控激活及其 `30 16 * * 1-5` 配置只保留为历史证据；激活未即时创建 Job，计划中的首次自然触发没有完成验收。后续 `fix-ths-catalog-revision` 7.1–7.3 已将生产收敛到 Helm revision 113、schema v10/0007、manual=0、writer=0、CronJob/Job absent，并保持旧数据与审计不变。不得为补自然触发证据而重建 revision 107 调度；两个交易日观察改由 `replace-market-collection-scheduling-with-hermes` 7.5 承接。
- `replace-market-collection-scheduling-with-hermes` 当前为 `production-7-2-single-schema-hook-validated-awaiting-refreeze`（29/34）：tasks 1.1–7.1 已完成，task 7.2 已授权。OpenSpec、事实文档、部署脚本与测试已协调并验证 single-hook 合同：调度/provider-backed collection Job 始终 absent；唯一临时例外是 database 阶段精确的 provider-free `a-stock-schema-migration`，service/final all 使用 `--no-hooks`，成功后全部 Job absent，失败则停止并保留证据。聚焦回归 `191 passed`、扩展部署回归 `252 passed`，Shell/Helm/OpenSpec/docs-contract/diff 门禁通过；正在重新冻结 immutable candidate。生产仍为 revision 113、schema v10/0007，manual=0、automation env absent、writer=`0|0|0|0|0`、CronJob/Job absent、关键计数 `103|246|2|846|846|846`、PVC/Secret UID 和 task 7.1 dump SHA-256 均无漂移。旧候选 `291a8de` 已 superseded，不得部署。未授权 gate 修改、full endpoint/provider、Hermes 主机或 job 写入；THS 7.4、额外同日 THS 重采和 tasks 7.3–7.6 仍需另行授权。
- **历史审计（2026-10-13）**：`add-fuyao-ths-sector-datasets` 的 10.3 capability apply + 10.9 `pg_dump` + 隔离 PostgreSQL 恢复演练完成；dump `/tmp/a-stock-pgdump-20261013.dump`（sha256 `1723b24c…3ee5`）在隔离 PostgreSQL 恢复 39 表，生产 capability 从 1 行增加到 4 行且旧 `fuyao/sectors/fuyao-market-v2` 未变。revision 98 当时的 THS fail-closed env、镜像/PVC/Secret、CronJob absent、健康与零 provider 写证据继续保留；当时 values 中的旧调度关闭字段仅是历史 release 记录，现已从当前 Chart/values 合同退役，不得作为操作输入。
- `add-sector-continuity-metrics`（2026-10-12）已完成 Stage 10 离线实现与验证；OpenSpec 为 `56/60`。task 11.1 已获用户授权，但上海时间 `10:57` 尚未到 `15:30` 盘后窗口，且 CLI 未配置 source-specific 真实 probe adapter。四类默认 dry-run 均证明 `networkCalls=0`、`formalWrites=0`，真实 taxonomy/membership/adjusted-price/benchmark probe 未运行，候选源继续为 `unverified`。tasks 11.2–11.4 未授权，经验阈值保持 `needs-backtest`。

## 最近完成

- **历史审计（2026-10-08，不可执行）**：`deploy-unified-market-data-adapters-20261008` 曾通过当时的 schedule-disable 模式在 revisions 83/84 暂停并删除 retained CronJob，随后 revisions 85/86/87 收敛 database/service/完整 release。该旧模式已退役；当前普通脚本只读拒绝 former identity，不执行遗留资源 mutation。
- **历史审计（2026-09-17 至 2026-09-22，不可执行）**：`consolidate-helm-managed-scheduling` 曾创建 suspended 基线并激活 revision 26；该状态已由 revision 84 删除和 revision 113 absent 基线取代。当前仓库不再由 Helm 管理新的 schedule 资源，`manual-local` 仅因仍承载共享 PV 保留。
- `fix-tdx-breadth-stock-universe`（2026-09-25）完成 TDX 普通 A 股 universe 过滤、生产部署、只读 real probe、2026-09-23/24 精确日期重采集、provider/collection/API 契约、文档更新和离线门禁；生产 CronJob 按 fail-closed 规则保持 absent。
- 2026-09-30 使用受控 TrueNAS k3s 入口部署 `main`（`40c3498`）：先清理暂停的 Helm-owned CronJob（revision 77），再以 `--component all` 完成 database/service/完整清单收敛（revisions 78/79/80）。镜像 `localhost/a-stock-market-environment:20260930-115139-40c3498` 已导入目标 containerd，digest 为 `sha256:53c1219db808acd6860286725fa77ebda7da40f8dbcbf8e66e001056cfe05883`；Deployment 与两个 Pod Ready/Running，两个 PVC Bound，CronJob absent，NodePort `/api/health` 返回 200。调度保持 disabled，未创建 Job 或触发 provider 采集。
- 2026-09-17 完成 TrueNAS PostgreSQL 生产切换与 SQLite 历史导入：生产 dry-run 发现并修复 migration Job `fsGroup`、只读 WAL `immutable=1` 和 revision trigger 冲突；隔离 PostgreSQL 16.4 集成测试 11 项通过，正式导入 `snapshot_entries=46`、`core_index_results=65`、`materialized_market_environment=10`，最新历史日 API 200。
- `fix-market-collection-effective-date-and-timezone`（2026-09-15）已完成代码、离线验证及生产 15→14 覆盖迁移：API、采集协调器、刷新 CLI 统一使用上海有效市场日；09:30 前回退上一工作日并拒绝未来日期；提供 SQLite 迁移输入的 `relabel-date` dry-run/apply/rollback 审计迁移；采集页“最近尝试/最近成功”固定按北京时间显示。PostgreSQL 生产切换和包含修复的镜像重新部署仍未执行。
- **历史审计（2026-09-13，不可执行）**：operator override 的 controller `Asia/Shanghai`、`30 16 * * 1-5` 与 PostgreSQL Service/Secret 证据保留在 completed plan。override 和后续 Helm-owned schedule 路径均已退役；当前仓库不提供任何 Kubernetes CronJob 创建、激活或修正入口。
- 市场环境看板 live server 已确认是 k3s `v1.26.6+k3s-6a894050-dirty`，主机时区 `Asia/Shanghai` 且 NTP 已同步；冻结镜像为 `localhost/a-stock-market-environment:20260906-005226-2075b6e` / `sha256:8fc74dcf37f5e6303e42f78811ef9de16759cb6e045aa57648e027cd1449754b`。Helm revision、Dashboard imageID 与网络边界不在本次 schedule-only override 范围，仍按后续受控 preflight 复核。
- `complete-limit-ecosystem-dashboard-parity` 已完成并归档：契约、事实表、严格 provider、相邻交易日晋级、梯队/分层、历史覆盖和前端状态均已落地；旧 smoke 因东方财富字段不足保持 `promotionQuality=insufficient`，成为本次扶摇接入的基线。
- `fix-limit-and-active-direction-collection`（2026-09-15）已完成 provider 响应兼容和离线修复：涨跌停池支持 `push2ex` 到 `push2delay` 逐池降级、键值对象池、查询日期绑定证据和显式日期冲突拒绝；容量方向支持统一字段别名/响应容器解析并继续执行 30 行与成交额排序校验。provider/采集回归和 docs-contract 已通过；真实 provider smoke、生产镜像部署和 PVC 写入仍未执行。

## 未实现

- 高位股、中位股和低位股的分层亏钱效应尚未形成独立可追溯数据集。
- 第 03 页高级制度、板块和独立亏钱收益字段仍可能不足；基础 membership 晋级可在交易日、完整分页和规范身份已证明时使用，但高级分层和 250 日分位仍不得冒充 `validated`。
- 公告、政策、外围和突发事件仍需结构化来源、发布时间、有效期与失效条件；当前保持 `unverified`。
- 第 02 至 11 章 281 条规则仍为 `documented-only`。
- 尚未积累 500–750 日历史快照，没有规则可晋级为 `validated`。

## 当前风险

- 真实行情源受网络可用性影响；页面会显示降级来源、过期报价和部分失败 warning。
- `push2` 与 `push2delay` 同属东方财富，供应商整体不可用时行业和容量方向采集仍会失败；同日期成功快照会保留，不会用其他日期替代。
- 扶摇行业 fallback 虽已确认 320/320 目录和快照覆盖，但其接口不提供资金流、市场宽度和领涨股；即使正式开关获批，行业结果也只能解释为带 warning 的降级指数排名，不能冒充完整行业事实。
- 生产已部署 date-and-content-addressed THS catalog observation identity（schema v10/0007），但 7.4 的盘后真实三任务证据和尚未实施的 Hermes 两日观察仍未完成。禁止删除旧证据、改 checksum、补零、裁剪目录、伪造抓取时间或用其他日期替代；同日重采只有在完整 catalog 内容不变时才应复用 revision，跨日必须保留不同 date-addressed revision。
- 东方财富 dataapi 行业补充为 latest-only、同供应商且仅观测到 128 行；扶摇 THS 与东方财富 BK 分类不同，必须保守匹配并显示覆盖缺口，不能将补充结果解释为独立 provider 或历史数据证据。
- 生产手工采集当前已关闭。已实现但默认关闭的 Hermes automation endpoint 没有应用级认证或 TLS，只能在操作方明确接受的非公网可信路由边界内另行启用；所有能路由到 `192.168.1.20:32001` 的客户端届时都将具备调用能力，idempotency、CORS 和 lease 不是认证。
- 计划中的 Hermes 工作日调度仍不维护交易所节假日日历；周一至周五节假日必须留下 skipped/failed/partial 的真实结果，精确日期校验禁止跨日期落盘。当前 Kubernetes CronJob/Job absent，Hermes 尚未启用。
- 当前 PostgreSQL 为单主实例；事务 lease/fencing 可支持 Dashboard 与后续 Hermes 触发的后端任务并发访问，但多主/跨节点 HA、复制和自动故障切换仍不在本次范围。
- provider host policy 当前及目标均为进程内边界，不提供多 Pod 的分布式限流；可选 Scrapling 尚无获批生产 host，allowlist 必须保持为空。
- 通达信不可用时五个指数仍串行进入降级链，本机冷缓存核心请求约 34 秒；章节拆分已避免额外证据继续阻塞首屏，但指数 provider 仍需独立优化。
- 真实历史数据能否达到目标 750 日取决于 provider 覆盖；不足 500 日时不得形成验证证据。
- `.codex/`、`.opencode/` — agent 工具会话目录（是否入库待确认）
- 本机无 Python 时本地 gate 退化为警告放行（记录于 `docs/runbooks.md`）。

## 下一步

- `fix-ths-catalog-revision` tasks 1.1–7.3 已完成；生产为 Helm 113、v10/0007、不可变镜像 digest 已冻结，schedule/manual/writer 仍关闭，provider-free 验收与历史零漂移通过。下一步必须等待 2026-10-15 15:10 Asia/Shanghai 后运行 exact THS trio；结算前不得以 `--force`、改时间或手工 POST 绕过。7.4 完成后继续保持 Kubernetes CronJob/Job absent，旧 7.5 不恢复调度，等待 Hermes change 7.5 的 canary、两个完整交易日和 THS lineage 证据。
- `replace-market-collection-scheduling-with-hermes` task 7.2 已授权，single-hook 实现与离线门禁已通过：下一步用独立 Git index/detached worktree 冻结新 immutable candidate，复核生产无漂移后执行 backend/schema rollout 与 provider-free 验收。当前授权不得沿用到 7.3，也不授权 automation gate、full endpoint/provider、Hermes 主机、job 或投递目标写入。
- `add-fuyao-ths-sector-datasets` 的 capability、dump 与隔离恢复历史继续保留；旧 revision 98/99 的调度关闭字段只描述当时 release，不是当前配置输入。后续小批 catalog/history/member 操作仍需按原计划分别授权，历史 `sectors` 证据不得改写；清理隔离 PostgreSQL 容器也仍需用户复述。
- `add-sector-continuity-metrics` 下一步先补齐并审阅 source-specific 真实 probe adapters，再于上海工作日 15:30 后继续已授权的 task 11.1；四类报告未完成前保持 `56/60` 和 `unverified`。非测试数据库 migration/backfill、生产部署和调度激活继续分别授权。
- `activate-fuyao-sector-fallback` 下一步运行 6.1 全量复测（focused、pytest、`rules validate/coverage`、`docs sync-check`、`openspec validate --strict`、`scripts/check-docs-contract.py --mode=full`）后归档本次 change；自动采集保持 absent，sectors 仍按 enabled 状态提供 fallback/partial 数据。
- `deploy-unified-market-data-adapters-20261008` 已完成 revision 87 生产发布；保持当前不可变镜像、PVC 和调度 disabled/absent 基线，调度恢复或真实 provider probe 必须另行授权。
- 归档 `unify-market-data-acquisition-adapters` change；Scrapling 生产 allowlist 继续保持为空。后续若有获批 host 或要执行真实 provider probe/生产 rollout，必须另建受审计划并遵循盘后、安全与回滚边界。
- 归档已完成的 `restore-sector-data-via-independent-provider` change；后续如需正式生产启用，必须在盘后按 runbook 重新审阅部署 packet、Secret、数据库目标和失败回滚，不得将本次临时 SQLite 证据迁入生产。
- 评估指数 provider 的连接失败熔断、可复用探测或线程安全并发方案，缩短冷缓存核心响应。
- 定时采集 revision 26/70/107 均为历史状态；当前 revision 113 已证明 CronJob/Job absent。未完成的自然触发验收不再通过 Kubernetes 补做，转由 Hermes change 的 canary 与两日观察承接。
- 旧 operator override 的首次自然触发检查点已取消；后续只按 Hermes canary 与两个完整上海交易日观察七数据集、通知、THS lineage 和 provider-free 读回，失败或 partial 必须保留真实质量证据。
- 后续评估交易所节假日日历、认证和多节点 HA；当前版本保持单主 PostgreSQL、ReadWriteOnce PVC 与有界进程内 executor。
- 另行定义东方财富多层级行业板块筛选口径，并评估独立供应商备胎。
- 2026-09-30 和 2026-10-14 的 Kubernetes 调度激活均为历史；当前 revision 113 的 CronJob/Job absent 是有效基线。后续自动观察只按 `replace-market-collection-scheduling-with-hermes` 实施和授权；重新引入 Kubernetes scheduling 必须另立 change，禁止直接创建、修改或回滚出 CronJob。
- 为分层亏钱效应建立稳定样本口径，并补齐文档 04 的真实 provider。
- 积累 500–750 个交易日快照，回测市场环境阈值与分类稳定性。
- 后续按覆盖清单逐章实现第 02 至 11 章 evaluator。

## 最后更新

2026-10-15
  - **Hermes 调度替换离线实施推进至 20/34**：已完成持久幂等与 structured failure、七数据集 sync-first full endpoint、独立 automation gate、Hermes caller/prompt 与 v0.12.0 安装合同、前端结构化失败显示；当前进入 5.x Kubernetes 调度路径退役。TrueNAS 普通部署的当前合同是在任何 build/write 前只读检查 Helm stored manifest、release-derived `a-stock-data-collection` 和 legacy `market-data-collection`，发现遗留或状态不确定即 fail closed；普通脚本不 mutation，处置必须另建计划。生产仍为 revision 113、CronJob/Job absent、manual=0、writer=0，未启用 automation、未写 Hermes 主机且未调用 provider。
  - **THS 7.5 验收转交 Hermes**：取消旧计划中的 Kubernetes schedule restoration，保持 THS 7.5 未完成；Hermes 7.5 承接 canary、两个完整上海交易日、七数据集 provider-free 读回、THS 同日/跨日 revision 与三任务 lineage 验收。生产继续保持 Helm revision 113、v10/0007、manual=0、writer=0、CronJob/Job absent。本次只修订规划与事实文档，未改代码、生产集群、Hermes 主机、数据库或 provider 状态。

### 历史审计日志（不可执行）

以下带日期记录只描述当时的 release、命令和开关；其中出现的 Kubernetes schedule 模式、旧 CLI 或关闭字段
均已退役，不得复制到当前部署、回滚或恢复流程。

2026-10-13
  - **Fuyao THS 10.5 catalog sync 完成并修复生产镜像断链**：首次盘后 apply 由旧 Pod 镜像 `20261012-172238-c53705f` 执行，因 `883401.TI` 缺 `changePct` 失败（runId `4c1e51239ffb4cdb881299e74d5da379`）；该失败仅保留 `ths_operations` 审计行，normalized 目标表零写入。随后从已审 commit `8f0a6bc` 构建包含 `955ee33` partial `changePct` 修复的镜像 `localhost/a-stock-market-environment:20261013-162900-8f0a6bc`（containerd digest `sha256:d6339966…98600`），本地 health smoke 通过，远端 SHA-256 校验通过并 import；hook-free atomic Helm upgrade 将 release 99 → 100，仅变更 image tag，Pod 1/1 Ready、0 重启，PostgreSQL/PVC/Secret/migration 未变，CronJob/Job absent。新 Pod 重试同一命令成功：runId `8226a1b725d74d1a81829372736be4b3`、45/45 items、56/60 requests、0 failed/0 conflict；生产 PG 写入 `ths_catalog_revisions=1`、`ths_catalog_relations=846`（industry 320 / cn_concept 390 / region 33 / tszs 103）、`ths_industry_rankings=846`、`ths_sector_daily_bars=846`、`ths_sector_identities=846`、`ths_sector_memberships=2376`（`886042.TI=203`）。Pod 内 health 200，`/api/market-environment/ths/catalog` 返回 revision `fuyao-ths-catalog-v1`、total 846。10.6–10.8 仍需逐步单独授权；调度继续 disabled/suspended，隔离 PG cleanup 仍需明确授权。
  - **Fuyao THS 三数据集 10.9 pg_dump + 隔离恢复演练完成**：用户在本地 dev box 通过 `ssh admin@192.168.1.20 → sudo k3s kubectl exec -n a-stock a-stock-postgresql-0` 跑 `pg_dump -Fc -Z 9` 生成 `/tmp/a-stock-pgdump-20261013.dump`（2,400,447 字节、sha256 `1723b24c…3ee5`），`kubectl cp` + `scp` 拉回本地；本地起隔离 PG 容器 `a-stock-pg-recovery-1791854545`（`docker.m.daocloud.io/library/postgres:16.4`）并 `pg_restore --single-transaction --clean --if-exists --exit-on-error` 完成 0 error、39 表恢复。Schema 校验：`schema_migrations` v4–v8 全 apply（v7/v8 共用 `2026-10-12 09:34:56.764315+00`，印证 9.2 真演练一次 apply 两个 migration）；`provider_capability_reports` 仍仅 `fuyao/sectors/fuyao-market-v2` 1 行；11 张新 THS 表 schema 均存在、行数均 0。隔离 PG 容器按用户 (a) 选保留运行，等 10.3 capability apply 后做行差对照。未触动 production pod、PVC UID `6c426fc5-…`、Helm release rev 98、已写入 capability 唯一行、Helm env 全 off 与 absent CronJob。
  - **Fuyao THS 三数据集 10.3 capability apply 完成**：2026-10-13 09:54（Asia/Shanghai）由本地 dev box 通过 `ssh admin@192.168.1.20 → sudo k3s kubectl cp /tmp/fuyao-ths-report-20261012.json a-stock/a-stock-57b65c5bc6-ggt62:/tmp/...` 把脱敏 envelope 放进生产 Pod `/tmp`（emptyDir，不进 PVC；md5 `4b108bb1…f83c` 两端一致），再 `sudo k3s kubectl exec -n a-stock a-stock-57b65c5bc6-ggt62 -- bash -lc "cd /app && PYTHONPATH=/app/src python3 -m market_environment.cli capabilities promote"` 跑三条 CLI（`/app/src/market_environment` 在镜像 PYTHONPATH 之外，需 `cd /app` + `PYTHONPATH=/app/src`）。Dry-run 三份全部 `result=validated, conflictState=absent, targetBackend=postgresql+psycopg://***@a-stock-postgresql:5432/a-stock`，exit 0；加 `--apply` 全部 `result=applied, mode=apply`，exit 0。生产 PG 行差对照 = 4 行（`fuyao|industry-ranking|fuyao-ths-catalog-v1|eligible|845|1|2026-10-12 15:44:17`、`fuyao|sector-membership|fuyao-ths-membership-v1|eligible|203|1|2026-10-12 15:44:17`、`fuyao|sectors|fuyao-market-v2|eligible|10|1|2026-10-09 12:00:00`、`fuyao|sector-turnover-history|fuyao-ths-history-v1|eligible|484|1|2026-10-12 15:44:17`）；对比 10.9 隔离 PG baseline 多 3 行，旧 `fuyao/sectors/fuyao-market-v2` 行未变（option (a) 承诺兑现）。Pod env 镜像对比前后：`MARKET_ENVIRONMENT_THS_WRITES_AUTHORIZED=0`、六个 `_THS_*_ENABLED=0`、三个 `_THS_*_REVISION=""` 与 `_FUYAO_SECTORS_ENABLED=1/APPROVED_REVISION=fuyao-market-v2` 全不变；`/tmp` 空 dir 不进 PVC；Pod `restartCount=0`、Deployment 1/1 Ready、PVC UID `6c426fc5-…` 不变、Helm release rev 98 未动、CronJob 仍 absent；未触动任何 Secret、API key 与外发端口。聚焦 THS/capability/fuyao 161 passed（focused set 14 个测试文件，45.63s）；`openspec validate --strict` 通过；`check-docs-contract --mode=full` 通过；`git diff --check` 通过。日志落 `/tmp/a-stock-dryrun-*` + `/tmp/a-stock-apply-*` + `/tmp/a-stock-pgdiff-caps-20261013.txt` + `/tmp/a-stock-podenv-{pre,post}state-20261013.txt`。下一受控动作仍按 plan 10.x "每步独立授权"顺序等待：10.4 Helm release 升级注入 `_WRITES_AUTHORIZED=1` + 6 个 `_ENABLED=1` + `_REVISION`（CronJob 仍 `suspend=true`），10.5–10.8 顺序小批 catalog sync / history backfill / member import / 全量 dry-run 采集；清理隔离 PG 容器仍需用户复述。
  - **Fuyao THS 三数据集 10.4 Helm release 升级完成**：2026-10-13 10:28（Asia/Shanghai）由本地 dev box 通过 `ssh admin@192.168.1.20` 把 `deploy/truenas/values-ths-capabilities-on.yaml`（仅 `marketEnvironment.fuyao.ths` block 新增：`writesAuthorized: true`、六个 `_enabled: true`、三个 `_REVISION` 与 10.3 capability revision 对齐）与 `deploy/helm/a-stock` chart tarball 复制至 remote `/tmp/`，跑 `sudo /usr/local/bin/helm upgrade a-stock /tmp/a-stock -n a-stock --kubeconfig /etc/rancher/k3s/k3s.yaml --values /tmp/values-ths-capabilities-on.yaml --no-hooks --atomic --wait --timeout 5m`：先 `--dry-run` 校验无钩子 `Happy Helming`，再 `--atomic --wait` 真实 upgrade，Helm release 98 → 99、`helm history` 末行 `Tue Oct 13 10:28:21 2026 deployed Upgrade complete`。Audit packet：本地 `helm template` 渲染 `/tmp/a-stock-manifest-desired-10.4-20261013.yaml` 与 live `helm get manifest` 仅 10 处 env 值差异（`THS_WRITES_AUTHORIZED 0→1`、六个 `_THS_*_ENABLED 0→1`、三个 `_THS_*_REVISION ""→revision`），其它 line-for-line 一致；`values-ths-capabilities-on.yaml` 完整镜像 live release values 并保持图像 tag `20261012-172238-c53705f`、Secret 引用 `a-stock-market-provider`、PVC `a-stock-data + a-stock-postgresql-data`、`sectors.enabled: true/approvedRevision: fuyao-market-v2`、`scheduledCollection.enabled: false/suspend: true` 不变。后置验证：`kubectl exec a-stock-776d4bf97c-zt9ss -- env | grep MARKET_ENVIRONMENT` 落 `/tmp/a-stock-10.4-podenv-poststate-20261013.txt`，`THS_WRITES_AUTHORIZED=1` + 六个 `_ENABLED=1` + 三个 `_REVISION` 与 10.3 完全对齐、`FUYAO_SECTORS_ENABLED=1/APPROVED_REVISION=fuyao-market-v2` 保留；`helm get manifest` pre→post diff 仅 10 处 env 变化（落 `/tmp/a-stock-manifest-post-20261013.yaml`），其它资源 line-for-line 一致；`helm get values` 仅新增 `marketEnvironment.fuyao.ths` 块（落 `/tmp/a-stock-10.4-helm-values-post-20261013.txt`）；Dashboard `1/1 Ready`、dashboard pod 0 重启、PostgreSQL 0 重启、PVC UID `a-stock-data=c03bc7f8-…` 与 `a-stock-postgresql-data=6c426fc5-…` 未变；`schema_migrations` v4-v8 `applied_at` 仍是 `2026-10-12 09:34:56`（`--no-hooks` 未触发 schema-migration Job）；`provider_capability_reports` 行差仍是 4 行（10.3 三新增 + 旧 `fuyao/sectors/fuyao-market-v2` 保持），10.4 不直接调 CLI；`/api/health` HTTP 200、`/api/market-environment/ths/catalog` 仍返回 `{"revision":null,"items":[],"page":1,"pageSize":100,"total":0}`（首次 sync 未执行）；`MARKET_ENVIRONMENT_FUYAO_API_KEY` 仅来自 Secret、不进入 values/manifest；CronJob 仍 absent、`scheduledCollection.enabled=false/suspend=true` 保留。离线：聚焦 THS/capability 套件 88 passed、`vitest 139 passed`、`openspec validate --strict` 通过、`check-docs-contract --mode=full` 通过（代码 11 / 文档 5 / plan 1）、`git diff --check` 全过。日志落 `/tmp/a-stock-10.4-helm-values-{pre,post}-20261013.txt` + `/tmp/a-stock-manifest-{pre,desired,post}-*.yaml` + `/tmp/a-stock-pvc-pre-20261013.yaml` + `/tmp/a-stock-pods-pre-20261013.yaml` + `/tmp/a-stock-chart.tgz` MD5；values 文件 `deploy/truenas/values-ths-capabilities-on.yaml` 已落地仓库。下一受控动作仍按 plan 10.x "每步独立授权"顺序等待：10.5 单次小批 catalog sync、10.6 单次小批 history backfill、10.7 单次小批 member import（dump 缺 SHA-256 时仅跑 probe）、10.8 全量 dry-run 采集校验；清理隔离 PG 容器仍需用户复述。

  - **Fuyao THS 三数据集 10.2 盘后真实 probe 完成**：用户明确授权后于 2026-10-12 23:44（Asia/Shanghai）在隔离临时路径重跑 `cli fuyao ths-real-probe`，脱敏 proof 落 `/tmp/fuyao-ths-report-20261012.json`（保留 `.b1/.b2` 备份）。六份 capability report 中三份翻为 `eligible`：`fuyao-ths-catalog-v1`（industry-ranking 845/845 行，`changePctCoverage=1.0`、`changePctMissingTags=[]`、`requiredFieldsComplete=true`）、`fuyao-ths-membership-v1`（203 名成员，checksum `8e56512b…a6f6`）、`fuyao-ths-history-v1`（484 根 K 线，checksum `c98d89e5…7931`）；三 dump 仍 `ineligible`（SHA-256 缺失）。离线验证：后端 THS/fuyao/capability 套件 87 passed、Vitest 139 passed、`openspec validate --strict` 通过、`check-docs-contract --mode=full` 通过、`git diff --check` 通过。未触动 production PostgreSQL / Helm / Secret / PVC / 调度 / CronJob，未执行 capability apply 或 promotion。下一动作必须按 plan 10.x 分步授权：建议先 10.9（pg_dump + 隔离恢复演练），再做 10.3 capability apply、10.4 Helm 升级、10.5–10.8 顺序执行。

2026-10-12
  - **Fuyao THS 三数据集 9.2 部署落地**：2026-10-12
  - **Fuyao THS 三数据集 9.2 部署落地**：用户明确授权后于 17:18–17:35（Asia/Shanghai）通过受控 `scripts/deploy-truenas-k3s.sh --component all` 在 `192.168.1.20` k3s `v1.26.6+k3s-6a894050-dirty` 集群完成真演练 + 生产 additive migration + 部署 + 观察。Helm revisions 96/97/98（database → service → 完整 release），新镜像 `localhost/a-stock-market-environment:20261012-172238-c53705f`（containerd manifest digest `sha256:bcebdb7127f882e6b2117acca0d133352b83b55b1a9f3dc5894e3ce92a901e8d`、Pod imageID `sha256:55a4facc965dd0ab9eb5f96ab89094669f757fce40faf186302dc862540aab2e`）。`schema-migration` Hook Job 成功 apply alembic 0004+0005；11 张新 THS 表与索引全数落地，`schema_migrations` v4–v8 全应用。Deployment 注入 10 个新 THS fail-closed env var，`MARKET_ENVIRONMENT_THS_WRITES_AUTHORIZED=0` 且 `MARKET_ENVIRONMENT_FUYAO_THS_*_ENABLED=0/_REVISION=""`；`sectors` 仍 `enabled=1, approvedRevision=fuyao-market-v2`（上一 change 保留）。两个 PVC UID 不变（`a-stock-data=c03bc7f8-…/2Gi`、`a-stock-postgresql-data=6c426fc5-…/5Gi`），PostgreSQL 0 重启，`http://192.168.1.20:32001/api/health` 与首页均 HTTP 200。`scheduledCollection` 仍 `enabled=false / suspend=true`，CronJob 仍 absent，`provider_capability_reports` 中上一 change 的 capability 行未变。`/api/market-environment/ths/catalog` 返回空 catalog；未触发任何 provider、未执行小批 catalog/历史回填/成员导入、未恢复调度。
  - **Fuyao THS 真实 probe 与生产 NO-GO（9.1 阶段）**：新增六能力 `ths-real-probe`、promotion policy、official Parquet reader、membership 写路径和点选宽度链路。15:21 隔离 probe 仅 membership/history eligible；catalog 与三 dump ineligible，未晋升。生产 migration/写入/部署未执行，原因是 clean commit、备份恢复、镜像与 render hash 门禁未满足；官方动态接口入口为 `https://fuyao.aicubes.cn/llms-full.txt`（最后核对 2026-10-12）。
  - **task 11.1 授权后的安全预检**：用户已明确授权真实 capability probe；执行时上海时间为 `10:57`，未通过 15:30 盘后门禁，且当前 CLI 未注入真实 provider-neutral adapter。已生成 taxonomy、membership、adjusted-price、benchmark 四份隔离 dry-run 报告，均为零网络、零正式写入；未执行真实 provider 请求，未获得 revision/checksum/覆盖或数据条款证据，11.1 仍未勾选，所有真实来源开关保持关闭。tasks 11.2–11.4 未授权。

2026-10-11
  - **第 05 页申万一级主线持续性离线实现完成**：OpenSpec `add-sector-continuity-metrics` 已完成 tasks 1.1–10.5；申万一级时点事实、五项指标、唯一验证项、显式 backfill、PostgreSQL 持久化、API/前端和 snapshot v2 bridge 已通过 focused、三类 golden 双重 replay、隔离 PostgreSQL migration/UoW 与全库 `1335 passed`。真实 provider、非测试数据库、Kubernetes/Helm/PVC/Secret 和调度均未操作，tasks 11.1–11.4 等待额外授权。

2026-10-10
  - **第 05 页申万一级主线持续性规划**：OpenSpec `add-sector-continuity-metrics` 进入 Stage 1，仅固化产品、架构、仓库归属和运维事实；现有 provider observation 与待实现 canonical analysis 分离，真实数据源、生产写入与调度状态均未改变。

2026-10-09
  - **扶摇行业 fallback 生产预发布与 repair 扩展（当日早期 checkpoint）**：第三个 repair-control commit 完成唯一一次 hook-free Helm write，revision 92 deployed 并恢复 complete-off stored release；schema-migration hook 只被存储且未执行，namespace Jobs absent。该 checkpoint 时 OpenSpec/事实文档为 `18/24`，任务 5.2–5.6 尚未执行；这是同日后续启用前的历史状态，不代表当前生产开关。
  - **扶摇行业 sectors enable + 一次 collection（当日后续 production 结果）**：commit `4eb55dd` 修复 `select_runtime_sectors_pod` 后，部署到 Helm revision 95（sectors enabled=1、approved revision `fuyao-market-v2`、frozen image `sha256:853a8a…d03`、其他 Fuyao/Scrapling/limits/limits.fuyao/limits.v1 仍按 off 设定、enrichment/Scrapling 关闭）；随后 5.5 一次 `snapshots scheduled-refresh --dataset sectors` 成功（runId `e7c06da411124f5097f26c44b08f3820`、source=fuyao、status=fallback、10 obs、5 unsupported fields、双 Eastmoney push2/push2delay failure）。`provider_capability_reports` 唯一行 checksum `b763a32e…b2a`；CronJob/Job absent、Secret/PVC identity 未变。
  - **TrueNAS k3s 生产发布**：统一市场数据采集适配器随 `main=36aba3b` 发布；受控调度关闭为 revisions 83/84，database/service/完整 release 为 revisions 85/86/87。镜像 `localhost/a-stock-market-environment:20261008-235342-36aba3b` 的 containerd digest 为 `sha256:7d7a2762e274aad710257ad66224ddf782831b156a3bd56eafbf0f93cb219978`；Dashboard/PostgreSQL/PVC/健康与 provider-free GET 后置条件通过，CronJob/Job absent，未触发 provider。

2026-10-08
  - TrueNAS k3s 发布只读预检发现 revision 82 的 `a-stock-data-collection` 仍 active；操作责任人明确授权停止自动采集后，受控 rollback-v1 packet 经 revision 83 fail-safe suspended、revision 84 retained-resource cleanup 两步完成 exact CronJob 删除并证明 absent。未创建 provider-backed Job，未修改 PVC/Secret/生产数据。
  - 完成 `unify-market-data-acquisition-adapters`：五数据集统一 acquisition/collector/committer/projector 路径、engine-neutral transport、Fuyao gateway 迁移、legacy runtime 收口和默认关闭 Scrapling profile 已通过 focused/全量/规则/OpenSpec 离线门禁；生产 allowlist 为空，未运行真实网络或生产写入。

2026-09-30
  - **TrueNAS k3s 生产发布**：`main=40c3498` 通过受控 `--disable-schedule` + `--component all` 发布到 `192.168.1.20`；Helm revisions 77/78/79/80，镜像和 containerd digest、Deployment/PVC/NodePort/CronJob 后置条件见 `deploy-project-and-startup` plan。
  - 调度保持 disabled，未创建 Job 或触发 provider 采集；工作区 `main` 与 `origin/main` 同步且干净。
  - **定时采集激活**：按 `activate-scheduled-collection-20260930` 计划通过受控 `--release-suspended`（revision 81）和 `--activate-schedule`（revision 82）激活 `a-stock-data-collection`；`30 16 * * 1-5`、controller `Asia/Shanghai`、`suspend=false`，未启用扶摇数据集开关。
  - 16:30 首个自然 Job `a-stock-data-collection-29845950` 已执行并保留真实 `partial` 结果：core/breadth success，limits/activeDirection partial，sectors failed-missing；`runId=8a3a60fb61d347d8b3930c9ae7318273`，exact-date API 与五类质量记录均已读回。Job exit code 2 是质量状态的真实非零结果，不作为调度发布失败；后续继续观察 provider 恢复。

2026-09-29
  - **Fuyao 行业 fallback 隔离观察时点**：已证明 `industry` 目录/快照 320/320 覆盖和精确日期，但当时 `FUYAO_SECTORS_ENABLED=0`、`FUYAO_SECTORS_SHADOW_ENABLED=0`，只保留脱敏隔离证据，未写正式 sectors 快照。该时点状态已被 2026-10-09 revision 95 的受控启用与一次 collection 取代；历史证据仍保留，不回写或重标。
