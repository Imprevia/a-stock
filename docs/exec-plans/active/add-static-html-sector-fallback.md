# `add-static-html-sector-fallback` — 末层 HTML 静态源

## Stage（阶段）

为 `sectors` 数据集新增两个互不相关的 **末层** static HTML source adapter,默认 disabled,严格隔离字段权威,只补 `name` / `changePct` / `amount` / `leader 名`,其余 SUPPLEMENTAL_FIELDS 始终 null 加 warning。

## Status（状态）

`completed-without-production-write`

## Goal（目标）

为当前 Fuyao 末层之后的真空中补一条独立的兜底链路,既能让 Eastmoney/Tushare/Fuyao 全挂时仍拿到 4 个 web-visible 行业事实,又不破坏 SUPPLEMENTAL_FIELDS 的不可伪造纪律。`scrapling` 引擎范围与 `crawlFallback.enabled` 解耦,默认 `false`,扫描零 I/O 通过。

## Scope（范围）

- 增加 `infrastructure/providers/html_common/` 共享工具:drift、selector、fixture、text normalize、base adapter.
- 增加 `infrastructure/providers/sina_html/` 与 `xueqiu_html/` 两个独立 source adapter(`sectors-sina-html` / `sectors-xueqiu-html`,revision 分别为 `crawl-html-sina-v1` / `crawl-html-xueqiu-v1`).
- 在 `infrastructure/providers/sectors_acquisition.py` 的 `SectorsAcquisitionPlan.collect()` 末尾接入 `_attempt_html_tier`,Fuyao 失败或不可用时尝试 sina → xueqiu,任一成功 short-circuit,都失败落入既有 `failed-retained` / `failed-missing` 语义。
- `bootstrap/settings.py` 增加 `CrawlFallbackConfig`(env: `MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED`、`MARKET_ENVIRONMENT_CRAWL_FALLBACK_HOSTS`),默认 disabled.
- `bootstrap/container.py` 与 `bootstrap/registries.py` 通过 `crawl_fallback_is_enabled` 把开关注入到 plan 与 adapter 注册;`enabled=false` 时零注册,plan 步骤也不出现.
- `deploy/helm/a-stock/values.yaml` 与模板新增 `marketEnvironment.crawlFallback.{enabled,hosts}`,模板渲染 `MARKET_ENVIRONMENT_CRAWL_FALLBACK_*` env.
- `tests/fixtures/{sina,xueqiu}_html/` 增加离线合成 HTML + 期望 JSON + footprint.
- `tests/test_market_environment_static_html_sectors.py` 与 `tests/test_market_environment_sectors_html_probe.py` 覆盖 happy / drift / 401 / challenge / 上游短接 / 字段权威 / leader identifier 拒绝 / probe dry-run.
- `src/market_environment/cli.py` 增加 `sectors-html real-probe` 子命令,默认 dry-run,只有 `--allow-real` + `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1` 才会发出单次 bodyless GET,且输出红字 envelope 不含 token / cookie / body.
- 同步 `docs/architecture.md`(数据源表,infrastructure 段落)、`docs/runbooks.md`(末层 HTML 静态源小节,显式禁止 challenge solving)。
- OpenSpec change `openspec/changes/add-static-html-sector-fallback/` 内 4 个 artifact 全部齐备(proposal/design/spec delta/tasks)且 `openspec validate` 通过.

不在范围内:任何真实生产采集、capability-report promotion、Helm rollout、production schedule、scrape 真实页面、credit / quota / token 提交。

## Acceptance（验收）

