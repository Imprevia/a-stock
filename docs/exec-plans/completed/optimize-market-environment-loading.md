# 优化市场环境看板数据加载

## Stage

实现与验证

## Status

已完成

## Acceptance

- 评估并记录聚合接口的性能问题与兼容边界，旧 `/api/market-environment` 契约继续可用。
- 首屏仅请求五大指数和无需外部章节数据即可生成的基础判断，不等待全 A、涨跌停池、行业和成交额榜。
- 第 02、03、05、06、08、09 页按实际依赖加载章节证据；第 04、07 页不触发无意义的外部数据请求。
- 同一日期已加载的章节数据在 30 秒服务缓存期内复用，单个章节失败不清空已成功的指数或其他章节数据。
- 后端契约与按需调用测试、前端生产构建、浏览器桌面/移动检查和 docs-contract full 通过。

## Completion Evidence

- `.venv\Scripts\python.exe -m pytest tests -q --basetemp .tmp-pytest-loading-final`：62 passed，只有既有 Starlette/httpx 弃用 warning。
- `npm run build --prefix apps/market-environment-dashboard`：构建成功；保留既有单 chunk 超过 500 kB warning。
- Playwright 浏览器 QA：1440px 首屏仅请求 `/api/market-environment/core`，存在 2 个非空 ECharts canvas；切到第 02 页后才请求 `section=breadth` 且章节 loader 可见；第 04 页无新增请求；第 08 页请求一次 `section=summary` 后，第 09 页复用结果。390px 视口 `scrollWidth=390`，移动导航可打开，且第 04 页仍只请求核心接口。
- 真实冷缓存核心接口返回 5 个指数，耗时约 34.37 秒；历史证据显示市场广度降级单独约 12 秒、完整章节首次请求约十几秒。拆分后这些章节请求不再阻塞首屏核心响应。
- `SKIP_PLAN_GATE=1 python scripts/check-docs-contract.py --mode=full`：通过；仅因新 plan 在未暂存工作树中无法被 Gate 3 的 git diff 检测而使用 plan gate 逃生口，active plan 和代码文档映射均已实际更新。
- `git diff --check`：通过。

## Remaining Gaps

- 本机通达信不可用时，五个指数仍依次进入 provider 降级，冷缓存核心请求约 34 秒；本次只隔离章节聚合等待，没有改变既定数据源优先级和串行安全边界。
- 共享东方财富 limiter 与 HTTP Session 的跨日期并发安全需要独立计划处理，本次没有扩大到 `src/trading_system/`。

## Next Step

- 独立评估指数 provider 的连接失败熔断、可复用探测或线程安全并发方案，把冷缓存核心响应继续降到可接受范围。
