<script setup lang="ts">
import { BarChart3, CircleAlert, History, RefreshCw, ShieldAlert } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

import {
  fetchThsOperation,
  fetchThsSectorBars,
  pollCollectionRun,
  pollThsOperation,
  startCollectionRun,
  startSectorTurnoverBackfill,
  startThsCatalogSync,
} from '../../collection-api'
import type {
  ThsOperationProgress,
  ThsSectorBarsResponse,
} from '../../collection-api'
import SectorTurnoverChartPanel from '../../components/charts/SectorTurnoverChartPanel.vue'
import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'
import type {
  SectorCandidate,
  SectorCandidateStage,
  SectorMetricTrace,
  SectorStructureSecurity,
  ThsIndustryRankingRow,
  ThsSectorBreadthRow,
  ThsSectorTag,
} from '../../types'

const market = useMarketStore()
const ctx = useDocumentContext()

type SectorView = 'ranking' | 'breadth' | 'turnover' | 'continuity'

const activeView = ref<SectorView>('ranking')
const rankingTag = ref<ThsSectorTag>('industry')
const rankingSearch = ref('')
const selectedThscode = ref('')
const klineStartDate = ref('')
const klineEndDate = ref('')
const barsResponse = ref<ThsSectorBarsResponse | null>(null)
const barsLoading = ref(false)
const barsError = ref('')
const backfillLoading = ref(false)
const operation = ref<ThsOperationProgress | null>(null)
const breadthSelectionLoading = ref(false)
const breadthSelectionError = ref('')

const industryRanking = computed(() => market.chapter?.industryRanking)
const sectorBreadth = computed(() => market.chapter?.sectorBreadth)
const sectorTurnover = computed(() => market.chapter?.sectorTurnover)
const selectedAsOf = computed(() => market.data?.asOf ?? market.selectedDate)
const rawAnalysis = computed(() => market.chapter?.sectorAnalysis ?? null)
const analysis = computed(() => rawAnalysis.value?.asOf === selectedAsOf.value ? rawAnalysis.value : null)
const hasMismatchedAnalysis = computed(() => Boolean(rawAnalysis.value && !analysis.value))
const rankingIsExactDate = computed(() => industryRanking.value?.quality.asOf === selectedAsOf.value)
const allRankingRows = computed(() => rankingIsExactDate.value ? industryRanking.value?.rows ?? [] : [])
const tagRankingRows = computed(() => allRankingRows.value.filter((row) => row.tag === rankingTag.value))
const rankingRows = computed(() => {
  const query = rankingSearch.value.trim().toLocaleLowerCase('zh-CN')
  if (!query) return tagRankingRows.value
  return tagRankingRows.value.filter((row) => (
    row.thscode.toLocaleLowerCase('zh-CN').includes(query)
    || row.name.toLocaleLowerCase('zh-CN').includes(query)
  ))
})
const breadthIsExactDate = computed(() => sectorBreadth.value?.quality.asOf === selectedAsOf.value)
const breadthRows = computed(() => breadthIsExactDate.value ? sectorBreadth.value?.rows ?? [] : [])
const selectedRanking = computed(() => allRankingRows.value.find((row) => row.thscode === selectedThscode.value) ?? null)
const completeBars = computed(() => (barsResponse.value?.items ?? []).filter((bar) => (
  bar.open != null && bar.high != null && bar.low != null && bar.close != null
)))
const needsBackfill = computed(() => {
  const response = barsResponse.value
  if (!response) return false
  const coverage = response.coverage
  return Boolean(
    coverage.gaps.length
    || (klineStartDate.value && (!coverage.firstDate || coverage.firstDate > klineStartDate.value))
    || (klineEndDate.value && (!coverage.lastDate || coverage.lastDate < klineEndDate.value)),
  )
})
const rankingWarnings = computed(() => [...new Set([
  industryRanking.value?.quality.warning,
  ...(industryRanking.value?.quality.warnings ?? []),
].filter((warning): warning is string => Boolean(warning)))])
const analysisWarnings = computed(() => [...new Set([
  ...(analysis.value?.warnings ?? []),
  ...(analysis.value?.quality.warnings ?? []),
  ...(analysis.value?.quality.missingInputs ?? []).map((item) => `缺少输入：${item}`),
  ...(analysis.value?.history?.gaps ?? []).map((item) => `历史缺口：${item}`),
  analysis.value?.latestAttempt?.warning,
].filter((warning): warning is string => Boolean(warning)))])

