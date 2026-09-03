<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  Activity, AlertTriangle, BarChart3, CalendarDays, ChevronRight, CircleAlert,
  Database, FileCheck2, Gauge, LineChart, Menu, RefreshCw, Rows3, Scale,
  ShieldAlert, Target, TrendingDown, TrendingUp, X,
} from 'lucide-vue-next'
import type {
  Chapter01Analysis,
  Chapter01Section,
  Chapter01SectionResponse,
  DataSetQuality,
  IndexAnalysis,
  MarketEnvironmentResponse,
} from './types'
import { formatLocalDate, getDefaultMarketDate } from './date-util'
import DataCollectionView from './data-collection-view.vue'

type AppView = 'dashboard' | 'data-collection'

const documents = [
  { id: '01', title: '指数、趋势位置和成交额', objective: '量化指数方向、均线结构、区间位置和量价推进。', rules: 'QTS-01-01-01 ~ 05', icon: LineChart },
  { id: '02', title: '上涨家数、下跌家数和中位数', objective: '用全 A 参与面验证指数涨跌是否代表多数股票。', rules: 'QTS-01-02-01 ~ 05', icon: Rows3 },
  { id: '03', title: '涨停、跌停、炸板和晋级', objective: '拆分短线热度、封板质量、接力成功率和极端风险。', rules: 'QTS-01-03-01 ~ 05', icon: Activity },
  { id: '04', title: '高、中、低位亏钱效应', objective: '识别亏钱效应是在扩散，还是从恐慌向修复收敛。', rules: 'QTS-01-04-01 ~ 04', icon: ShieldAlert },
  { id: '05', title: '主线持续性和成交集中度', objective: '区分持续主线、一日脉冲和高位抱团。', rules: 'QTS-01-05-01 ~ 05', icon: BarChart3 },
  { id: '06', title: '大成交额主动进攻方向', objective: '验证容量资金是否形成量增、价升、强收盘和板块跟随。', rules: 'QTS-01-06-01 ~ 05', icon: Target },
  { id: '07', title: '公告、政策、外围和事件', objective: '把来源可靠性、时效、预期差和盘面确认分开记录。', rules: 'QTS-01-07-01 ~ 05', icon: FileCheck2 },
  { id: '08', title: '如何归类市场环境', objective: '按风险优先级映射为趋势、轮动、退潮或混合环境。', rules: 'QTS-01-08-01 ~ 03', icon: Gauge },
  { id: '09', title: '如何综合判断市场环境', objective: '形成环境类别、证据链、置信度、风险和次日验证条件。', rules: 'QTS-01-09-01 ~ 04', icon: Scale },
]

const combinationDefinitions = [
  { key: 'bottom_repair', condition: '低位、重回短期均线、温和放量', state: '底部修复或启动尝试' },
  { key: 'uptrend', condition: '均线多头、位置抬升、量能稳定', state: '上升趋势或主升阶段' },
  { key: 'breakout', condition: '区间高位、放量突破、收盘较强', state: '趋势加速或突破确认' },
  { key: 'high_divergence', condition: '区间高位、巨量滞涨、冲高回落', state: '高位分歧或派发风险' },
  { key: 'rotation', condition: '均线缠绕、量能忽高忽低', state: '震荡轮动' },
  { key: 'trend_damage', condition: '跌破关键均线、放量下跌', state: '趋势破坏或退潮' },
]

const data = ref<MarketEnvironmentResponse | null>(null)
const selectedCode = ref('sh000001')
const selectedDocumentId = ref('01')
const selectedDate = ref(getDefaultMarketDate(new Date()))
const loading = ref(false)
const error = ref('')
const loadedSections = ref<Chapter01Section[]>([])
const sectionLoading = ref(false)
const sectionError = ref('')
const sidebarOpen = ref(false)
const currentView = ref<AppView>(window.location.pathname === '/data-collection' ? 'data-collection' : 'dashboard')
const chartElement = ref<HTMLElement | null>(null)
const volumeChartElement = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let volumeChart: echarts.ECharts | null = null
let requestSequence = 0
let sectionRequestSequence = 0
let dataRequestDate = ''

const documentSections: Partial<Record<string, Chapter01Section>> = {
  '02': 'breadth',
  '03': 'limits',
  '05': 'sectors',
  '06': 'activeDirection',
  '08': 'summary',
  '09': 'summary',
}

const selectedDocument = computed(() => documents.find((item) => item.id === selectedDocumentId.value) ?? documents[0])
const selectedIndex = computed<IndexAnalysis | null>(() => data.value?.indices.find((item) => item.code === selectedCode.value) ?? data.value?.indices[0] ?? null)
const selectedCombination = computed(() => selectedIndex.value?.combination ?? null)
const chapter = computed(() => data.value?.chapter01)
const breadth = computed(() => chapter.value?.breadth)
const limits = computed(() => chapter.value?.limits)
const assessment = computed(() => chapter.value?.assessment)
const combinationOverview = computed(() => chapter.value?.combinationOverview)
const activeSection = computed(() => documentSections[selectedDocumentId.value] ?? null)
const generatedAt = computed(() => data.value?.generatedAt ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(data.value.generatedAt)) : '')
const breadthBar = computed(() => {
  const item = breadth.value
  if (!item?.validCount || item.advanceCount == null || item.flatCount == null || item.declineCount == null) return null
  return {
    advance: (item.advanceCount / item.validCount) * 100,
    flat: (item.flatCount / item.validCount) * 100,
    decline: (item.declineCount / item.validCount) * 100,
  }
})
const sectionWarning = computed(() => {
  const section = activeSection.value
  if (!section || !loadedSections.value.includes(section)) return ''
  if (section === 'breadth' && breadthBar.value) return breadth.value?.quality.warning ?? ''
  if (section === 'sectors' && chapter.value?.sectors?.rows?.length) return chapter.value.sectors.quality.warning ?? ''
  if (section === 'activeDirection' && chapter.value?.activeDirection?.topStocks?.length) return chapter.value.activeDirection.quality.warning ?? ''
  return ''
})

