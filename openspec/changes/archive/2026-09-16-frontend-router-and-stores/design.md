## Context

市场环境看板（`apps/market-environment-dashboard/`）当前所有视图逻辑集中于 `App.vue`（约 1700+ 行），其 script 内以 `currentView: 'dashboard' | 'data-collection' | 'settings'` 字符串 + `selectedDocumentId: '01'..'09'` 字符串 + `window.history.pushState` + `popstate` 监听 + `#document-N` hash 解析实现了手写的两层路由。模板侧则用 `v-if="currentView === 'dashboard'"` 与 `v-if/v-else-if` 嵌套 9 个文档的内联内容。

后端已提供三个粒度化端点（`/api/market-environment/core`、`/api/market-environment/chapter-01?section=`、`/api/market-environment/next-session`），前端实际只使用 `/core` + `/chapter-01?section=` + `/next-session` 三个。本次重构在保留后端契约的前提下，把前端手写路由替换为 `vue-router`、跨页状态集中到 `pinia`、组件按页面拆开。

## Goals / Non-Goals

**Goals：**

- 用 `vue-router` v4（history mode）替换 `App.vue` 中的 `currentView` / `pushState` / `popstate` / hash 解析。
- 用 `pinia` 集中跨页共享状态，按 `market / navigation / preferences / collection` 划分归属。
- 把 9 个文档渲染拆为独立页面组件，让现有能力契约（`index-combination-analysis`、`market-breadth-page` 等）保持页面行为不变。
- `/dashboard/:documentId` 用嵌套路由：`DashboardLayout` 持有共享 store + 上下文，子 `RouterView` 渲染章节。
- 路由 `beforeEach` 守卫按目标章节预拉对应 `section`；不阻塞路由切换（fire-and-forget 拉取，store 内已合并则跳过）。
- 旧 `#document-N` 在路由初始化阶段一次性重定向到 `/dashboard/N`，旧书签可点。
- `timezone.ts` 的 module-scope reactive 行为收敛到 `preferences` store；保留 `formatDateTime(value, options)` 纯函数签名（显式 timezone 参数）。
- 现有 Vitest 测试加 `setActivePinia(createPinia())`；新增四个 store 的单测。

**Non-Goals：**

- 不修改后端端点、契约、Schema、provider 行为；`/api/market-environment` 全量端点不在本次变更范围内。
- 不在路由层引入 `<keep-alive>` 章节缓存（沿用「路由切换即重建」的语义）。
- 不引入 SSR、不引入持久化插件（`pinia-plugin-persistedstate`）；`preferences` store 内的 localStorage 读写仍由 store action 直接负责。
- 不重写 ECharts 图表逻辑，只把生命周期管理抽到 `composables/useChartLifecycle.ts`。
- 不改 dashboard 后端数据 schema、不改 `apps/market-environment-dashboard/src/types.ts` 中的 `MarketEnvironmentResponse` / `Chapter01SectionResponse` 等现有接口。
- 不动采集后端执行路径（`CollectionCoordinator`、`provider` 触发逻辑）；`collection` store 只接管 `data-collection-view.vue` 的 UI 层状态。

## Decisions

### 路由模式与重定向策略

- 使用 `createWebHistory()`；与现有 `pushState` 行为一致，部署侧需配置 SPA fallback（开发由 Vite 自动处理；生产由 Ingress/NodePort 兜底；详见 `docs/runbooks.md` 增补）。
- 旧 `#document-N`（任意其他 hash）由 `router.beforeEach` 一次性 `router.replace('/dashboard/' + id)`。不保留 hash 形态作为次级定位。
- 顶层 `/` → `router.replace('/dashboard/01')`；`/dashboard` → `router.replace('/dashboard/01')`。

### 嵌套路由形态

- `/dashboard/:documentId` 用嵌套路由：父级 `DashboardLayout.vue` 持有 `useMarketStore()` 并渲染共享的 `DocumentHeader` / `EvidenceStrip` / `Breadcrumb`，子 `<RouterView/>` 渲染 9 个独立章节组件。
- 每个章节组件用 `defineAsyncComponent` + 动态 `import()` 实现按需加载；Vite 产出的 chunk 隔离到每个文档。
- 路由 meta 携带 `section: Chapter01Section | null`；`null` 表示该章节对应多个 section 或无需按 section 拉取（如 09 综合判断）。

### store 划分依据