const VIEW_TABS: Array<{ id: SectorView; label: string }> = [
  { id: 'ranking', label: '排名' },
  { id: 'breadth', label: '板块宽度' },
  { id: 'turnover', label: '量价 K 线' },
  { id: 'continuity', label: '申万持续性' },
]

const TAG_LABELS: Record<ThsSectorTag, string> = {
  industry: '行业',
  cn_concept: '概念',
  region: '区域',
  tszs: '特色指数',
}

const METRICS = [
  { id: 'QTS-01-05-01', title: '相对强度', hint: '5 日 / 20 日超额收益较低滚动分位' },
  { id: 'QTS-01-05-02', title: '成交持续性', hint: '近 5 日进入行业成交额前 20% 的天数' },
  { id: 'QTS-01-05-03', title: '板块宽度', hint: '有效成员收盘高于 MA20 比例的滚动分位' },
  { id: 'QTS-01-05-04', title: '分歧承接', hint: '负收益分歧后两个完整交易日的修复分位' },
  { id: 'QTS-01-05-05', title: '成交集中度', hint: '成交额前五行业占全市场成交额的滚动分位' },
] as const

const metricCards = computed(() => METRICS.map((metric) => ({
  ...metric,
  trace: analysis.value?.metricTraces.find((item) => item.ruleId === metric.id) ?? null,
})))
const lineageEntries = computed(() => Object.entries(analysis.value?.lineage ?? {})
  .filter(([, value]) => ['string', 'number'].includes(typeof value) && value !== '')
  .slice(0, 9))
const marketRisk = computed(() => analysis.value?.risk ?? {})
const marketRiskVetoes = computed(() => {
  const values = marketRisk.value.vetoes
  return Array.isArray(values) ? values.filter((item): item is string => typeof item === 'string') : []
})

const STAGE_LABELS: Record<SectorCandidateStage, string> = {
  insufficient: '数据不足',
  'high-level-crowding': '高位抱团',
  'mainline-confirmed': '主线确认',
  'mainline-candidate': '主线候选',
  'one-day-pulse': '单日脉冲',
  'rotation-or-ebb': '轮动或退潮',
}

function stageLabel(value: SectorCandidateStage): string {
  return STAGE_LABELS[value] ?? value
}

function formatCount(value: number | null | undefined): string {
  return value == null ? '--' : value.toLocaleString('zh-CN')
}

function formatAmount(value: number | null | undefined): string {
  return value == null ? '--' : Math.abs(value) >= 100000000 ? `${(value / 100000000).toFixed(1)} 亿` : `${(value / 10000).toFixed(0)} 万`
}

function changeTone(value: number | null | undefined): 'positive' | 'negative' | 'flat' {
  if (value == null) return 'flat'
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'flat'
}

function formatPct(value: number | null | undefined): string {
  return value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatRatio(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(1)}%`
}

function formatCoverage(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`
}

function formatMetricValue(trace: SectorMetricTrace | null, ruleId: string): string {
  if (!trace || ['insufficient', 'missing', 'failed'].includes(trace.status)) return '--'
  if (ruleId === 'QTS-01-05-02') return trace.value == null ? '--' : `${trace.value} 天`
  const percentile = trace.percentile ?? trace.value
  if (percentile == null) return '--'
  return `P${Math.round(percentile <= 1 ? percentile * 100 : percentile)}`
}

function formatScore(value: number | null | undefined): string {
  return value == null ? '--' : `${value.toFixed(Number.isInteger(value) ? 0 : 1)} 分`
}

function traceStatusLabel(trace: SectorMetricTrace | null): string {
  return trace ? ctx.metricQualityLabel(trace.status) : '数据不足'
}

function traceStatusTone(trace: SectorMetricTrace | null): string {
  return trace ? ctx.metricQualityTone(trace.status) : 'missing'
}

