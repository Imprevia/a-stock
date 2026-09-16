## Context

`apps/market-environment-dashboard/src/App.vue` 当前约 1000 行，单文件同时承载：路由壳（vue-router）、侧栏与顶栏的 UI、9 章节内联模板、章节公共上下文（document header、evidence strip、breadcrumb）、3 个 ECharts 实例的全局生命周期、9 章节的派生 computed 与格式化函数。`frontend-router-and-stores` 已经把路由、状态层（market store / preferences store / navigation store）规范化，但章节内容仍然内联。

前一次尝试在同一个 change 内一次性把 `App.vue` 的 ref + computed + action 全部迁移到 market store，触发了 22-26 个回归失败，因为模板里数百处 `data.X` / `loading` / `selectedDate` 等引用与 `data.` → `market.data.` 的批量替换产生冲突，且手滑错误无法逐个发现。本 change 的 design 必须把"逐步拆分 + 子任务独立可验证"作为第一原则。

## Goals / Non-Goals

**Goals:**

- 把 9 个章节拆为独立 Vue 单文件组件，每个组件可独立 `mount` 与单测。
- 引入 `DashboardLayout.vue` 作为 dashboard 路由的共享壳（document header + evidence strip + breadcrumb + `<RouterView/>`）。
- 引入 3 个共享 chart 组件与 `useChartLifecycle()` composable，把 ECharts 生命周期管理从 `App.vue` 抽出。
- 引入 `useDocumentContext()` composable 暴露章节公共状态（label 字典、UI 状态），与 `market` store 形成分层（composable 读 market，不写 market）。
- 路由升级为嵌套路由（`/dashboard/:documentId`），children 为各章节页面；`meta.section` 驱动 `beforeEach` 预拉。
- 现有 9 章节的页面行为契约（`market-breadth-page`、`index-combination-analysis` 等）保持不变。

**Non-Goals:**

- 不修改后端 API。
- 不修改 `market` / `preferences` / `navigation` store 的 state 形状（store 在前一个 change 已定义）。
- 不引入 SSR、不引入持久化插件。
- 不做章节内容的语义修改（页面行为按现有契约保持）。
- 不在路由层引入 `<keep-alive>` 章节缓存。
- 不实现 Phase 4 的 history mode 部署侧 SPA fallback 文档（由前一个 change 处理）。

## Decisions

### 决策 1：按章节逐个拆分，每章节一个 Phase

每次只拆一个章节（从 `Document01IndexPricePage.vue` 开始），每个章节落地后立即：
1. 在 `pages/dashboard/` 下新建章节组件
2. 把 `App.vue` 模板里该章节的 `v-else-if="selectedDocumentId === '0X'"` 块替换为 `<DocumentXXPage :as-of="..." />` 占位调用（保留 App.vue 的路由壳）
3. 写 `DocumentXXPage.test.ts`（独立 mount + pinia + market fixture 预填），验证跑过
4. 才进入下一个章节

这样每个章节的改动范围 ~50-150 行，可独立 review 与回滚。前一次失败的根因是「一次性大爆炸 + 批量 replace」——这次逐章节拆分让任何一次失败最多影响一个章节。

**替代方案**（已拒绝）：一次性把 9 章节全部拆出再切换 App.vue 渲染——前一次失败证明这种方案的风险不可控。

### 决策 2：DashboardLayout 持有 `useMarketStore()`，章节组件读 market store 派生（不持有 ref）

`DashboardLayout.vue` 在 setup 顶层调 `useMarketStore()`，把 `market.data` / `market.loading` / `market.error` / `market.selectedDate` / `market.selectedCode` / `market.nextSessionComparison` 通过 `<RouterView/>` 的 props 或 provide/inject 暴露给子章节组件。章节组件**不直接调** `useMarketStore()` 的 action，只读 getter；如果需要刷新（如「重新加载」按钮），通过 `defineExpose` 或 emit 把请求发回 `DashboardLayout`。