- `MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED=0` 时 `SectorsAcquisitionPlan` 的 step 序列不出现 `sectors-sina-html` 或 `sectors-xueqiu-html`,registry 也不注册二者,plan 校验通过.
- `MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED=1` 且 `HOSTS=sina` 时,plan 末段增加 `sectors-sina-html` fallback,短接在 Eastmoney / Tushare / Fuyao 之后.
- `MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED=1` 且 `HOSTS=sina,xueqiu` 时,plan 末段同时包含 sina 与 xueqiu,顺序固定,sina 成功短路 xueqiu.
- 离线合成 fixture 命中时,`SinaHtmlSectorAdapter.extract_rows` 与 `XueqiuHtmlSectorAdapter.extract_rows` 各自产出对齐 `expected_rows.json` 的 `SectorRow`.
- `mainNet` / `mainNetPct` / `upCount` / `downCount` 始终为 `null`,每行/全表收集一个 `dom-source-unsupported:<field>` warning,质量元数据 `status="fallback"`.
- 当原始页面把 leader 显示为 6 位代码(如 `600519`),`leader` 仍然为 `null`,质量元数据追加一条 `leader-identifier-not-name` 警告,绝不写入.
- 401 / 403 / 登录墙 / 验证码 立刻被分类为 `non-retryable` `permission` / `challenge`,不走重试,无 engine 升级.
- DOM 选择器漂移(`data-symbol` 消失 / 表格结构变化)`DriftDetector` 触发 `dom-drift` warning,quality 降级为 `fallback` 或 `degraded`,绝不从无关 DOM 文本拼出任何行业行.
- Helm 模板渲染 baseline 与 overlay 都通过 `helm template`,token / cookie / secret 值都不会进入 manifest.
- `python -m src.market_environment.cli sectors-html real-probe --source sina-html --as-of 2026-10-09 --output /tmp/p.json` 默认 dry-run,`payload["status"] == "dry-run"`,`transports` 数组为空,无 `headers` / `body` / `credential` 字段.
- `python scripts/check-docs-contract.py --mode=fast` 在 docs 同步后通过.

## Completion Evidence（完成证据）

- 新增测试:`pytest tests/test_market_environment_static_html_sectors.py tests/test_market_environment_sectors_html_probe.py -q` 26 passed.
- 关联测试:`pytest tests/test_market_environment_sectors_acquisition.py tests/test_market_environment_sector_enrichment.py tests/test_market_environment_bootstrap.py -q` 全绿.
- OpenSpec:`openspec validate add-static-html-sector-fallback` 通过;`openspec status --change add-static-html-sector-fallback` 显示 4 artifact done.
- CLI 干跑(已在隔离 session 跑过):`python -m src.market_environment.cli sectors-html real-probe --source sina-html --as-of 2026-10-09 --output /tmp/probe.json` 输出合法 envelope,无 token / cookie / body.
- Helm values / templates 通过基础 `helm template a-stock deploy/helm/a-stock`(本地未远端验证过,但渲染未触发任何 helm 模板错误).

## Remaining Gaps（剩余缺口)

按 OpenSpec 约束,以下动作必须独立、人为授权,本变更不执行:

- **真实 probe**:`--allow-real` + 盘后窗口 + `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1` 下抓取 sina / xueqiu 真实卡片页,捕获 fixture 替换 `tests/fixtures/` 中的合成 HTML。需要操作发起人签署(`commit-pr-reviewer` 或人工 envar 授权)。
- **Capability-report promotion**:把红字 envelope 通过 `python -m src.market_environment.cli capabilities promote --input <report>` 写入 runtime PostgreSQL store。必须先有真实 probe,且必须通过 dry-run 校验。
- **Helm rollout**:把 `marketEnvironment.crawlFallback.enabled` 由 `false` 翻 `true`,并对应部署/Secret/CronJob 同步开启。必须先有 promoted capability report,否则 promote 会保持 `ineligible`。
- **生产 schedule**:`scheduledCollection.enabled` 仍按仓库规则保持 `false` 且 `suspend=true`;crawl tier 上线后**不**自动开 cron,完全跟随人工复核。
- **fixture 更新**:DOM 变更后,需要操作发起人重新合成 fixture 并重跑本次测试集。仓库 PR 门禁在 fixture 漂移时会触发 `dom-drift` warning,这是预期行为,但仍需要修复 fixtures 才能 CI 通过。

## Next Step（下一步）

1. 等人对接计划 / 是否进入真实 probe 期。
2. 等 Tushare 权限推进 (`add-tushare-sector-fallback`) 是否先于本变更得到授权,以及两者 fallback 顺序调整的最终决定。
3. 在本变更未被 archived 之前,持续保持 `docs/exec-plans/active/add-static-html-sector-fallback.md` 的 `Status` 与 `Remaining Gaps` 同步刷新,避免出现"代码已上线但 plan 仍自称未完成"或反之。