- 按「状态归属 + 生命周期」划分：
  - `market`：fetch + cache 性质的核心数据。跨页共享（dashboard 内任意文档都依赖 selectedDate 与 data）。包含 selectedDate、selectedCode、data、loading/error、loadedSections、sectionStates、nextSessionComparison。action: `loadCore()`、`loadSection(section, force?)`、`loadNextSession(asOf)`、`setDate(date)`、`setSelectedCode(code)`。
  - `navigation`：UI 路由附属状态。`sidebarOpen` + `openSidebar()` / `closeSidebar()` / `toggleSidebar()`。
  - `preferences`：从 `timezone.ts` 迁入的时区偏好状态。`personalTimeZone` / `workspaceTimeZone` / `effectiveTimeZone` / `source` / `warning` / `loading` / `saving` / `canManageWorkspaceTimeZone` / `backendAvailable`。action: `load()`、`save(scope, value)`。`formatDateTime` / `parseTimestamp` 等纯函数留在 `composables/useFormatDateTime.ts` 接收显式 timezone 参数；不再直接读 module-scope reactive。
  - `collection`：从 `data-collection-view.vue` 迁入。`running` / `lastResult` / `lastError` / `requestSequence`。action: `collect(source)` / `loadStatus(asOf)` / `subscribeStatus()`。
- store 间调用：`market` 不调用 `preferences`（时间显示由调用方读 `usePreferencesStore().effectiveTimeZone` 后传入纯函数）；`navigation` 不调用任何其他 store。

### 路由守卫与预拉

- `router.beforeEach` 流程：
  1. 解析旧 hash（如有）→ `router.replace()` 后 return。
  2. 进入 `/dashboard` 系：检查 `market.data`，为空则 `await market.loadCore()`（首次进入必须等 core 就绪）。
  3. 进入 `/dashboard/:documentId`：读取 `to.meta.section`，若非空且未在 `market.loadedSections` 中，启动 `void market.loadSection(section)`（不 await，路由切换不阻塞；store 内合并完成后章节组件渲染时即可用）。
- 守卫不阻塞章节切换：进入 `/dashboard/03` 时 `/chapter-01?section=limits` 拉取期间，章节组件仍渲染空状态。

### ECharts 生命周期抽离

- `composables/useChartLifecycle.ts` 暴露 `useChartLifecycle(elementRef, optionFactory)`：
  - `onMounted` → `echarts.init()` + `setOption(optionFactory())`。
  - `watch(optionFactory)` → 重画（dispose + init 或仅 setOption，由实现侧选）。
  - `window.addEventListener('resize', resize)`。
  - `onBeforeUnmount` → `dispose()`。
- 现 `app.test.ts:374-426` 的 `chart lifecycle` 测试改为针对 `useChartLifecycle` 的本地测试；保留「section loading 替换 DOM 时图表重建」语义。

### 章节组件拆分颗粒度

- 9 个文档对应 9 个独立组件：`Document01IndexPricePage.vue` … `Document09AssessmentPage.vue`。
- 01 章节内 ECharts 重的部分再拆子组件：`IndexPriceChartPanel.vue`、`BreadthHistoryChartPanel.vue`。
- 03、04、05、06、07、08、09 章节早期可走 generic 配置（按 `documentId` 走 `if/else`），Phase 3 收尾时拆为独立组件。

### 受影响的现有能力（实现层变更）

- `index-combination-analysis`：01 章节组件从 `App.vue` 模板迁到 `Document01IndexPricePage.vue`，行为契约不变；五指数组合矩阵、同步评估、句式模板继续保留在原位（与 `review-sentence` 能力对齐）。
- `market-breadth-page`：02 章节组件从 `App.vue` 模板迁到 `Document02BreadthPage.vue`；复用现有 `breadth-page.test.ts` 的 fixture，验证方式从「挂载 App」改为「挂载 Document02BreadthPage + 提供 store」。
- `market-data-collection-management`：采集页路由从 `/dashboard/01` 旁的 `currentView === 'data-collection'` 分支迁到 `/data-collection` 顶层路由；契约要求（5 个数据集独立任务、状态视图、retry/full action 等）不变。
- `next-session-comparison` / `review-sentence`：行为契约不变；实现侧继续由 `Document01IndexPricePage.vue` 内的 `<NextSessionPanel/>` 与 `<ReviewSentencePanel/>` 渲染。

### 测试策略

- 端到端测试：`app.test.ts` 改为 `setActivePinia(createPinia())` + `createRouter({ history: createMemoryHistory(), routes })`；保持 `mount(App)` 行为，仅注入路由上下文。
- 现有 `breadth-page.test.ts` / `limits-page.test.ts` 等改为挂载独立页面组件 + 提供 `market` store fixture。
- 新增 `stores/market.test.ts`、`stores/preferences.test.ts`、`stores/collection.test.ts`、`stores/navigation.test.ts`；每文件用 `setActivePinia(createPinia())` + `vi.stubGlobal('fetch', mockFetch)` 跑独立断言。