const changeTone = (value: number) => value > 0 ? 'positive' : value < 0 ? 'negative' : 'flat'
const formatPct = (value: number | null | undefined) => value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
const formatRatio = (value: number | null | undefined) => value == null ? '--' : `${value.toFixed(2)}x`
const formatVolumePrice = (ratio: number | null | undefined, state: string | null | undefined) => [formatRatio(ratio), state].filter(Boolean).join(' ')
const formatCount = (value: number | null | undefined) => value == null ? '--' : value.toLocaleString('zh-CN')
const formatAmount = (value: number | null | undefined) => value == null ? '--' : Math.abs(value) >= 100000000 ? `${(value / 100000000).toFixed(1)} 亿` : `${(value / 10000).toFixed(0)} 万`
const formatPosition = (value: number | null | undefined) => value == null ? '--' : `${(value * 100).toFixed(0)}%`
const formatCoverage = (value: number | null | undefined) => value == null ? '--' : `${(value * 100).toFixed(0)}%`
const qualityLabel = (quality?: DataSetQuality) => quality ? ({ ok: '正常', fallback: '降级', partial: '部分覆盖', missing: '未接入', failed: '失败' } as Record<string, string>)[quality.status] ?? quality.status : '数据不足'
const qualityTone = (quality?: DataSetQuality) => quality?.status === 'ok' ? 'ok' : ['fallback', 'partial'].includes(quality?.status ?? '') ? 'fallback' : 'missing'
const confidenceLabel = (value?: string) => ({ high: '高', medium: '中', low: '低', insufficient: '数据不足' } as Record<string, string>)[value ?? ''] ?? value ?? '数据不足'
const environmentLabel = (value?: string) => ({ trend: '趋势', rotation: '轮动', retreat: '退潮', mixed: '混合', insufficient: '数据不足' } as Record<string, string>)[value ?? ''] ?? value ?? '数据不足'

interface ChartTooltipItem {
  axisValueLabel?: string
  data?: number[] | null
  marker?: string
  seriesName?: string
  value?: number | number[] | null
}

function formatPriceTooltip(params: unknown) {
  const items = Array.isArray(params) ? params as ChartTooltipItem[] : []
  const candle = items.find((item) => item.seriesName === 'K线')
  const rawValues = Array.isArray(candle?.data) ? candle.data : Array.isArray(candle?.value) ? candle.value : []
  const values = rawValues.length === 5 ? rawValues.slice(1) : rawValues
  const [open, close, low, high] = values.map((value) => Number(value))
  const lines = [`<strong>${items[0]?.axisValueLabel ?? ''}</strong>`]
  if (values.length === 4) {
    lines.push(`${candle?.marker ?? ''}开 ${open.toFixed(2)}　高 ${high.toFixed(2)}`)
    lines.push(`收 ${close.toFixed(2)}　低 ${low.toFixed(2)}`)
  }
  for (const item of items.filter((entry) => entry.seriesName?.startsWith('MA'))) {
    const value = typeof item.value === 'number' ? item.value : null
    if (value != null) lines.push(`${item.marker ?? ''}${item.seriesName}　${value.toFixed(2)}`)
  }
  return lines.join('<br/>')
}

async function loadData() {
  const requestId = ++requestSequence
  const requestedDate = selectedDate.value
  ++sectionRequestSequence
  loadedSections.value = []
  sectionLoading.value = false
  sectionError.value = ''
  loading.value = true
  error.value = ''
  let shouldLoadSection = false
  try {
    const response = await fetch(`/api/market-environment/core?as_of=${requestedDate}`)
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `请求失败（${response.status}）`)
    }
    const nextData = await response.json() as MarketEnvironmentResponse
    if (requestId !== requestSequence) return
    data.value = nextData
    dataRequestDate = requestedDate
    shouldLoadSection = true
    if (!data.value.indices.some((item) => item.code === selectedCode.value)) selectedCode.value = data.value.indices[0]?.code ?? ''
  } catch (cause) {
    if (requestId !== requestSequence) return
    error.value = cause instanceof Error ? cause.message : '行情加载失败，请稍后重试'
  } finally {
    if (requestId !== requestSequence) return
    loading.value = false
    await nextTick()
    renderChart()
  }
  if (shouldLoadSection) void loadCurrentSection()
}

