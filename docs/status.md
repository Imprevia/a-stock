# 仓库状态

## 已实现

- harness 骨架：`docs/` 事实源体系、exec-plans 落地位、本地门禁（`.githooks/` + `scripts/check-docs-contract.py` + `scripts/install-hooks.py`）。
  - 事实源：`docs/repository-guide.md`、`docs/architecture.md`、`docs/runbooks.md`
- `搭建交易系统/` 已完成目录归档：11 个章节各自使用唯一章节目录，章节总览和正文不再散落于下载批次子目录。
- `docs/trading-system-directory.md` 已记录交易系统知识库的完整目录和文件清单，并由 `AGENTS.md` 提供入口说明。
- `搭建交易系统-量化版/` 已按原目录的 70 个相对路径完成量化重写：统一 YAML 元数据、327 个稳定规则 ID、固定/分位混合阈值、五档评分、风险否决、缺失处理和校准状态。
- `docs/trading-system-quantified-directory.md` 已记录量化版完整目录和维护规则；所有经验阈值当前均为 `needs-backtest`，没有规则被宣称为 `validated`。
- 市场环境分析看板：`src/market_environment/` + `apps/market-environment-dashboard/`。
  - 已接入 5 个指数、MA5/10/20/60、20/60 日区间位置、成交额比值、趋势/量价状态。
  - 已实现 mootdx → 百度 → 腾讯历史降级、腾讯实时交叉校验、指数进程内短缓存、非交易日回退和错误质量标记。
  - 已新增一级导航 `如何判断市场环境` 与 01 至 09 二级文档视图，覆盖指数、市场广度、涨跌停生态、行业主线、容量方向、事件边界和综合判断。
  - 已通过可选 `chapter01` 契约接入精确市场广度、日期化涨停/跌停/炸板池、行业排名和成交额 Top-N 股票；历史日期不复用今日快照。
  - 已覆盖计算、provider、服务层和 API 契约测试，并通过前端生产构建与桌面/移动浏览器检查。
  - 已修复上证指数和中证500成交额缺失：新浪指数 K 线按腾讯实时成交额校准，量价状态不再误报“数据不足”。
  - 已实现第 01 页第四部分“指数、趋势位置和成交额结合判断”：每个指数输出六类明确组合或显式未分类证据，第 01 章汇总市场强弱、阶段、资金认可和交易模式；页面支持随指数切换同步更新，不使用兜底分类。
  - 已修复看板日期错位和东方财富主域连接拦截导致的市场广度缺失：浏览器与 API 使用正确日期边界，全 A 完整快照兼容 `diff` 数组和键值对象；主域失败或分页受限时按排序分页降级计算，上涨家数、下跌家数和涨跌幅中位数只使用有效样本。
  - 已拆分数据加载：保留完整聚合接口，网页首屏改用指数核心接口，第 02、03、05、06、08、09 页按需加载章节证据；章节失败不会清空核心数据，同日期 provider 结果按数据集缓存并复用。
  - 已实现市场数据 SQLite 持久快照与盘后预计算：`breadth` 直接走精确分页统计，`activeDirection` 使用成交额 Top-N；支持 exact-date、checksum、settled freshness、跨进程 lease、stale-while-revalidate、刷新 CLI、回滚开关和可选缓存质量元数据。
  - 已新增 `/data-collection` 数据管理页和五类独立采集任务：`core`、`breadth`、`limits`、`sectors`、`activeDirection` 支持单项或一键采集，单项失败不停止或回滚成功兄弟任务；核心指数进一步隔离五个指数子结果。
  - 已实现 collection run/task、失败保留、精确日期状态、lease 去重、重启恢复和 materialized aggregate；普通市场环境 GET 只读本地聚合/快照，手工 POST 默认由 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 关闭。
  - 数据采集页首次状态请求不再复用研究页的 15:00 截止日期，而是由后端上海市场日初始化；用户改选历史日期后继续发送显式日期。
  - 东方财富请求已在进程内全局串行，并对连接/读取失败、429 和 5xx 有界重试，403 立即失败；行业排名支持 `push2` 到 `push2delay` 降级，领涨股名称按真实 `f128` 字段解析且不跨日期保留。
  - 容量方向已支持 `push2` 到 `push2delay` 的统一 Top-N 校验和可审计降级；当前市场日真实 smoke 在主域断连后保存 `eastmoney-clist-delay` / `fallback` 的 30 个观察样本，双端点失败继续使用精确日期的 `failed-retained` / `failed-missing`。
  - 数据采集管理已通过 124 个 Python 测试、11 个前端测试和生产构建；当前市场日行业真实 smoke 在主域断连后由 `eastmoney-clist-delay` 成功返回 100 条记录。
  - 已提供单镜像 k3s 部署配置：`deploy/k3s/` 提供原生 Kustomize 清单，`deploy/helm/a-stock/` 提供可覆盖镜像、Ingress/TLS、PVC、资源与调度参数的 Helm Chart；两者均保持单副本非 root 运行、健康探针和 SQLite 持久化。
  - 已新增部署内盘后自动采集：k3s/Helm CronJob 默认在 `Asia/Shanghai` 工作日 16:30 调用 `snapshots scheduled-refresh`，覆盖五类数据并与 Dashboard 共享镜像、PVC、SQLite task/lease 和失败隔离；支持关闭、暂停和调度覆盖。
  - scheduled-refresh 在周末无 provider 调用并返回 skipped，结算前拒绝；`partial` 保留成功兄弟任务且不自动整批重跑。部署与 CLI 测试已纳入全量 `117 passed, 3 skipped`，真实 Helm/kubectl render 补充验证为 `5 passed`。