### 迁移兼容期

- `timezone.ts` 在迁移后保留薄壳导出（`timezonePreferences`、`formatDateTime`、`initializeTimezonePreferences`、`saveTimezonePreference`），所有这些符号改为转发到 `usePreferencesStore()`。这样 `App.vue` 之外尚未迁移的调用点继续可用。
- 兼容期由 Phase 2 开始；Phase 4 收尾时删除薄壳，全部调用点改为 `usePreferencesStore()`。

## Risks / Trade-offs

- **路由懒加载引入异步竞态**：路由切换与 section 拉取同时发生，可能在章节组件渲染时 store 尚未合并。 → `useChartLifecycle` 用 `optionFactory` 闭包从 store 取值；首次渲染允许「图表为空、表格显示 loading」语义。
- **ECharts 重建成本**：每次路由切换都 dispose + init；如果某文档章节频繁切换，可能感知到重建耗时。 → Phase 1 实测一次章节切换重建耗时；超过 300 ms 触发 review。
- **store 单测 fixture 复用**：store 状态在不同测试间共享可能引入「上一测试残留」。 → 每个测试 `beforeEach` 内 `setActivePinia(createPinia())` 重建实例。
- **历史 hash 重定向漏掉罕见形态**（如 `#document-XX` 两位以上或 `#foo-bar`）。 → `router.beforeEach` 只匹配 `#document-(0[1-9])$`；其他形态不动。
- **preferences store 迁移期内 `timezone.ts` 薄壳与 store 同时存在**：可能存在两份 state。 → 薄壳内部直接转发到 store，不复制 ref；任何 store 之外的写入都通过薄壳再到 store。
- **现有 `app.test.ts` 端到端 fixture 依赖 `mount(App)`** + `vi.stubGlobal('fetch')` 的交互时序：注入路由上下文后可能改变时序。 → 保留 `flushPromises()` × 2 的现有节奏；如发现 fixture 需要调整，单独 review。
- **后端 `/api/market-environment` 全量端点未使用但保留**：不会被前端触发，但部署清单中可能仍包含。 → 不在本次变更范围；后续单独评估是否删除。
- **部署侧 history mode SPA fallback 未在本次变更中验证**：Ingress / NodePort 配置差异可能让刷新页面 404。 → 在 `docs/runbooks.md` 增补 history mode 部署注意点，运维侧按需调整；变更交付说明中标注「需部署侧确认 SPA fallback」。

## Migration Plan

- Phase 1（路由骨架）：新增 `vue-router` 与 `pinia` 依赖、`router/`、`stores/navigation.ts`；`App.vue` 改造为顶层壳；`/dashboard/01`、`/data-collection`、`/settings` 三条路由先跑起来；旧 hash 重定向上线。`app.test.ts` 改造为带路由上下文的端到端测试。
- Phase 2（核心数据共享）：新增 `stores/market.ts`；`DashboardLayout.vue` 与 `Document01IndexPricePage.vue` 拆出；`useChartLifecycle.ts` 抽离；`timezone.ts` 薄壳迁移到 `stores/preferences.ts`。
- Phase 3（剩余章节拆分）：`Document02..09` 拆为独立组件；`breadth-page.test.ts` / `limits-page.test.ts` 改造；`stores/collection.ts` 抽离，`DataCollectionPage.vue` 落地。
- Phase 4（懒加载 + 预拉 + 守卫收尾）：每个文档组件 `defineAsyncComponent`；`router.beforeEach` 预拉 section；`docs/architecture.md` / `docs/runbooks.md` / `docs/repository-guide.md` 同步更新；`timezone.ts` 薄壳删除。
- 回滚策略：每个 Phase 单独 ship；任一 Phase 失败可仅 revert 该 Phase 的文件改动，不影响前后 Phase 已 ship 内容。

## Open Questions

- `preferences` store 是否需要持久化插件？目前 `timezone.ts` 已在 store 内部手动管理 localStorage；引入 `pinia-plugin-persistedstate` 会带来新依赖且只省 5 行代码，不建议引入。
- `market` store 是否需要在用户切换日期时清空旧 `loadedSections`？目前 `App.vue` 在 `loadData()` 时清空（`loadedSections.value = []`）；store 内沿用此语义。
- 章节组件的 generic 配置形态是否在 Phase 3 一次性完成？建议保留 Phase 3 中通用章节组件 + 9 个文档 meta 配置 + 关键章节独立子组件（01、02、03）三层结构；Phase 4 收尾时再决定哪些章节拆独立组件。