**为什么不让章节组件直接 useMarketStore**：前一次教训指出，App.vue 的 computed + watch + setter + onMounted + 模板同时切换源时，回归点会散布在 1000 行里。让章节组件只读不写、把写操作收敛到 DashboardLayout，可以让每个章节的 fixture 与 store 的耦合点最小化（只需要预填 market data）。

**替代方案**（已拒绝）：让章节组件自由 useMarketStore——灵活性高，但耦合点散布，不利于单测与回滚。

### 决策 3：useChartLifecycle composable 封装 ECharts 三件套

`composables/useChartLifecycle.ts` 暴露：

```ts
useChartLifecycle(elementRef, optionFactory, watchSources?): {
  resize(): void,
  dispose(): void,
}
```

- `onMounted` → `echarts.init(elementRef.value)` + `setOption(optionFactory())`
- `watch(watchSources, () => setOption(optionFactory()))` —— 只在 watchSources 变化时重画
- `window.addEventListener('resize', resize)`
- `onBeforeUnmount` → `dispose()`

3 个共享 chart 组件（`IndexPriceChartPanel` / `VolumeChartPanel` / `BreadthHistoryChartPanel`）只是 `useChartLifecycle` 的薄壳，不持有 `let chart = null` 闭包变量。

**为什么**：前一次尝试在 `App.vue` 留下 `chart` / `volumeChart` / `breadthChart` 三个闭包变量 + `renderChart` / `disposeCharts` / `resizeCharts` 全局函数——这是组件化的反面案例。composable 让 ECharts 生命周期跟着组件走，不需要全局协调。

### 决策 4：路由嵌套 + meta.section + beforeEach 预拉

`router/routes.ts` 升级为：

```ts
{
  path: '/dashboard/:documentId(0[1-9])',
  component: () => import('./pages/dashboard/DashboardLayout.vue'),
  meta: { section: null },
  props: route => ({ documentId: route.params.documentId }),
  children: [
    { path: '', component: () => import('./pages/dashboard/DocumentXXPage.vue') },
  ],
}
```

DashboardLayout 在 `beforeRouteEnter` 或 `onMounted` 调 `market.loadCore()`，然后为每个文档的 `meta.section` 在 `router.beforeEach` 调 `market.loadSection(section)`（不 await，路由切换不阻塞）。

**为什么不在 children 各自声明 meta**：9 个章节共享一个 DashboardLayout，section 信息由 DashboardLayout 在 beforeEach 统一处理；children 各自只关心渲染。这样路由配置扁平、可读。

### 决策 5：useDocumentContext composable 暴露章节公共 helper

`composables/useDocumentContext.ts` 暴露：
- `breadthHistoryRows` / `breadthRuleRows` / `breadthRuleSummary` 等 `breadth` 派生 computed
- `limitHistory` / `limitStratifications` / `promotionGap` 等 `limits` 派生 computed
- `breadthWarnings` / `limitWarnings` 等 warnings 派生
- `qualityLabel` / `qualityTone` / `environmentLabel` / `reasonLabel` / `gapLabel` 等 label 字典与格式化函数

为什么：这些 computed 与 label 字典在 `App.vue` 内被 9 个章节共享（通过 props drilling 或 provide/inject）；抽到 composable 让章节组件直接 `const { breadthWarnings } = useDocumentContext()`。

**composable 形态**：用 setup 函数返回 reactive 引用，让每个章节组件拿到的是 `market.breadth` 的派生 computed，不重新计算。

### 决策 6：测试从 `mount(App)` 改为 `mount(DocumentXXPage)`

`breadth-page.test.ts` / `limits-page.test.ts` / `data-collection-view.test.ts` 改造为：

```ts
import Document02BreadthPage from './pages/dashboard/Document02BreadthPage.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  const market = useMarketStore()
  market.data = makeResponse() // 预填 fixture
})

it('renders recap', async () => {
  const wrapper = mount(Document02BreadthPage, {
    global: { plugins: [router] },
  })
  // 断言 wrapper 渲染内容
})
```

这样章节 fixture 与章节组件一一对应，单测只覆盖该章节的渲染逻辑，不再依赖 `App.vue` 的全局壳。

## Risks / Trade-offs