- 交易规则工程化产品范围已定义：`docs/product-specs/trading-rule-engineering.md`。
- OpenSpec change `engineer-trading-rules-ci` 已建立 proposal、4 份 capability spec、design 和 19 项实施任务。
- 已修正干净环境依赖冲突：`httpx` 采用 mootdx 0.11.7 支持的 `>=0.25,<0.26` 区间，保证 CI 可解析安装。
- 交易规则工程平台已实现：327 条覆盖清单、第 01 章 46 条 YAML 规则、确定性执行、证据、回测骨架、CLI 和两条 GitHub Actions workflow。
- 固定快照生成 46 条 trace 并通过 golden 回放；全量测试 34 passed，OpenSpec strict 与 docs-contract full 均通过。

## 进行中

- `document-truenas-podman-k3s-deployment` 仍为 active exec plan；`schedule-after-market-data-collection` 实现已完成，OpenSpec change 待归档。

## 未实现

- 高位股、中位股和低位股的分层亏钱效应尚未形成独立可追溯数据集。
- 公告、政策、外围和突发事件仍需结构化来源、发布时间、有效期与失效条件；当前保持 `unverified`。
- 第 02 至 11 章 281 条规则仍为 `documented-only`。
- 尚未积累 500–750 日历史快照，没有规则可晋级为 `validated`。

## 当前风险

- 真实行情源受网络可用性影响；页面会显示降级来源、过期报价和部分失败 warning。
- `push2` 与 `push2delay` 同属东方财富，供应商整体不可用时行业和容量方向采集仍会失败；同日期成功快照会保留，不会用其他日期替代。
- 手工采集接口当前无完整用户认证，外部部署必须保持 `MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED` 关闭；生产写入口需后续接入权限边界。
- 第一版定时任务不维护交易所节假日日历；周一至周五节假日会留下 failed/partial 审计记录，但精确日期校验禁止跨日期落盘。
- SQLite refresh lease 只支持同一主机的本地文件系统，多主机部署需要共享缓存适配器。
- 通达信不可用时五个指数仍串行进入降级链，本机冷缓存核心请求约 34 秒；章节拆分已避免额外证据继续阻塞首屏，但指数 provider 仍需独立优化。
- 真实历史数据能否达到目标 750 日取决于 provider 覆盖；不足 500 日时不得形成验证证据。
- `.codex/`、`.opencode/` — agent 工具会话目录（是否入库待确认）
- 本机无 Python 时本地 gate 退化为警告放行（记录于 `docs/runbooks.md`）。

## 下一步

- 评估指数 provider 的连接失败熔断、可复用探测或线程安全并发方案，缩短冷缓存核心响应。
- 在目标 k3s 集群先以 suspend 部署 CronJob，创建一次性 Job 验证 SQLite PVC、provider 外网和 JSON 日志后再恢复工作日调度。
- 后续评估交易所节假日日历、认证和多节点协调；当前版本保持单机 SQLite、ReadWriteOnce PVC 与有界进程内 executor。
- 另行定义东方财富多层级行业板块筛选口径，并评估独立供应商备胎。
- 为分层亏钱效应建立稳定样本口径，并补齐文档 04 的真实 provider。
- 积累 500–750 个交易日快照，回测市场环境阈值与分类稳定性。
- 后续按覆盖清单逐章实现第 02 至 11 章 evaluator。

## 最后更新

2026-09-03