function topSecurityLabel(rows: SectorStructureSecurity[]): string {
  if (!rows.length) return '--'
  return rows.slice(0, 3).map((row) => row.name || row.code || row.securityId || '--').join('、')
}

function candidateRisk(candidate: SectorCandidate): string {
  if (candidate.crowdingRisk === true) return '触发抱团风险'
  if (candidate.crowdingRisk === false) return '未触发抱团风险'
  return '风险证据不足'
}

function lineageLabel(key: string): string {
  return ({
    source: '数据源', dataVersion: '数据版本', classificationVersion: '分类版本',
    membershipVersion: '成员版本', universeVersion: '范围版本', adjustmentVersion: '复权版本',
    benchmarkVersion: '基准版本', calculationVersion: '计算版本', checksum: '证据校验',
  } as Record<string, string>)[key] ?? key
}

function rankingName(thscode: string): string {
  return allRankingRows.value.find((row) => row.thscode === thscode)?.name ?? thscode
}

function breadthTopLabel(rows: ThsSectorBreadthRow['topByTurnover']): string {
  if (!rows.length) return '--'
  return rows.slice(0, 3).map((row) => row.name || row.securityId).join('、')
}

function tagLabel(tag: ThsSectorTag | null | undefined): string {
  return tag ? TAG_LABELS[tag] : '用户点选'
}

function yearsAgo(value: string, years: number): string {
  const date = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(date.getTime())) return ''
  date.setUTCFullYear(date.getUTCFullYear() - years)
  return date.toISOString().slice(0, 10)
}

function operationStatusLabel(value?: string | null): string {
  return ({
    queued: '等待执行', running: '执行中', success: '成功', partial: '部分完成',
    failed: '失败', conflict: '存在冲突', blocked: '依赖阻塞',
  } as Record<string, string>)[value ?? ''] ?? value ?? '未知'
}

async function loadBars(): Promise<void> {
  if (!selectedThscode.value || !klineStartDate.value || !klineEndDate.value) return
  barsLoading.value = true
  barsError.value = ''
  barsResponse.value = null
  try {
    barsResponse.value = await fetchThsSectorBars(selectedThscode.value, {
      startDate: klineStartDate.value,
      endDate: klineEndDate.value,
      page: 1,
      pageSize: 1500,
    })
  } catch (cause) {
    barsError.value = cause instanceof Error ? cause.message : '本地 K 线读取失败'
  } finally {
    barsLoading.value = false
  }
}

async function refreshOperation(): Promise<void> {
  if (!operation.value?.runId) return
  try {
    operation.value = await fetchThsOperation(operation.value.runId)
  } catch (cause) {
    barsError.value = cause instanceof Error ? cause.message : '回填进度读取失败'
  }
}

async function startBackfill(): Promise<void> {
  if (!selectedThscode.value || !klineStartDate.value || !klineEndDate.value) return
  backfillLoading.value = true
  barsError.value = ''
  try {
    const queued = await startSectorTurnoverBackfill({
      thscodes: [selectedThscode.value],
      startDate: klineStartDate.value,
      endDate: klineEndDate.value,
    })
    operation.value = {
      runId: queued.runId,
      kind: 'turnover-backfill',
      status: queued.status,
      progress: { completed: 0, total: 1, failed: 0, conflicts: 0 },
      warning: null,
      checkpoints: [],
    }
    await refreshOperation()
  } catch (cause) {
    barsError.value = cause instanceof Error ? cause.message : '历史回填发起失败'
  } finally {
    backfillLoading.value = false
  }
}

async function selectBreadth(thscode: string): Promise<void> {
  if (!selectedAsOf.value || breadthSelectionLoading.value) return
  selectedThscode.value = thscode
  activeView.value = 'breadth'
  breadthSelectionLoading.value = true
  breadthSelectionError.value = ''
  try {
    const queued = await startThsCatalogSync({
      asOf: selectedAsOf.value,
      membershipThscodes: [thscode],
    })
    const completed = await pollThsOperation(queued.runId, { intervalMs: 600 })
    if (!completed || !['success', 'partial'].includes(completed.status)) {
      throw new Error(completed?.warning || '点选板块成员同步未完成')
    }
    const collection = await startCollectionRun(selectedAsOf.value, ['sector-breadth'])
    const collected = await pollCollectionRun(collection.runId)
    if (!collected || !['success', 'partial'].includes(collected.status)) {
      throw new Error('点选板块宽度采集未完成')
    }
    await market.loadSection('sectors', true)
  } catch (cause) {
    breadthSelectionError.value = cause instanceof Error ? cause.message : '点选板块宽度发起失败'
  } finally {
    breadthSelectionLoading.value = false
  }
}