- **章节公共 helper 仍被多个章节共享**（`App.vue` 里 `breadthRuleRows` 同时被 02 章节渲染）—抽到 `useDocumentContext` 后，每个章节的 `mount` 都需 `setActivePinia`，否则 composable 内的 reactive 引用不会响应。→ composable 在 setup 顶层调 `useMarketStore()`，store 是惰性的；mount 时必须先 `setActivePinia(createPinia())`。
- **嵌套路由 + lazy import 引入首次加载延迟**——`DashboardLayout.vue` 与 9 个 `DocumentXXPage.vue` 都用 `defineAsyncComponent`，用户首次进入 dashboard 会多出 1-2 个 chunk 请求。→ 前一个 change 已经把「路由切换阻塞章节组件渲染」设为不阻塞，加载延迟在 dev 环境下不感知。
- **章节内容契约的测试覆盖从 `app.test.ts` 转移到各章节 `DocumentXXPage.test.ts`**——迁移期间可能漏测。→ 迁移前 `app.test.ts` 里的章节断言保留为冒烟测试，章节测试落地后逐步删除 `app.test.ts` 里的对应断言。
- **`App.vue` 仍有路由壳（侧栏 + 顶栏 + `<RouterView/>`）**——不会拆到 0 行，至少 100-200 行。→ 这是非目标，App.vue 是合理的壳组件。
- **手动滑错误**（前一次大爆炸证明 batch replace 会误伤 `data.` / `loadData()` / CSS 类名）——本次设计禁止使用 `replaceAll` 风格的批量替换，每次只改一处一处改处，跑一次测试。

## Migration Plan

- Phase A（基础设施）：
  1. 引入 `useChartLifecycle` composable
  2. 引入 `useDocumentContext` composable
  3. 把 `Sidebar` 与 `Topbar` 拆为独立组件
  4. 把 `formatDateTime` 等纯函数迁入 `composables/useFormatDateTime.ts`
- Phase B（按章节顺序）：
  1. Document01IndexPricePage（含 ECharts）——最复杂
  2. Document02BreadthPage（含广度图）
  3. Document03LimitsPage（最长）
  4. Document04TierRiskPage
  5. Document05SectorsPage
  6. Document06ActiveDirectionPage
  7. Document07EventsPage
  8. Document08EnvironmentClassifyPage
  9. Document09AssessmentPage
- Phase C（App.vue 收尾）：
  1. 把 `App.vue` 模板里 `v-else-if="selectedDocumentId === '0X'"` 全部移除
  2. 引入 `DashboardLayout` 接管 dashboard 视图
  3. 路由升级为嵌套路由 + `meta.section`
- Phase D（验证 + 收尾）：
  1. `npm run test` 49/49 → 70+/70+
  2. `npm run build` 通过
  3. `python scripts/check-docs-contract.py --mode=full`
  4. 更新 `docs/architecture.md` + `docs/repository-guide.md`
- 每个章节拆完后立即 commit（feature 分支 `frontend-component-split`）。

**回滚**：每个 Phase 独立独立可逆；任一 Phase 失败可仅 revert 该 Phase 的文件改动。

## Open Questions

- `Document04TierRiskPage` 与 `Document07EventsPage` 当前 `App.vue` 内联内容极简（只有 1-2 个 section）——是否要为它们单独建文件？还是先合并到 `Document09AssessmentPage` 的「质量边界」区域？倾向：每个章节独立文件，便于未来扩展。
- `Sidebar` 与 `Topbar` 在 `App.vue` 现有 700+ 行模板中占 ~80 行——是否与本 change 一起拆？还是放入 Phase 4 的清理批次？倾向：本 change 一起拆（它们与 DashboardLayout 紧耦合）。
- `App.vue` 的 `onMounted` 里仍调 `initializeTimezonePreferences()` 与 `market.loadCore()`——拆出 Sidebar/Topbar 后，`App.vue` 还要保留这两个 onMounted 吗？还是移到 main.ts 或 DashboardLayout？倾向：保留在 App.vue（App.vue 是路由壳，初始化入口合理）。