function mergeChapterSection(current: Chapter01Analysis | undefined, incoming: Chapter01Analysis, section: Chapter01Section) {
  if (section === 'summary') return { ...incoming }
  const merged = current ? { ...current } : { ...incoming }
  merged.status = incoming.status
  merged.coverage = incoming.coverage
  if (incoming.documents) merged.documents = incoming.documents
  if (incoming.breadth?.quality.status !== 'missing') merged.breadth = incoming.breadth
  if (incoming.limits?.quality.status !== 'missing') merged.limits = incoming.limits
  if (incoming.sectors?.quality.status !== 'missing') merged.sectors = incoming.sectors
  if (incoming.activeDirection?.quality.status !== 'missing') merged.activeDirection = incoming.activeDirection
  merged.combinationOverview = incoming.combinationOverview
  merged.assessment = incoming.assessment
  return merged
}

function completedChapterSections(chapter: Chapter01Analysis, requested: Chapter01Section) {
  const completed: Chapter01Section[] = [requested]
  if (chapter.breadth?.quality.status !== 'missing') completed.push('breadth')
  if (chapter.limits?.quality.status !== 'missing') completed.push('limits')
  if (chapter.sectors?.quality.status !== 'missing') completed.push('sectors')
  if (chapter.activeDirection?.quality.status !== 'missing') completed.push('activeDirection')
  if (requested === 'summary') completed.push('summary')
  return completed
}

async function loadCurrentSection(force = false) {
  const section = activeSection.value
  const requestedDate = dataRequestDate
  const requestId = ++sectionRequestSequence
  sectionLoading.value = false
  sectionError.value = ''
  if (!section || loading.value || !data.value || !requestedDate || selectedDate.value !== requestedDate) return
  if (!force && loadedSections.value.includes(section)) return

  sectionLoading.value = true
  try {
    const response = await fetch(`/api/market-environment/chapter-01?as_of=${requestedDate}&section=${section}`)
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `请求失败（${response.status}）`)
    }
    const nextData = await response.json() as Chapter01SectionResponse
    if (requestId !== sectionRequestSequence || requestedDate !== dataRequestDate || !data.value) return
    if (nextData.asOf !== data.value.asOf) throw new Error('章节数据日期与核心数据不一致')
    data.value = {
      ...data.value,
      generatedAt: nextData.generatedAt,
      chapter01: mergeChapterSection(data.value.chapter01, nextData.chapter01, section),
    }
    const completedSections = completedChapterSections(nextData.chapter01, section)
    loadedSections.value = [...new Set([...loadedSections.value, ...completedSections])]
  } catch (cause) {
    if (requestId !== sectionRequestSequence || requestedDate !== dataRequestDate) return
    sectionError.value = cause instanceof Error ? cause.message : '章节证据加载失败，请稍后重试'
  } finally {
    if (requestId === sectionRequestSequence) sectionLoading.value = false
  }
}