watch(selectedAsOf, (value) => {
  klineEndDate.value = value
  klineStartDate.value = yearsAgo(value, 1)
}, { immediate: true })

watch(tagRankingRows, (rows) => {
  if (!rows.some((row) => row.thscode === selectedThscode.value)) {
    selectedThscode.value = rows[0]?.thscode ?? ''
  }
}, { immediate: true })

watch(
  [activeView, selectedThscode, klineStartDate, klineEndDate],
  ([view]) => {
    if (view === 'turnover') void loadBars()
  },
)
</script>

<template>
  <p class="page-flow-label">THS provider observation 与申万 canonical analysis 独立展示，不按名称推断身份。</p>

  <nav class="sector-view-tabs" aria-label="行业板块视图">
    <button
      v-for="tab in VIEW_TABS"
      :key="tab.id"
      type="button"
      :class="{ active: activeView === tab.id }"
      :aria-selected="activeView === tab.id"
      role="tab"
      @click="activeView = tab.id"
    >{{ tab.label }}</button>
  </nav>

  <div v-if="breadthSelectionError" class="sector-analysis-notice warning" role="alert"><CircleAlert :size="20" /><div><strong>点选板块宽度未完成</strong><p>{{ breadthSelectionError }}</p></div></div>

  <section v-if="activeView === 'ranking'" class="panel table-panel ths-ranking-panel" aria-labelledby="ths-ranking-title">
    <div class="panel-heading">
      <div><span class="panel-kicker">THS provider observation</span><h2 id="ths-ranking-title">四类目录与当日排名</h2></div>
      <span class="quality-badge" :class="ctx.qualityTone(industryRanking?.quality)">{{ ctx.qualityLabel(industryRanking?.quality) }}</span>
    </div>
    <div class="sector-ranking-controls">
      <label><span>分类</span><select v-model="rankingTag"><option v-for="(label, tag) in TAG_LABELS" :key="tag" :value="tag">{{ label }}</option></select></label>
      <label><span>搜索名称或编号</span><input v-model="rankingSearch" type="search" placeholder="例如 半导体 / 885000.TI" /></label>
      <div><span>目录版本</span><strong>{{ industryRanking?.revisionId || rankingRows[0]?.catalogRevision || '--' }}</strong></div>
    </div>
    <div v-if="industryRanking && !rankingIsExactDate" class="sector-analysis-notice warning" role="status">
      <CircleAlert :size="20" /><div><strong>排名日期不一致</strong><p>所选 {{ selectedAsOf }}，本地排名证据为 {{ industryRanking.quality.asOf || '未知' }}；不展示跨日期结果。</p></div>
    </div>
    <div v-else-if="rankingRows.length" class="table-scroll ths-ranking-scroll">
      <table class="sector-table ths-ranking-table">
        <thead><tr><th>排名</th><th>板块</th><th>涨跌幅</th><th>成交量</th><th>成交额</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rankingRows" :key="`${row.tag}:${row.thscode}`">
            <td>{{ row.rank }}</td>
            <td><strong>{{ row.name }}</strong><span>{{ row.thscode }}</span></td>
            <td :class="changeTone(row.changePct)">{{ formatPct(row.changePct) }}</td>
            <td>{{ formatAmount(row.volume) }}</td>
            <td>{{ formatAmount(row.turnover) }}</td>
            <td><div class="ths-ranking-actions"><button class="inline-icon-command" type="button" :disabled="breadthSelectionLoading" @click="selectBreadth(row.thscode)"><BarChart3 :size="15" /><span>计算宽度</span></button><button class="inline-icon-command" type="button" @click="selectedThscode = row.thscode; activeView = 'turnover'"><History :size="15" /><span>查看 K 线</span></button></div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty-evidence">
      <BarChart3 :size="24" /><strong>本地排名不足</strong><p>{{ rankingWarnings.join('；') || '当前分类没有匹配的精确日期目录与排名。' }}</p>
    </div>
  </section>

  <section v-if="activeView === 'breadth'" class="panel ths-breadth-panel" aria-labelledby="ths-breadth-title">
    <div class="panel-heading">
      <div><span class="panel-kicker">当前交易日 · Top 10 与用户点选</span><h2 id="ths-breadth-title">板块内部宽度</h2></div>
      <span class="quality-badge" :class="ctx.qualityTone(sectorBreadth?.quality)">{{ ctx.qualityLabel(sectorBreadth?.quality) }}</span>
    </div>
    <div v-if="sectorBreadth && !breadthIsExactDate" class="sector-analysis-notice warning" role="status">
      <CircleAlert :size="20" /><div><strong>宽度日期不一致</strong><p>历史宽度不使用当前成员回算；所选日期没有可展示的 exact-date 结果。</p></div>
    </div>
    <div v-else-if="breadthRows.length" class="ths-breadth-grid">
      <article v-for="row in breadthRows" :key="row.thscode" class="ths-breadth-card">
        <header><div><span>{{ tagLabel(row.tag) }} · {{ row.thscode }}</span><h3>{{ row.name || rankingName(row.thscode) }}</h3></div><div class="ths-breadth-card-actions"><em :class="row.quality">{{ ctx.metricQualityLabel(row.quality) }}</em><button class="inline-icon-command" type="button" :disabled="breadthSelectionLoading" @click="selectBreadth(row.thscode)">点选此板块</button></div></header>
        <div class="ths-breadth-metrics">
          <div><span>上涨 / 下跌 / 平盘</span><strong>{{ row.advanceCount }} / {{ row.declineCount }} / {{ row.flatCount }}</strong><small>有效 {{ row.validDirectionCount }} / 成员 {{ row.memberCount }}</small></div>
          <div><span>上涨占比</span><strong>{{ formatRatio(row.advanceRatio) }}</strong><small>差率 {{ formatRatio(row.advanceDeclineSpreadRatio) }}</small></div>
          <div><span>中位涨幅</span><strong>{{ formatPct(row.medianChangePct) }}</strong><small>同日成员事实</small></div>
          <div><span>MA20 宽度</span><strong>{{ formatRatio(row.ma20Breadth) }}</strong><small>{{ row.closeAboveMa20Count }} / {{ row.validMa20Count }}</small></div>
          <div><span>涨停 / 跌停</span><strong>{{ formatCount(row.limitUpCount) }} / {{ formatCount(row.limitDownCount) }}</strong><small>同日 limits 交集</small></div>
          <div><span>扩散率</span><strong>{{ formatRatio(row.diffusionRate) }}</strong><small>最高单股贡献 {{ formatRatio(row.maxMemberTurnoverContribution) }}</small></div>
        </div>
        <dl class="ths-breadth-toplists">
          <div><dt>Top 成交</dt><dd>{{ breadthTopLabel(row.topByTurnover) }}</dd></div>
          <div><dt>Top 涨幅</dt><dd>{{ breadthTopLabel(row.topByGain) }}</dd></div>
          <div><dt>选择来源</dt><dd>{{ row.selectionReasons.join('、') }}</dd></div>
        </dl>
        <ul v-if="row.warnings.length"><li v-for="warning in row.warnings" :key="warning">{{ warning }}</li></ul>
      </article>
    </div>
    <div v-else class="empty-evidence"><BarChart3 :size="24" /><strong>当日宽度不足</strong><p>仅在当前已完成上海交易日、成员事实和依赖可用时计算。</p></div>
  </section>

  <section v-if="activeView === 'turnover'" class="panel ths-turnover-panel" aria-labelledby="ths-turnover-title">
    <div class="panel-heading">
      <div><span class="panel-kicker">本地 PostgreSQL · 单编号</span><h2 id="ths-turnover-title">板块量价 K 线</h2></div>
      <span class="quality-badge" :class="ctx.qualityTone(sectorTurnover?.quality)">{{ ctx.qualityLabel(sectorTurnover?.quality) }}</span>
    </div>
    <div class="sector-kline-controls">
      <label><span>板块编号</span><select v-model="selectedThscode"><option v-for="row in allRankingRows" :key="`${row.tag}:${row.thscode}`" :value="row.thscode">{{ row.name }} · {{ row.thscode }}</option></select></label>
      <label><span>开始日期</span><input v-model="klineStartDate" type="date" :max="klineEndDate" /></label>
      <label><span>结束日期</span><input v-model="klineEndDate" type="date" :max="selectedAsOf" /></label>
      <button class="icon-button" type="button" :disabled="barsLoading || !selectedThscode" title="刷新本地 K 线" aria-label="刷新本地 K 线" @click="loadBars"><RefreshCw :size="17" :class="{ spin: barsLoading }" /></button>
    </div>
    <div v-if="barsResponse" class="sector-kline-coverage">
      <div><span>实际覆盖</span><strong>{{ barsResponse.coverage.firstDate || '--' }} 至 {{ barsResponse.coverage.lastDate || '--' }}</strong></div>
      <div><span>本地行数</span><strong>{{ barsResponse.coverage.storedRows }}</strong></div>
      <div><span>缺口</span><strong>{{ barsResponse.coverage.gaps.length ? barsResponse.coverage.gaps.join('、') : '无' }}</strong></div>
      <button v-if="needsBackfill" class="command-button" type="button" :disabled="backfillLoading" @click="startBackfill"><History :size="16" /><span>{{ backfillLoading ? '正在发起…' : '显式回填缺口' }}</span></button>
    </div>
    <div v-if="barsError" class="sector-analysis-notice warning" role="alert"><CircleAlert :size="20" /><div><strong>量价操作未完成</strong><p>{{ barsError }}</p></div></div>
    <div v-if="barsLoading" class="state-panel"><div class="loader" /><span>正在读取本地 K 线…</span></div>
    <template v-else-if="completeBars.length">
      <SectorTurnoverChartPanel :bars="completeBars" />
      <p class="sector-kline-footnote">{{ selectedRanking?.name || selectedThscode }} · 蜡烛、成交量和成交额均来自本地已验证覆盖；缺失字段不以 0 替代。</p>
    </template>
    <div v-else-if="barsResponse" class="empty-evidence"><BarChart3 :size="24" /><strong>本地历史不足</strong><p>当前区间没有完整 OHLC；页面不会自动访问 provider，请使用显式回填操作。</p></div>
    <section v-if="operation" class="sector-operation-status" aria-label="历史回填进度">
      <div><span>回填任务</span><strong>{{ operation.runId }}</strong></div>
      <div><span>状态</span><strong>{{ operationStatusLabel(operation.status) }}</strong></div>
      <div><span>进度</span><strong>{{ operation.progress.completed }} / {{ operation.progress.total }}</strong></div>
      <div><span>失败 / 冲突</span><strong>{{ operation.progress.failed }} / {{ operation.progress.conflicts }}</strong></div>
      <button class="inline-icon-command" type="button" @click="refreshOperation"><RefreshCw :size="15" /><span>刷新进度</span></button>
      <p v-if="operation.warning">{{ operation.warning }}</p>
    </section>
  </section>

  <section v-if="activeView === 'continuity'" class="panel sector-analysis-panel" aria-labelledby="sector-analysis-title">
    <div class="panel-heading">
      <div><span class="panel-kicker">申万一级 · 连续性分析</span><h2 id="sector-analysis-title">第 05 章五项规则证据</h2></div>
      <span v-if="analysis" class="quality-badge" :class="ctx.metricQualityTone(analysis.status)">{{ ctx.metricQualityLabel(analysis.status) }}</span>
      <span v-else class="quality-badge missing">仅观察层</span>
    </div>

    <div v-if="hasMismatchedAnalysis" class="sector-analysis-notice warning" role="status">
      <CircleAlert :size="20" />
      <div><strong>分析日期与所选日期不一致</strong><p>所选 {{ selectedAsOf }}，本地分析为 {{ rawAnalysis?.asOf }}；本页不会跨日期展示五项指标。</p></div>
    </div>
    <div v-else-if="!analysis" class="sector-analysis-notice" role="status">
      <BarChart3 :size="22" />
      <div><strong>当前为 observation-only</strong><p>provider 行业排名可独立查看，但不能替代申万历史、时点成员和滚动分位。五项规则证据保持数据不足。</p></div>
    </div>

    <template v-else>
      <div class="sector-analysis-summary">
        <div><span>分析日期</span><strong>{{ analysis.asOf }}</strong></div>
        <div><span>置信度</span><strong>{{ ctx.confidenceLabel(analysis.quality.confidence) }}</strong></div>
        <div><span>历史覆盖</span><strong>{{ formatCoverage(analysis.quality.coverage) }}</strong></div>
        <div><span>有效历史</span><strong>{{ analysis.history?.validObservations ?? analysis.quality.availableObservations }} / {{ analysis.history?.requiredObservations ?? analysis.quality.requiredObservations }}</strong></div>
        <div><span>窗口</span><strong>{{ analysis.history?.windowDays ?? '--' }} 个交易日</strong></div>
        <div><span>最近尝试</span><strong>{{ analysis.latestAttempt?.status || '--' }}</strong></div>
      </div>

      <div class="sector-metric-grid" aria-label="五项规则证据">
        <article v-for="metric in metricCards" :key="metric.id" class="sector-metric-card" :class="traceStatusTone(metric.trace)">
          <div class="sector-metric-heading"><span>{{ metric.id }}</span><em>{{ traceStatusLabel(metric.trace) }}</em></div>
          <h3>{{ metric.title }}</h3>
          <strong>{{ formatMetricValue(metric.trace, metric.id) }}</strong>
          <p>{{ metric.hint }}</p>
          <dl>
            <div><dt>评分</dt><dd>{{ formatScore(metric.trace?.score) }}</dd></div>
            <div><dt>有效观察</dt><dd>{{ metric.trace?.observations ?? 0 }} / {{ metric.trace?.requiredObservations ?? 60 }}</dd></div>
            <div><dt>权重</dt><dd>{{ metric.trace?.normalizedWeight == null ? '--' : formatRatio(metric.trace.normalizedWeight) }}</dd></div>
          </dl>
          <small v-if="metric.trace?.missingReason">{{ metric.trace.missingReason }}</small>
        </article>
      </div>

      <div v-if="analysisWarnings.length" class="sector-analysis-warnings" role="status">
        <strong>分析缺口</strong>
        <ul><li v-for="warning in analysisWarnings" :key="warning">{{ warning }}</li></ul>
      </div>

      <div v-if="lineageEntries.length" class="sector-lineage" aria-label="分析版本与血缘">
        <div v-for="[key, value] in lineageEntries" :key="key"><span>{{ lineageLabel(key) }}</span><strong>{{ value }}</strong></div>
      </div>
    </template>
  </section>

  <section v-if="activeView === 'continuity' && analysis" class="panel sector-candidates-panel" aria-labelledby="sector-candidates-title">
    <div class="panel-heading">
      <div><span class="panel-kicker">候选与阶段</span><h2 id="sector-candidates-title">Canonical 申万候选（最多三个）</h2></div>
      <span class="quality-badge" :class="analysis.candidates.length ? 'ok' : 'missing'">{{ analysis.candidates.length }} 个</span>
    </div>

    <div v-if="analysis.candidates.length" class="sector-candidate-grid">
      <article v-for="(candidate, index) in analysis.candidates" :key="candidate.industryId" class="sector-candidate-card">
        <div class="sector-candidate-heading">
          <div><span>候选 {{ index + 1 }} · {{ candidate.industryId }}</span><h3>{{ candidate.displayName }}</h3></div>
          <em>{{ stageLabel(candidate.stage) }}</em>
        </div>
        <div class="sector-candidate-score"><strong>{{ formatScore(candidate.totalScore) }}</strong><span>确认连续 {{ candidate.confirmationStreak }} 日</span></div>
        <div class="sector-risk-row" :class="{ active: candidate.crowdingRisk === true }">
          <ShieldAlert :size="17" /><strong>{{ candidateRisk(candidate) }}</strong>
        </div>
        <ul v-if="candidate.vetoes.length" class="sector-veto-list"><li v-for="veto in candidate.vetoes" :key="veto">{{ veto }}</li></ul>
        <dl v-if="candidate.internalStructure" class="sector-structure-grid">
          <div><dt>有效成员</dt><dd>{{ formatCount(candidate.internalStructure.effectiveMemberCount) }}</dd></div>
          <div><dt>上涨 / 下跌</dt><dd>{{ formatCount(candidate.internalStructure.advancingCount) }} / {{ formatCount(candidate.internalStructure.decliningCount) }}</dd></div>
          <div><dt>涨停 / 跌停</dt><dd>{{ formatCount(candidate.internalStructure.limitUpCount) }} / {{ formatCount(candidate.internalStructure.limitDownCount) }}</dd></div>
          <div><dt>最高单股成交贡献</dt><dd>{{ formatRatio(candidate.internalStructure.topSecurityTurnoverContribution) }}</dd></div>
          <div><dt>扩散比例</dt><dd>{{ formatRatio(candidate.internalStructure.diffusionRatio) }}</dd></div>
          <div><dt>成交排名靠前</dt><dd>{{ topSecurityLabel(candidate.internalStructure.topByTurnover) }}</dd></div>
          <div><dt>涨幅排名靠前</dt><dd>{{ topSecurityLabel(candidate.internalStructure.topByReturn) }}</dd></div>
        </dl>
        <p v-else class="sector-structure-empty">内部结构事实不足，不自动推断角色。</p>
      </article>
    </div>
    <div v-else class="sector-analysis-notice warning">
      <CircleAlert :size="20" /><div><strong>没有 exact-date canonical 候选</strong><p>候选行业保持为空，下一交易日只验证数据或身份恢复。</p></div>
    </div>

    <div v-if="marketRiskVetoes.length || marketRisk.crowdingRisk != null" class="sector-market-risk">
      <strong>市场级集中度风险</strong>
      <span>{{ marketRisk.crowdingRisk === true ? '已触发' : marketRisk.crowdingRisk === false ? '未触发' : '证据不足' }}</span>
      <span v-if="typeof marketRisk.concentrationPercentile === 'number'">集中度 P{{ Math.round(marketRisk.concentrationPercentile * 100) }}</span>
      <span v-if="typeof marketRisk.breadthPercentile === 'number'">宽度 P{{ Math.round(marketRisk.breadthPercentile * 100) }}</span>
      <ul v-if="marketRiskVetoes.length"><li v-for="veto in marketRiskVetoes" :key="veto">{{ veto }}</li></ul>
    </div>
  </section>

  <section v-if="activeView === 'continuity' && analysis" class="panel sector-validation-panel" aria-labelledby="sector-validation-title">
    <div class="panel-heading">
      <div><span class="panel-kicker">唯一验证项</span><h2 id="sector-validation-title">下一交易日只验证一件事</h2></div>
      <span class="quality-badge" :class="analysis.validation.candidateIndustry ? 'ok' : 'missing'">恰好一条</span>
    </div>
    <div class="sector-validation-text">
      <p>候选板块：<strong>{{ analysis.validation.candidateName || analysis.validation.candidateIndustry || '无 canonical 候选' }}</strong>；阶段：<strong>{{ stageLabel(analysis.validation.stage) }}</strong>。</p>
      <p>持续性证据：{{ analysis.validation.persistenceEvidence }}；宽度证据：{{ analysis.validation.breadthEvidence }}；成交证据：{{ analysis.validation.turnoverEvidence }}；内部结构：{{ analysis.validation.internalStructure }}。</p>
      <blockquote>下一交易日只验证：分歧后{{ analysis.validation.target }}能否承接。</blockquote>
      <div><span>确认条件</span><strong>{{ analysis.validation.confirmationCondition }}</strong></div>
      <div><span>失效条件</span><strong>{{ analysis.validation.invalidationCondition }}</strong></div>
    </div>
  </section>

</template>
