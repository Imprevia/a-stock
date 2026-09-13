# 仓库状态

## 已实现

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
  - 已实现市场数据 SQLite 持久快照与盘后预计算：`breadth` 直接走精确分页统计，`activeDirection` 使用成交额 Top-N；支持 exact-date、checksum、settled freshness、跨进程 lease、stale-while-revalidate、刷新 CLI、回滚开关和可选缓存质量元数据。
  - 已新增 `/data-collection` 数据管理页和五类独立采集任务：`core`、`breadth`、`limits`、`sectors`、`activeDirection` 支持单项或一键采集，单项失败不停止或回滚成功兄弟任务；核心指数进一步隔离五个指数子结果。
  - 已实现 collection run/task、失败保留、精确日期状态、lease 去重、重启恢复和 materialized aggregate；普通市场环境 GET 只读本地聚合/快照，手工 POST 默认开启并可由 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0` 显式关闭。
  - 数据采集页首次状态请求不再复用研究页的 15:00 截止日期，而是由后端上海市场日初始化；用户改选历史日期后继续发送显式日期。
  - 东方财富请求已在进程内全局串行，并对连接/读取失败、429 和 5xx 有界重试，403 立即失败；行业排名支持 `push2` 到 `push2delay` 降级，领涨股名称按真实 `f128` 字段解析且不跨日期保留。
  - 容量方向已支持 `push2` 到 `push2delay` 的统一 Top-N 校验和可审计降级；当前市场日真实 smoke 在主域断连后保存 `eastmoney-clist-delay` / `fallback` 的 30 个观察样本，双端点失败继续使用精确日期的 `failed-retained` / `failed-missing`。
  - 数据采集管理已通过 124 个 Python 测试、11 个前端测试和生产构建；当前市场日行业真实 smoke 在主域断连后由 `eastmoney-clist-delay` 成功返回 100 条记录。
  - 已提供单镜像 k3s 部署配置：`deploy/k3s/` 提供原生 Kustomize 清单，`deploy/helm/a-stock/` 提供可覆盖镜像、Ingress/TLS、PVC、资源与调度参数的 Helm Chart；两者均保持单副本非 root 运行、健康探针和 SQLite 持久化。
  - TrueNAS k3s 组件化部署已落地：`scripts/deploy-truenas-k3s.sh --component all|database|service|schedule` 共享一个 Helm release，`all` 固定按 `database -> service -> schedule` 执行；database 保持现有 SQLite RWO PVC 与 `/data/snapshots.sqlite3`，service 复用不可变镜像，schedule 仅接受 frozen image 并保持 suspended/disabled。离线 manifest 与 TrueNAS scheduling guard 套件分别通过 178 与 103 个测试，未访问真实 TrueNAS、provider 或生产 PVC。
  - 已新增部署内盘后自动采集：k3s/Helm CronJob 的业务目标为 `Asia/Shanghai` 工作日 16:30，覆盖五类数据并与 Dashboard 共享镜像、PVC、SQLite task/lease 和失败隔离；native timezone 限 1.27+，1.26 的 controller 兼容实现与 TrueNAS overlays 已形成离线实现。GYT-52 对旧 exact `0b319c1501d6706f0be4eb680c46dd0d66f2c4dc` 的四项 NO-GO 已由 implementation parent `cd26dff3e6bebe012198dcd38074c354c1a9afac` 修复；`b13ed06fb729cc3a2c52908ba45136717bf18bed`、`7d74b8b`、`0717d840d8c2777bef666a208d28ebe4288c77c1` 与冻结 review/evidence tip `4f6d2b28b1694c78f53eb3ce007b8530b0667ead` 仅为 docs-only wrappers。GYT-52 已于 2026-09-10 对 clean exact `origin/main=main=HEAD=b1907e63ab81ca9c5e1d9d5531aadbf3118f2998` 给出 Gate A GO（评论 `01a08af1-2842-7c07-80a6-2af49b91e196`）；GYT-21 继续明确排除。该 GO 仅允许进入 Gate B 精确生产验证准备，不代表生产发布或 Gate C 激活。
  - scheduled-refresh 在周末无 provider 调用并返回 skipped，结算前拒绝；`partial` 保留成功兄弟任务且不自动整批重跑。旧结构化 CommonMark/Bash AST 审计和发布测试结果均为历史证据：它们未覆盖 canonical rollback binding、label/shape drift 下的 active-to-off 补偿，以及 stdin/source/alias 等二次解释路径。focused/deployment/guard 与 fake-provider 测试范围绑定 `cd26dff3e6bebe012198dcd38074c354c1a9afac`；全库、OpenSpec、docs-contract、clean/review 证据绑定冻结 docs-only review/evidence tip `4f6d2b28b1694c78f53eb3ce007b8530b0667ead`，旧 SHA 结果不作为当前验收。
- 交易规则工程化产品范围已定义：`docs/product-specs/trading-rule-engineering.md`。
- OpenSpec change `engineer-trading-rules-ci` 已建立 proposal、4 份 capability spec、design 和 19 项实施任务。
- 已修正干净环境依赖冲突：`httpx` 采用 mootdx 0.11.7 支持的 `>=0.25,<0.26` 区间，保证 CI 可解析安装。
- 交易规则工程平台已实现：330 条覆盖清单、第 01 章 49 条 YAML 规则、确定性执行、证据、回测骨架、CLI 和两条 GitHub Actions workflow。
- 固定快照生成 49 条 trace；新增三条规则不进入 `QTS-01-00-01`，既有规则 trace 保持不变。

## 进行中

- `document-truenas-podman-k3s-deployment` 仍为 active exec plan；`schedule-after-market-data-collection` 实现已完成，OpenSpec change 待归档。
  - `enable-truenas-scheduled-market-collection` 的 Stage 4 NO-GO 回流实现已完成：implementation parent `cd26dff3e6bebe012198dcd38074c354c1a9afac` 关闭 rollback authorization binding、active-to-off fail-safe、文档 shell 审计与 ordinary typed-value 前置拒绝；`b13ed06fb729cc3a2c52908ba45136717bf18bed`、`7d74b8b`、`0717d840d8c2777bef666a208d28ebe4288c77c1` 及冻结 tip `4f6d2b28b1694c78f53eb3ce007b8530b0667ead` 仅为 docs-only evidence wrappers。focused suite `323 passed`、全库离线 `464 passed, 2 warnings`，代码/测试归属 parent，clean/review 归属冻结 tip；GYT-52 已于 2026-09-10 对 `b1907e63ab81ca9c5e1d9d5531aadbf3118f2998` 给出 Gate A GO（评论 `01a08af1-2842-7c07-80a6-2af49b91e196`）。GYT-50 当前因生产访问/用户选择取消，Gate B/Gate C 仍需分别取得 exact action/operation authorization；当前不执行生产动作。
- 生产定时任务 fail-closed 契约：Helm release 仍未创建或管理 application CronJob，Gate B action authorization 与 Gate C operation authorization 尚待记录，正式链路保持 fail-closed；GYT-52 Gate A GO 已解除 Gate A 阻塞，但不构成 Gate B/C 操作授权。TrueNAS 集群另有一条不归 Helm ownership 的 operator override CronJob；它不能作为 Gate B/Gate C 已完成的证据。Chart、TrueNAS baseline 与三个 overlay 默认 `scheduledCollection.enabled=false / suspend=true`，`scripts/deploy-truenas-k3s.sh` 通用入口的安全约束不变。
- Operator override 临时绕过路径：2026-09-13 已确认 controller 继承主机 `Asia/Shanghai`，并使用独立的 `deploy/truenas/market-data-collection-cronjob-1.26-controller-shanghai.yaml` 将 live schedule 从错误的上海 08:30 修正为工作日上海 16:30。server-side dry-run 通过，live diff 只改 `spec.schedule`；冻结镜像、`suspend=false`、安全上下文和独立 PVC/PV 均未变化。周末 smoke Job 返回 `skipped/weekend`、exit 0，SQLite 大小和 mtime 未变化，临时 Job 已删除；下一步等待 2026-09-14 16:30 首次自然触发验证。
- 定时采集稳定性修复已完成：`SnapshotStore` 将 WAL 设置移至初始化阶段，materialized local read 复用同一只读事务中的聚合、limits、leases 与 revision；性能测试 fixture 不再执行无关的完整采集写事务。`scripts/apply-truenas-operator-override.sh` 以 exact 非 Helm-owned CronJob 为边界，默认只读 + server dry-run，显式 `--apply` 后 exact readback，并通过 `sudo env KUBECONFIG=...` 保留目标上下文。operator/deployment 联合测试 `193 passed`，market environment service/store `39 passed`，全量离线 pytest `592 passed, 2 warnings`；Gate B/Gate C 生产授权仍未改变。
- 市场环境看板 live server 已确认是 k3s `v1.26.6+k3s-6a894050-dirty`，主机时区 `Asia/Shanghai` 且 NTP 已同步；冻结镜像为 `localhost/a-stock-market-environment:20260906-005226-2075b6e` / `sha256:8fc74dcf37f5e6303e42f78811ef9de16759cb6e045aa57648e027cd1449754b`。Helm revision、Dashboard imageID 与网络边界不在本次 schedule-only override 范围，仍按后续受控 preflight 复核。
- `complete-limit-ecosystem-dashboard-parity` 的第 03 页完整涨跌停生态看板实现与受控验证已完成：契约、事实表迁移、严格 provider、相邻交易日晋级、梯队/制度/交易所分层、近 5 日与 60/250 日覆盖、前端状态和离线门禁均已落地；2026-09-11 隔离真实 smoke 因 provider 缺少顶层交易日字段而 `failed-missing`，`promotionQuality=insufficient`，未写生产 SQLite/PVC。limits detail/V1 开关默认关闭，旧五字段仍是兼容基线。

## 未实现

- 高位股、中位股和低位股的分层亏钱效应尚未形成独立可追溯数据集。
- 第 03 页 limits detail 的真实 provider 日期、证券制度、ST/上市窗口、板块和收盘状态覆盖仍未完成证明；已授权的隔离 smoke 证明当前 provider 缺少顶层交易日字段，在数据源修复并重新验证前，晋级率、梯队/分层和 250 日分位必须保持 `insufficient` / `degraded`，不视为 `validated`。
- 公告、政策、外围和突发事件仍需结构化来源、发布时间、有效期与失效条件；当前保持 `unverified`。
- 第 02 至 11 章 281 条规则仍为 `documented-only`。
- 尚未积累 500–750 日历史快照，没有规则可晋级为 `validated`。

## 当前风险

- 真实行情源受网络可用性影响；页面会显示降级来源、过期报价和部分失败 warning。
- `push2` 与 `push2delay` 同属东方财富，供应商整体不可用时行业和容量方向采集仍会失败；同日期成功快照会保留，不会用其他日期替代。
- 手工采集接口仍无应用级认证或 TLS。TrueNAS NodePort 候选上线后，所有能路由到 `192.168.1.20:32001` 的客户端均可匿名触发 provider 调用和 SQLite 写入；持久共享入口仍需后续接入认证授权，异常时先将 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED=0`，再按现场捕获的 pre-release 网络与 release 基线回退。
- 第一版定时任务不维护交易所节假日日历；周一至周五节假日会留下 failed/partial 审计记录，但精确日期校验禁止跨日期落盘。
- SQLite refresh lease 只支持同一主机的本地文件系统，多主机部署需要共享缓存适配器。
- 通达信不可用时五个指数仍串行进入降级链，本机冷缓存核心请求约 34 秒；章节拆分已避免额外证据继续阻塞首屏，但指数 provider 仍需独立优化。
- 真实历史数据能否达到目标 750 日取决于 provider 覆盖；不足 500 日时不得形成验证证据。
- `.codex/`、`.opencode/` — agent 工具会话目录（是否入库待确认）
- 本机无 Python 时本地 gate 退化为警告放行（记录于 `docs/runbooks.md`）。

