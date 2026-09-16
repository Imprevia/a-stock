## ADDED Requirements

### Requirement: useDocumentContext 暴露章节公共派生与 helper

系统 SHALL 引入 `apps/market-environment-dashboard/src/composables/useDocumentContext.ts`，通过 setup 函数返回 reactive 引用，覆盖：- `breadthHistoryRows` / `breadthRuleRows` / `breadthRuleSummary` / `breadthIndexConsistencyRows` / `breadthConsistencySummary` / `breadthVerification` / `breadthWarnings` / `breadthCopyStatus` 等 breadth 派生
- `limitWarnings` / `limitSectionPhase` / `promotionGap` / `limitHistory` / `limitHistoryMeta` / `limitTiers` / `limitStratifications` 等 limits 派生
- `qualityLabel` / `qualityTone` / `metricQualityLabel` / `metricQualityTone` / `qualityCodeLabel` / `cacheStateLabel` / `sectionPhaseLabel` / `confidenceLabel` / `assessmentStatusLabel` / `dimensionStatusLabel` / `reasonLabel` / `environmentLabel` / `gapLabel` / `formatRatioDelta` / `formatReturnDelta` 等 label 字典与格式化函数

composable SHALL 在 setup 顶层调 `useMarketStore()`，store 为惰性实例。

#### Scenario: 章节组件引用 useDocumentContext
- **WHEN** `Document02BreadthPage.vue` setup 顶层 `const ctx = useDocumentContext()`，模板里写 `{{ ctx.breadthHistoryRows.length }}`
- **THEN** composable 返回 `breadthHistoryRows` computed，模板响应式渲染；`market.breadth.history.points` 变化时自动更新

#### Scenario: composable 跟随 market store
- **WHEN** 测试在 `setActivePinia(createPinia())` 后手动 `market.data = makeResponse()`，然后 mount 章节组件
- **THEN** composable 返回的 computed 自动从新 store 派生；组件渲染正确 fixture 数据

#### Scenario: composable 不修改 market
- **WHEN** 章节组件试图 `useDocumentContext().breadthWarnings = []`（写入操作）
- **THEN** TypeScript 编译期报错（readonly 派生 computed）或运行时无效；composable 暴露的全部是 reactive computed / 纯函数，不含可写字段

### Requirement: 章节公共上下文权限边界

`useDocumentContext()` SHALL 仅暴露**派生 computed** 与**纯函数**，不暴露任何修改 `market` store 的 action（如 `loadCore` / `loadSection` / `setDate` / `setSelectedCode`）。章节组件若需要触发刷新、日期变更等写操作，SHALL 通过 `defineExpose` 暴露的回调由 `DashboardLayout` 或 `App.vue` 路由壳处理。

#### Scenario: 章节组件不暴露 market.setDate
- **WHEN** `Document02BreadthPage.vue` 的 setup 试图 `const { setDate } = useDocumentContext()`
- **THEN** TypeScript 编译报错；composable 接口不包含任何 `setXxx` / `loadXxx` 写操作

#### Scenario: 章节组件通过 defineExpose 触发刷新
- **WHEN** `Document03LimitsPage.vue` 模板的「重新加载」按钮 `@click="$emit('refresh')"`，`App.vue` 在 `<DocumentXXPage @refresh="market.loadSection(activeSection, true)" />` 接住 emit
- **THEN** 章节组件不直接调 `market.loadSection`；通过 emit 把写操作委托给路由壳

### Requirement: useChartLifecycle composable 形态

`composables/useChartLifecycle.ts` SHALL 暴露 `useChartLifecycle(elementRef, optionFactory, watchSources?): { resize(): void, dispose(): void }`。

- `onMounted` 调 `echarts.init(elementRef.value)` + `setOption(optionFactory())`
- `watch(watchSources ?? optionFactory, () => setOption(optionFactory()))` 重画
- `window.addEventListener('resize', resize)`
- `onBeforeUnmount` 调 `dispose()`

#### Scenario: composable 接管 ECharts 生命周期
- **WHEN** `IndexPriceChartPanel.vue` setup 调 `useChartLifecycle(chartElement, () => buildOption(props.history, props.dates))`
- **THEN** 组件挂载时 ECharts 实例创建并首次 `setOption`；`props.history` 变化时自动 `setOption(newOption)`；组件卸载时 `dispose()` 释放实例

#### Scenario: composable 不持有全局闭包变量
- **WHEN** `App.vue` 不再持有 `let chart: echarts.ECharts | null` / `let volumeChart` / `let breadthChart` 闭包变量
- **THEN** ECharts 实例只在 chart panel 组件生命周期内存在；不再有「全局 chart 闭包需要跨组件协调」的问题

#### Scenario: composable resize 监听
- **WHEN** 浏览器 window 触发 resize 事件
- **THEN** useChartLifecycle 注册的 listener 调 `chart.resize()`；不触发 `dispose` + `init` 重启