function renderChart() {
  if (selectedDocumentId.value !== '01' || !chartElement.value || !volumeChartElement.value || !selectedIndex.value) return
  chart ??= echarts.init(chartElement.value)
  volumeChart ??= echarts.init(volumeChartElement.value)
  const history = selectedIndex.value.history
  const dates = history.map((item) => item.date.slice(5))
  chart.setOption({
    animation: false,
    grid: { top: 28, right: 18, bottom: 42, left: 62 }, tooltip: { trigger: 'axis', confine: true, textStyle: { fontSize: 14 }, formatter: formatPriceTooltip },
    legend: { top: 0, right: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: '#68727e', fontSize: 14 } },
    xAxis: { type: 'category', data: dates, boundaryGap: true, axisLabel: { color: '#8a939e', fontSize: 14 }, axisLine: { lineStyle: { color: '#dfe4e8' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#8a939e', fontSize: 14 }, splitLine: { lineStyle: { color: '#edf0f2' } } },
    series: [
      { name: 'K线', type: 'candlestick', data: history.map((item) => [item.open, item.close, item.low, item.high]), itemStyle: { color: '#c65050', color0: '#26815f', borderColor: '#c65050', borderColor0: '#26815f' } },
      { name: 'MA5', type: 'line', data: history.map((item) => item.ma5), showSymbol: false, connectNulls: false, lineStyle: { width: 1.2, color: '#c45b55' }, z: 3 },
      { name: 'MA10', type: 'line', data: history.map((item) => item.ma10), showSymbol: false, connectNulls: false, lineStyle: { width: 1.2, color: '#7263a7' }, z: 3 },
      { name: 'MA20', type: 'line', data: history.map((item) => item.ma20), showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: '#d18a35' }, z: 3 },
      { name: 'MA60', type: 'line', data: history.map((item) => item.ma60), showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: '#87929d' }, z: 3 },
    ],
  })
  volumeChart.setOption({
    animation: false, grid: { top: 8, right: 18, bottom: 8, left: 62 }, tooltip: { trigger: 'axis', confine: true, textStyle: { fontSize: 14 } },
    xAxis: { type: 'category', data: dates, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#edf0f2' } } },
    yAxis: { type: 'value', scale: true, splitNumber: 3, axisLabel: { color: '#a0a8b0', fontSize: 14, hideOverlap: true, formatter: (value: number) => `${(value / 100000000).toFixed(0)}亿` }, splitLine: { lineStyle: { color: '#f3f5f6' } } },
    series: [{ name: '成交额', type: 'bar', data: history.map((item) => item.amount || null), barMaxWidth: 12, itemStyle: { color: '#b9d2d4' } }],
  })
}

function selectDocument(id: string) {
  navigateTo('dashboard')
  selectedDocumentId.value = id
  sidebarOpen.value = false
  window.location.hash = `document-${id}`
}
function navigateTo(view: AppView) {
  currentView.value = view
  sidebarOpen.value = false
  const path = view === 'data-collection' ? '/data-collection' : '/'
  if (window.location.pathname !== path) window.history.pushState({}, '', path)
  if (view === 'dashboard' && !data.value && !loading.value) void loadData()
}
function handlePopState() {
  currentView.value = window.location.pathname === '/data-collection' ? 'data-collection' : 'dashboard'
  if (currentView.value === 'dashboard' && !data.value && !loading.value) void loadData()
}
function selectIndex(code: string) { selectedCode.value = code }
function resizeCharts() { chart?.resize(); volumeChart?.resize() }
function disposeCharts() {
  chart?.dispose()
  volumeChart?.dispose()
  chart = null
  volumeChart = null
}

watch(selectedIndex, async () => { await nextTick(); renderChart() })
watch(selectedDocumentId, async (documentId) => {
  if (documentId !== '01') disposeCharts()
  await nextTick()
  renderChart()
  void loadCurrentSection()
})
onMounted(() => {
  const match = window.location.hash.match(/document-(0[1-9])$/)
  if (match) selectedDocumentId.value = match[1]
  if (currentView.value === 'dashboard') loadData()
  window.addEventListener('resize', resizeCharts)
  window.addEventListener('popstate', handlePopState)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  window.removeEventListener('popstate', handlePopState)
  disposeCharts()
})
</script>

<template>
  <div class="app-shell">
    <button v-if="sidebarOpen" class="sidebar-backdrop" type="button" aria-label="关闭导航" @click="sidebarOpen = false" />
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="brand-block"><div class="brand-mark"><Activity :size="19" /></div><div><strong>交易研究系统</strong><span>A 股 · 盘后证据</span></div><button class="mobile-close" type="button" aria-label="关闭导航" @click="sidebarOpen = false"><X :size="18" /></button></div>
      <nav aria-label="交易研究导航">
        <div class="nav-label">市场研判</div>
        <button class="primary-nav" :class="{ active: currentView === 'dashboard' }" type="button" @click="navigateTo('dashboard')"><Gauge :size="17" /><span>如何判断市场环境</span><ChevronRight :size="15" /></button>
        <div class="secondary-nav"><button v-for="document in documents" :key="document.id" type="button" :class="{ active: currentView === 'dashboard' && selectedDocumentId === document.id }" @click="selectDocument(document.id)"><span class="nav-number">{{ document.id }}</span><span>{{ document.title }}</span></button></div>
        <div class="nav-label management-label">数据管理</div>
        <button class="primary-nav" :class="{ active: currentView === 'data-collection' }" type="button" @click="navigateTo('data-collection')"><Database :size="17" /><span>数据采集</span><ChevronRight :size="15" /></button>
      </nav>
      <div class="sidebar-foot"><Database :size="15" /><div><span>规则事实源</span><strong>market-environment v1</strong></div></div>
    </aside>

    <main class="main-shell">
      <header class="topbar"><div class="topbar-left"><button class="menu-button" type="button" aria-label="打开导航" @click="sidebarOpen = true"><Menu :size="19" /></button><div class="breadcrumb"><span>{{ currentView === 'dashboard' ? '如何判断市场环境' : '数据管理' }}</span><ChevronRight :size="14" /><strong>{{ currentView === 'dashboard' ? selectedDocument.id : '数据采集' }}</strong></div></div><div v-if="currentView === 'dashboard'" class="header-actions"><label class="date-field"><CalendarDays :size="16" /><span class="sr-only">选择交易日</span><input v-model="selectedDate" type="date" :max="formatLocalDate(new Date())" :disabled="loading" @change="loadData" /></label><button class="icon-button" type="button" :disabled="loading" aria-label="刷新行情" title="刷新行情" @click="loadData"><RefreshCw :size="17" :class="{ spin: loading }" /></button><button class="icon-button" type="button" aria-label="打开数据采集" title="打开数据采集" @click="navigateTo('data-collection')"><Database :size="17" /></button></div></header>
      <div class="content-shell">
        <DataCollectionView v-if="currentView === 'data-collection'" />
        <template v-else>
        <section class="document-header"><div class="document-number">{{ selectedDocument.id }}</div><div class="document-title"><span>01 · 如何判断市场环境</span><h1>{{ selectedDocument.title }}</h1><p>{{ selectedDocument.objective }}</p></div><div class="rule-reference"><span>规则范围</span><strong>{{ selectedDocument.rules }}</strong><em>经验阈值 · 待回测</em></div></section>
        <section v-if="error" class="state-panel error-panel" role="alert"><CircleAlert :size="22" /><div><strong>行情暂时不可用</strong><p>{{ error }}</p></div><button class="text-button" type="button" @click="loadData">重新加载</button></section>
        <section v-else-if="loading && !data" class="state-panel"><div class="loader" /><span>正在读取市场证据…</span></section>
        <template v-else-if="data">
          <section class="evidence-strip"><div><span>实际交易日</span><strong>{{ data.asOf }}</strong></div><div><span>章节覆盖率</span><strong>{{ formatCoverage(chapter?.coverage) }}</strong></div><div><span>数据状态</span><strong>{{ chapter?.status === 'ok' ? '完整' : ['degraded', 'partial'].includes(chapter?.status ?? '') ? '降级' : '数据不足' }}</strong></div><div class="evidence-meta"><span>更新 {{ generatedAt }}</span><i class="source-dot" /><span>{{ data.indices.length }} 个指数</span></div></section>

          <section v-if="activeSection && sectionLoading" class="state-panel"><div class="loader" /><span>正在读取本节证据…</span></section>
          <section v-else-if="activeSection && sectionError" class="state-panel error-panel" role="alert"><CircleAlert :size="22" /><div><strong>本节证据暂时不可用</strong><p>{{ sectionError }}</p></div><button class="text-button" type="button" @click="loadCurrentSection(true)">重新加载</button></section>

          <template v-else-if="selectedDocumentId === '01'">
            <section class="index-cards" aria-label="指数概览"><button v-for="index in data.indices" :key="index.code" class="index-card" :class="{ selected: selectedIndex?.code === index.code }" type="button" @click="selectIndex(index.code)"><div class="card-top"><span>{{ index.name }}</span><span class="code">{{ index.code }}</span></div><div class="card-price"><strong>{{ index.close.toFixed(2) }}</strong><span :class="changeTone(index.changePct)">{{ formatPct(index.changePct) }}</span></div><div class="card-bottom"><span>{{ index.trendState }}</span><span>{{ formatVolumePrice(index.amountRatio5, index.volumePriceState) }}</span></div></button></section>
            <section class="workspace-grid"><article class="panel chart-panel"><div class="panel-heading"><div><span class="panel-kicker">价格结构</span><h2>{{ selectedIndex?.name }} · 60 日走势</h2></div><span class="selected-hint"><TrendingUp v-if="selectedIndex && selectedIndex.changePct >= 0" :size="15" /><TrendingDown v-else :size="15" />{{ selectedIndex?.trendState }}</span></div><div ref="chartElement" class="price-chart" /><div class="volume-heading"><span>60 日成交额</span><span>金额单位：元</span></div><div ref="volumeChartElement" class="volume-chart" /><div class="chart-footnote"><span>日 K 线与 MA5 / MA10 / MA20 / MA60</span><span>来源：{{ selectedIndex?.dataQuality.source }}</span></div></article><article class="panel detail-panel"><div class="panel-heading"><div><span class="panel-kicker">当前结构</span><h2>趋势与量能</h2></div></div><div v-if="selectedIndex" class="metric-stack"><div class="metric-row"><span>MA5 / MA10</span><strong>{{ selectedIndex.movingAverages.ma5?.toFixed(2) ?? '--' }} <small>/</small> {{ selectedIndex.movingAverages.ma10?.toFixed(2) ?? '--' }}</strong></div><div class="metric-row"><span>MA20 / MA60</span><strong>{{ selectedIndex.movingAverages.ma20?.toFixed(2) ?? '--' }} <small>/</small> {{ selectedIndex.movingAverages.ma60?.toFixed(2) ?? '--' }}</strong></div><div class="metric-row"><span>20 日位置</span><strong>{{ formatPosition(selectedIndex.rangePosition20) }}<em>{{ selectedIndex.rangePosition20Label }}</em></strong></div><div class="metric-row"><span>60 日位置</span><strong>{{ formatPosition(selectedIndex.rangePosition60) }}<em>{{ selectedIndex.rangePosition60Label }}</em></strong></div><div class="metric-row"><span>成交额 / 5日</span><strong>{{ formatRatio(selectedIndex.amountRatio5) }}</strong></div><div class="metric-row"><span>成交额 / 20日</span><strong>{{ formatRatio(selectedIndex.amountRatio20) }}</strong></div></div></article></section>
            <section class="combination-grid">
              <article class="panel combination-panel">
                <div class="panel-heading"><div><span class="panel-kicker">第四部分 · 当前指数</span><h2>{{ selectedIndex?.name }} · 指数、位置与成交额组合</h2></div><span class="quality-badge" :class="selectedCombination?.matched ? 'ok' : 'missing'">{{ selectedCombination?.matched ? '明确命中' : '未分类' }}</span></div>
                <div v-if="selectedCombination" class="combination-state" :class="selectedCombination.tone"><span>当前组合</span><strong>{{ selectedCombination.state || '未命中明确组合' }}</strong><p>交易模式：{{ selectedCombination.tradingMode }}</p></div>
                <ul v-if="selectedCombination" class="combination-evidence"><li v-for="item in selectedCombination.evidence" :key="item">{{ item }}</li></ul>
              </article>
              <article class="panel combination-overview-panel">
                <div class="panel-heading"><div><span class="panel-kicker">第四部分 · 四项输出</span><h2>市场组合结论</h2></div><span class="quality-badge" :class="combinationOverview?.confidence === 'medium' ? 'fallback' : 'missing'">置信度 {{ confidenceLabel(combinationOverview?.confidence) }}</span></div>
                <div class="combination-output-list">
                  <div><span>市场是否真强</span><strong>{{ combinationOverview?.strength || '数据不足' }}</strong></div>
                  <div><span>市场所处阶段</span><strong>{{ combinationOverview?.stage || '数据不足' }}</strong></div>
                  <div><span>资金是否认可</span><strong>{{ combinationOverview?.capitalAcceptance || '数据不足' }}</strong></div>
                  <div><span>交易模式</span><strong>{{ combinationOverview?.tradingMode || '数据不足' }}</strong></div>
                </div>
              </article>
            </section>
            <section class="panel combination-rules-panel">
              <div class="panel-heading"><div><span class="panel-kicker">第四部分 · 规则对照</span><h2>六类典型组合</h2></div><span class="selected-hint">经验阈值 · 待回测</span></div>
              <div class="combination-rule-list"><div v-for="item in combinationDefinitions" :key="item.key" :class="{ active: selectedCombination?.key === item.key }"><span>{{ item.condition }}</span><strong>{{ item.state }}</strong></div></div>
            </section>
            <section class="panel table-panel"><div class="panel-heading"><div><span class="panel-kicker">横向比较</span><h2>五大指数指标表</h2></div></div><div class="table-scroll"><table><thead><tr><th>指数</th><th>涨跌幅</th><th>收盘价</th><th>MA20 / MA60</th><th>20日位置</th><th>60日位置</th><th>成交额</th><th>5日 / 20日</th><th>量价状态</th></tr></thead><tbody><tr v-for="index in data.indices" :key="index.code" :class="{ active: selectedIndex?.code === index.code }" @click="selectIndex(index.code)"><td><strong>{{ index.name }}</strong><span>{{ index.code }}</span></td><td :class="changeTone(index.changePct)">{{ formatPct(index.changePct) }}</td><td>{{ index.close.toFixed(2) }}</td><td>{{ index.movingAverages.ma20?.toFixed(2) ?? '--' }} / {{ index.movingAverages.ma60?.toFixed(2) ?? '--' }}</td><td><strong>{{ formatPosition(index.rangePosition20) }}</strong><span>{{ index.rangePosition20Label }}</span></td><td><strong>{{ formatPosition(index.rangePosition60) }}</strong><span>{{ index.rangePosition60Label }}</span></td><td>{{ formatAmount(index.amount) }}</td><td>{{ formatRatio(index.amountRatio5) }} / {{ formatRatio(index.amountRatio20) }}</td><td><span v-if="index.volumePriceState" class="state-chip">{{ index.volumePriceState }}</span><span v-else>--</span></td></tr></tbody></table></div></section>
          </template>

          <template v-else-if="selectedDocumentId === '02'">
            <section class="metric-grid four"><article class="metric-card"><span>上涨家数</span><strong class="positive">{{ formatCount(breadth?.advanceCount) }}</strong></article><article class="metric-card"><span>下跌家数</span><strong class="negative">{{ formatCount(breadth?.declineCount) }}</strong></article><article class="metric-card"><span>上涨占比</span><strong>{{ breadth?.advanceRatio == null ? '--' : formatPosition(breadth.advanceRatio) }}</strong></article><article class="metric-card"><span>涨跌幅中位数</span><strong :class="changeTone(breadth?.medianReturn ?? 0)">{{ formatPct(breadth?.medianReturn) }}</strong></article></section>
            <section class="two-column-grid"><article class="panel analysis-panel"><div class="panel-heading"><div><span class="panel-kicker">全 A 参与面</span><h2>市场广度分布</h2></div><span class="quality-badge" :class="qualityTone(breadth?.quality)">{{ qualityLabel(breadth?.quality) }}</span></div><div v-if="breadthBar" class="breadth-visual"><div class="breadth-bar"><i class="advance" :style="{ width: `${breadthBar.advance}%` }" /><i class="flat-bar" :style="{ width: `${breadthBar.flat}%` }" /><i class="decline" :style="{ width: `${breadthBar.decline}%` }" /></div><div class="breadth-legend"><span><i class="advance" />上涨 {{ formatCount(breadth?.advanceCount) }}</span><span><i class="flat-bar" />平盘 {{ formatCount(breadth?.flatCount) }}</span><span><i class="decline" />下跌 {{ formatCount(breadth?.declineCount) }}</span></div></div><div v-else class="empty-evidence"><Database :size="22" /><strong>市场广度数据不足</strong><p>{{ breadth?.quality.warning || '全 A 上涨、下跌和平盘样本尚未返回。' }}</p></div></article><article class="panel rule-panel"><div class="panel-heading"><div><span class="panel-kicker">组合判定</span><h2>{{ breadth?.state || '数据不足' }}</h2></div></div><p>指数与全 A 中位数同向时才具备广度一致性；缺少全市场样本时不形成强弱结论。</p><div class="source-row"><span>数据源</span><strong>{{ breadth?.quality.source || '--' }}</strong></div></article></section>
          </template>

          <template v-else-if="selectedDocumentId === '03'">
            <section class="metric-grid five"><article class="metric-card"><span>涨停</span><strong class="positive">{{ formatCount(limits?.limitUpCount) }}</strong></article><article class="metric-card"><span>跌停</span><strong class="negative">{{ formatCount(limits?.limitDownCount) }}</strong></article><article class="metric-card"><span>炸板</span><strong>{{ formatCount(limits?.failedLimitUpCount) }}</strong></article><article class="metric-card"><span>炸板率</span><strong>{{ limits?.failedLimitUpRatio == null ? '--' : formatPosition(limits.failedLimitUpRatio) }}</strong></article><article class="metric-card"><span>最高连板</span><strong>{{ limits?.maxStreak == null ? '--' : `${limits.maxStreak} 板` }}</strong></article></section>
            <section class="two-column-grid"><article class="panel analysis-panel"><div class="panel-heading"><div><span class="panel-kicker">短线生态</span><h2>{{ limits?.state || '数据不足' }}</h2></div><span class="quality-badge" :class="qualityTone(limits?.quality)">{{ qualityLabel(limits?.quality) }}</span></div><div class="signal-list"><div><span>热度</span><strong>涨停家数</strong><em>{{ formatCount(limits?.limitUpCount) }}</em></div><div><span>风险</span><strong>跌停家数</strong><em>{{ formatCount(limits?.limitDownCount) }}</em></div><div><span>封板质量</span><strong>炸板率</strong><em>{{ limits?.failedLimitUpRatio == null ? '--' : formatPosition(limits.failedLimitUpRatio) }}</em></div><div><span>接力</span><strong>晋级率</strong><em>{{ limits?.promotionRatio == null ? '--' : formatPosition(limits.promotionRatio) }}</em></div></div></article><article class="panel rule-panel"><div class="panel-heading"><div><span class="panel-kicker">数据质量</span><h2>{{ limits?.quality.source || '未接入' }}</h2></div></div><p>{{ limits?.quality.warning || '涨停、跌停和炸板数据按当日原始交易口径统计。经验分位尚未完成历史校准。' }}</p></article></section>
          </template>

          <template v-else-if="selectedDocumentId === '04'">
            <section class="metric-grid four"><article class="metric-card"><span>高位风险</span><strong>{{ chapter?.tierRisk?.high ?? '--' }}</strong></article><article class="metric-card"><span>中位风险</span><strong>{{ chapter?.tierRisk?.middle ?? '--' }}</strong></article><article class="metric-card"><span>低位风险</span><strong>{{ chapter?.tierRisk?.low ?? '--' }}</strong></article><article class="metric-card"><span>修复率</span><strong>{{ chapter?.tierRisk?.repairRatio == null ? '--' : formatPosition(chapter.tierRisk.repairRatio) }}</strong></article></section>
            <section class="panel analysis-panel"><div class="panel-heading"><div><span class="panel-kicker">分层风险</span><h2>{{ chapter?.tierRisk?.state || '数据不足' }}</h2></div><span class="quality-badge" :class="qualityTone(chapter?.tierRisk?.quality)">{{ qualityLabel(chapter?.tierRisk?.quality) }}</span></div><div class="empty-evidence"><ShieldAlert :size="24" /><strong>分层样本必须独立计算</strong><p>{{ chapter?.tierRisk?.quality.warning || '最高板、核心、中位接力、首板与失败样本尚未形成可追溯数据集，不按安全状态处理。' }}</p></div></section>
          </template>

          <template v-else-if="selectedDocumentId === '05'">
            <section class="panel table-panel"><div class="panel-heading"><div><span class="panel-kicker">行业轮动</span><h2>{{ chapter?.sectors?.state || '板块证据' }}</h2></div><span class="quality-badge" :class="qualityTone(chapter?.sectors?.quality)">{{ qualityLabel(chapter?.sectors?.quality) }}</span></div><div v-if="chapter?.sectors?.rows?.length" class="table-scroll"><table class="sector-table"><thead><tr><th>板块</th><th>涨跌幅</th><th>上涨 / 下跌</th><th>主力净额</th><th>领涨股</th></tr></thead><tbody><tr v-for="row in chapter.sectors.rows" :key="row.code || row.name"><td><strong>{{ row.name }}</strong><span>{{ row.code || '' }}</span></td><td :class="changeTone(row.changePct ?? 0)">{{ formatPct(row.changePct) }}</td><td>{{ formatCount(row.upCount) }} / {{ formatCount(row.downCount) }}</td><td>{{ formatAmount(row.mainNet) }}</td><td>{{ row.leader || '--' }}</td></tr></tbody></table></div><div v-else class="empty-evidence"><BarChart3 :size="24" /><strong>板块数据不足</strong><p>{{ chapter?.sectors?.quality.warning || '行业相对强度、成交持续性、板块宽度和集中度尚未返回。' }}</p></div></section>
          </template>

          <template v-else-if="selectedDocumentId === '06'">
            <section class="panel table-panel"><div class="panel-heading"><div><span class="panel-kicker">容量资金</span><h2>{{ chapter?.activeDirection?.state || '主动进攻方向' }}</h2></div><span class="quality-badge" :class="qualityTone(chapter?.activeDirection?.quality)">{{ qualityLabel(chapter?.activeDirection?.quality) }}</span></div><p v-if="chapter?.activeDirection?.summary" class="panel-summary">{{ chapter.activeDirection.summary }}</p><div v-if="chapter?.activeDirection?.topStocks?.length" class="table-scroll"><table><thead><tr><th>个股</th><th>涨跌幅</th><th>成交额</th><th>方向</th><th>收盘位置</th></tr></thead><tbody><tr v-for="stock in chapter.activeDirection.topStocks" :key="stock.code || stock.name"><td><strong>{{ stock.name || '--' }}</strong><span>{{ stock.code || '--' }}</span></td><td :class="changeTone(stock.changePct ?? 0)">{{ formatPct(stock.changePct) }}</td><td>{{ formatAmount(stock.amount) }}</td><td>{{ stock.industry || '--' }}</td><td>{{ formatPosition(stock.closePosition) }}</td></tr></tbody></table></div><div v-else class="empty-evidence"><Target :size="24" /><strong>未确认容量进攻方向</strong><p>{{ chapter?.activeDirection?.quality.warning || '成交额前 30、方向聚集度和板块同步率尚未形成完整证据。' }}</p></div></section>
          </template>

          <template v-else-if="selectedDocumentId === '07'">
            <section class="two-column-grid"><article class="panel analysis-panel"><div class="panel-heading"><div><span class="panel-kicker">事件台账</span><h2>{{ chapter?.events?.state || '未核实' }}</h2></div><span class="quality-badge" :class="qualityTone(chapter?.events?.quality)">{{ qualityLabel(chapter?.events?.quality) }}</span></div><div v-if="chapter?.events?.items?.length" class="event-list"><article v-for="event in chapter.events.items" :key="`${event.title}-${event.publishedAt}`"><FileCheck2 :size="18" /><div><strong>{{ event.title }}</strong><span>{{ event.source || '来源未标注' }} · {{ event.publishedAt || '时间未标注' }}</span></div><em :class="event.verified ? 'verified' : ''">{{ event.verified ? '已核实' : '待核实' }}</em></article></div><div v-else class="empty-evidence"><FileCheck2 :size="24" /><strong>没有可追溯事件输入</strong><p>{{ chapter?.events?.quality.warning || '事件不直接决定市场环境；未核实传闻不得进入加分。' }}</p></div></article><article class="panel rule-panel"><div class="panel-heading"><div><span class="panel-kicker">调整边界</span><h2>盘面确认后最多 ±5 分</h2></div></div><p>来源可靠性、信息新鲜度、价格成交确认、板块扩散和次日承接必须分开记录。</p></article></section>
          </template>

          <template v-else-if="selectedDocumentId === '08'">
            <section class="classification-layout"><article class="classification-main"><span>当前环境</span><strong>{{ environmentLabel(assessment?.state) }}</strong><p>置信度 {{ confidenceLabel(assessment?.confidence) }} · 规则覆盖 {{ formatCoverage(chapter?.coverage) }}</p></article><article class="panel evidence-panel"><div class="panel-heading"><div><span class="panel-kicker">证据一致性</span><h2>风险优先分类</h2></div></div><div class="evidence-list"><div v-for="item in assessment?.evidence || []" :key="item"><TrendingUp :size="16" /><span>{{ item }}</span></div><div v-if="!assessment?.evidence?.length" class="muted-row"><Database :size="16" /><span>有效证据链不足，暂不归类为趋势、轮动或退潮。</span></div></div></article></section>
          </template>

          <template v-else-if="selectedDocumentId === '09'">
            <section class="synthesis-grid"><article class="conclusion-block"><span class="panel-kicker">唯一结论</span><div class="conclusion-state"><strong>{{ environmentLabel(assessment?.state) }}</strong><em>{{ assessment?.score == null ? '分数不足' : `${assessment.score.toFixed(1)} 分` }}</em></div><p>置信度 {{ confidenceLabel(assessment?.confidence) }}，覆盖率 {{ formatCoverage(chapter?.coverage) }}。经验阈值仍处于待回测状态。</p></article><article class="panel synthesis-panel"><div class="panel-heading"><div><span class="panel-kicker">证据链</span><h2>支持当前判断</h2></div></div><ul v-if="assessment?.evidence?.length"><li v-for="item in assessment.evidence" :key="item">{{ item }}</li></ul><div v-else class="empty-inline">暂无完整证据链</div></article><article class="panel synthesis-panel risk"><div class="panel-heading"><div><span class="panel-kicker">风险否决</span><h2>不可忽略的风险</h2></div></div><ul v-if="assessment?.risks?.length"><li v-for="item in assessment.risks" :key="item">{{ item }}</li></ul><div v-else class="empty-inline">当前未返回已触发的风险否决</div></article><article class="panel verification-panel"><div><span>次日确认</span><strong>{{ assessment?.nextConfirmation || '数据不足，等待新增证据' }}</strong></div><div><span>失效条件</span><strong>{{ assessment?.invalidation || '尚未形成可追溯失效条件' }}</strong></div></article></section>
          </template>

          <section v-if="sectionWarning" class="warning-band"><AlertTriangle :size="17" /><div><strong>本节证据边界</strong><span>{{ sectionWarning }}</span></div></section>
          <section v-if="data.summary.warnings.length" class="warning-band"><AlertTriangle :size="17" /><div><strong>数据质量提醒</strong><span>{{ data.summary.warnings.join('；') }}</span></div></section>
        </template>
        </template>
      </div>
    </main>
  </div>
</template>