## 下一步

- 评估指数 provider 的连接失败熔断、可复用探测或线程安全并发方案，缩短冷缓存核心响应。
- 定时采集下一检查点是 Gate B 精确 packet 的只读 preflight、审核与 action authorization；GYT-52 已对 `b1907e63ab81ca9c5e1d9d5531aadbf3118f2998` 给出 Gate A GO，但 Gate B 证据接受后仍须形成明确 `next-schedule` 或 `immediate catch-up` 的 Gate C operation authorization，且 live diff 仅允许已审阅的 `spec.suspend: true -> false`。
- operator override 下一检查点是 2026-09-14 16:30 上海的首次自然触发；需核对 Job/Pod 日志、五类数据状态与独立 SQLite mtime，失败或 partial 必须保留真实质量证据。
- 后续评估交易所节假日日历、认证和多节点协调；当前版本保持单机 SQLite、ReadWriteOnce PVC 与有界进程内 executor。
- 另行定义东方财富多层级行业板块筛选口径，并评估独立供应商备胎。
- 为分层亏钱效应建立稳定样本口径，并补齐文档 04 的真实 provider。
- 积累 500–750 个交易日快照，回测市场环境阈值与分类稳定性。
- 后续按覆盖清单逐章实现第 02 至 11 章 evaluator。

## 最后更新

2026-09-13
