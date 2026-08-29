<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { CalendarDays, ChevronDown, CircleAlert, RefreshCw, TrendingDown, TrendingUp } from 'lucide-vue-next'
import type { IndexAnalysis, MarketEnvironmentResponse } from './types'

const data = ref<MarketEnvironmentResponse | null>(null)
const selectedCode = ref('sh000001')
const selectedDate = ref(new Date().toISOString().slice(0, 10))
const loading = ref(false)
const error = ref('')
const chartElement = ref<HTMLElement | null>(null)
const volumeChartElement = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let volumeChart: echarts.ECharts | null = null
let requestSequence = 0

const selectedIndex = computed<IndexAnalysis | null>(() =>
  data.value?.indices.find((item) => item.code === selectedCode.value) ?? data.value?.indices[0] ?? null,
)

const generatedAt = computed(() => {
  if (!data.value?.generatedAt) return ''
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(data.value.generatedAt))
})

const changeTone = (value: number) => (value > 0 ? 'positive' : value < 0 ? 'negative' : 'flat')
const formatPct = (value: number | null) => (value === null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`)
const formatRatio = (value: number | null) => (value === null ? '--' : `${value.toFixed(2)}x`)
const formatAmount = (value: number) => (value >= 100000000 ? `${(value / 100000000).toFixed(0)} 亿` : `${(value / 10000).toFixed(0)} 万`)
const formatPosition = (value: number | null) => (value === null ? '--' : `${(value * 100).toFixed(0)}%`)

async function loadData() {
  const requestId = ++requestSequence
  loading.value = true
  error.value = ''
  try {
    const response = await fetch(`/api/market-environment?as_of=${selectedDate.value}`)
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `请求失败（${response.status}）`)
    }
    const nextData = await response.json() as MarketEnvironmentResponse
    if (requestId !== requestSequence) return
    data.value = nextData
    if (!data.value.indices.some((item) => item.code === selectedCode.value)) {
      selectedCode.value = data.value.indices[0]?.code ?? ''
    }
  } catch (cause) {
    if (requestId !== requestSequence) return
    error.value = cause instanceof Error ? cause.message : '行情加载失败，请稍后重试'
  } finally {
    if (requestId !== requestSequence) return
    loading.value = false
    await nextTick()
    renderChart()
  }
}

function renderChart() {
  if (!chartElement.value || !volumeChartElement.value || !selectedIndex.value) return
  chart ??= echarts.init(chartElement.value)
  volumeChart ??= echarts.init(volumeChartElement.value)
  const history = selectedIndex.value.history
  const dates = history.map((item) => item.date.slice(5))
  chart.setOption({
    animation: false,
    grid: { top: 18, right: 18, bottom: 34, left: 48 },
    tooltip: { trigger: 'axis', confine: true },
    legend: { top: 0, right: 0, itemWidth: 12, itemHeight: 2, textStyle: { color: '#68727e', fontSize: 11 } },
    xAxis: { type: 'category', data: dates, boundaryGap: false, axisLabel: { color: '#8a939e', fontSize: 10 }, axisLine: { lineStyle: { color: '#dfe4e8' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#8a939e', fontSize: 10 }, splitLine: { lineStyle: { color: '#edf0f2' } } },
    series: [
      { name: '收盘', type: 'line', data: history.map((item) => item.close), showSymbol: false, lineStyle: { width: 2.5, color: '#1c6e8c' } },
      { name: 'MA5', type: 'line', data: history.map((item) => item.ma5), showSymbol: false, connectNulls: false, lineStyle: { width: 1.2, color: '#b85c5c' } },
      { name: 'MA10', type: 'line', data: history.map((item) => item.ma10), showSymbol: false, connectNulls: false, lineStyle: { width: 1.2, color: '#8f6db2' } },
      { name: 'MA20', type: 'line', data: history.map((item) => item.ma20), showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: '#d8893a' } },
      { name: 'MA60', type: 'line', data: history.map((item) => item.ma60), showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: '#8995a2' } },
    ],
  })
  volumeChart.setOption({
    animation: false,
    grid: { top: 8, right: 18, bottom: 24, left: 48 },
    tooltip: { trigger: 'axis', confine: true },
    xAxis: { type: 'category', data: dates, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#edf0f2' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#a0a8b0', fontSize: 9, formatter: (value: number) => `${(value / 100000000).toFixed(0)}亿` }, splitLine: { lineStyle: { color: '#f3f5f6' } } },
    series: [{ name: '成交额', type: 'bar', data: history.map((item) => item.amount || null), barMaxWidth: 12, itemStyle: { color: '#c9d9dc' } }],
  })
}

function selectIndex(code: string) {
  selectedCode.value = code
}

watch(selectedIndex, async () => {
  await nextTick()
  renderChart()
})

onMounted(() => {
  loadData()
  window.addEventListener('resize', () => chart?.resize())
})
</script>

<template>
  <main class="market-shell">
    <header class="page-header">
      <div class="title-block">
        <div class="eyebrow">A 股 · 盘后研究</div>
        <h1>市场环境分析</h1>
        <p>指数看方向，位置看阶段，成交额看资金是否认可。</p>
      </div>
      <div class="header-actions">
        <label class="date-field">
          <CalendarDays :size="16" aria-hidden="true" />
          <span class="sr-only">选择交易日</span>
          <input v-model="selectedDate" type="date" :max="new Date().toISOString().slice(0, 10)" :disabled="loading" @change="loadData" />
        </label>
        <button class="icon-button" type="button" :disabled="loading" aria-label="刷新行情" title="刷新行情" @click="loadData">
          <RefreshCw :size="17" :class="{ spin: loading }" />
        </button>
      </div>
    </header>

    <section v-if="error" class="state-panel error-panel" role="alert">
      <CircleAlert :size="22" />
      <div><strong>行情暂时不可用</strong><p>{{ error }}</p></div>
      <button class="text-button" type="button" @click="loadData">重新加载</button>
    </section>
    <section v-else-if="loading && !data" class="state-panel"><div class="loader" /><span>正在读取指数行情…</span></section>

    <template v-else-if="data">
      <section class="status-strip">
        <div><span class="status-label">实际交易日</span><strong>{{ data.asOf }}</strong></div>
        <div><span class="status-label">指数状态</span><strong>{{ data.summary.synchronization }}</strong></div>
        <div><span class="status-label">主导趋势</span><strong>{{ data.summary.dominantTrend }}</strong></div>
        <div class="status-meta"><span>数据更新 {{ generatedAt }}</span><span class="source-dot" /> <span>5 个指数</span></div>
      </section>

      <section class="index-cards" aria-label="指数概览">
        <button v-for="index in data.indices" :key="index.code" class="index-card" :class="{ selected: selectedIndex?.code === index.code }" type="button" @click="selectIndex(index.code)">
          <div class="card-top"><span>{{ index.name }}</span><span class="code">{{ index.code }}</span></div>
          <div class="card-price"><strong>{{ index.close.toFixed(2) }}</strong><span :class="changeTone(index.changePct)">{{ formatPct(index.changePct) }}</span></div>
          <div class="card-bottom"><span :class="index.trendState === '偏弱' || index.trendState === '趋势破坏' ? 'negative' : 'positive'">{{ index.trendState }}</span><span>{{ index.volumePriceState }}</span></div>
        </button>
      </section>

      <section class="workspace-grid">
        <article class="panel chart-panel">
          <div class="panel-heading"><div><span class="panel-kicker">价格结构</span><h2>{{ selectedIndex?.name }} · 60 日走势</h2></div><span class="selected-hint"><TrendingUp v-if="selectedIndex && selectedIndex.changePct >= 0" :size="15" /><TrendingDown v-else :size="15" /> {{ selectedIndex?.trendState }}</span></div>
          <div ref="chartElement" class="price-chart" />
          <div class="volume-heading"><span>60 日成交额</span><span>金额单位：元</span></div>
          <div ref="volumeChartElement" class="volume-chart" />
          <div class="chart-footnote"><span>历史收盘与 MA5 / MA10 / MA20 / MA60</span><span>数据源：{{ selectedIndex?.dataQuality.source }}</span></div>
        </article>

        <article class="panel detail-panel">
          <div class="panel-heading"><div><span class="panel-kicker">当前结构</span><h2>趋势与量能</h2></div><ChevronDown :size="16" class="muted-icon" /></div>
          <div v-if="selectedIndex" class="metric-stack">
            <div class="metric-row"><span>MA5 / MA10</span><strong>{{ selectedIndex.movingAverages.ma5?.toFixed(2) ?? '--' }} <small>/</small> {{ selectedIndex.movingAverages.ma10?.toFixed(2) ?? '--' }}</strong></div>
            <div class="metric-row"><span>MA20 / MA60</span><strong>{{ selectedIndex.movingAverages.ma20?.toFixed(2) ?? '--' }} <small>/</small> {{ selectedIndex.movingAverages.ma60?.toFixed(2) ?? '--' }}</strong></div>
            <div class="metric-row"><span>20 日位置</span><strong>{{ formatPosition(selectedIndex.rangePosition20) }} <em>{{ selectedIndex.rangePosition20Label }}</em></strong></div>
            <div class="metric-row"><span>60 日位置</span><strong>{{ formatPosition(selectedIndex.rangePosition60) }} <em>{{ selectedIndex.rangePosition60Label }}</em></strong></div>
            <div class="metric-row"><span>成交额</span><strong>{{ formatAmount(selectedIndex.amount) }}</strong></div>
            <div class="metric-row"><span>成交额 / 5日均值</span><strong>{{ formatRatio(selectedIndex.amountRatio5) }}</strong></div>
            <div class="metric-row"><span>成交额 / 20日均值</span><strong>{{ formatRatio(selectedIndex.amountRatio20) }}</strong></div>
          </div>
        </article>
      </section>

      <section class="panel table-panel">
        <div class="panel-heading"><div><span class="panel-kicker">横向比较</span><h2>五大指数指标表</h2></div><span class="table-note">点击行查看详情</span></div>
        <div class="table-scroll"><table><thead><tr><th>指数</th><th>涨跌幅</th><th>收盘价</th><th>MA20 / MA60</th><th>20日位置</th><th>60日位置</th><th>成交额</th><th>5日 / 20日</th><th>量价状态</th></tr></thead><tbody><tr v-for="index in data.indices" :key="index.code" :class="{ active: selectedIndex?.code === index.code }" @click="selectIndex(index.code)"><td><strong>{{ index.name }}</strong><span>{{ index.code }}</span></td><td :class="changeTone(index.changePct)">{{ formatPct(index.changePct) }}</td><td>{{ index.close.toFixed(2) }}</td><td>{{ index.movingAverages.ma20?.toFixed(2) ?? '--' }} / {{ index.movingAverages.ma60?.toFixed(2) ?? '--' }}</td><td><strong>{{ formatPosition(index.rangePosition20) }}</strong><span>{{ index.rangePosition20Label }}</span></td><td><strong>{{ formatPosition(index.rangePosition60) }}</strong><span>{{ index.rangePosition60Label }}</span></td><td>{{ formatAmount(index.amount) }}</td><td>{{ formatRatio(index.amountRatio5) }} / {{ formatRatio(index.amountRatio20) }}</td><td><span class="state-chip">{{ index.volumePriceState }}</span></td></tr></tbody></table></div>
      </section>

      <section class="conclusion-grid">
        <article class="panel conclusion-panel"><div class="panel-heading"><div><span class="panel-kicker">分析结论</span><h2>今天的市场结构</h2></div></div><p class="conclusion-lead">{{ data.summary.synchronization }}，整体主导趋势为 <strong>{{ data.summary.dominantTrend }}</strong>。</p><p class="conclusion-copy">当前页面只对指数、趋势位置和成交额进行判断；上涨家数、下跌家数和涨跌幅中位数等市场广度指标尚未纳入本版。</p></article>
        <article class="panel warning-panel"><div class="panel-heading"><div><span class="panel-kicker">数据质量</span><h2>来源与提醒</h2></div></div><ul v-if="data.summary.warnings.length"><li v-for="warning in data.summary.warnings" :key="warning">{{ warning }}</li></ul><p v-else>所有指数均已返回有效历史数据。</p></article>
      </section>
    </template>
  </main>
</template>
