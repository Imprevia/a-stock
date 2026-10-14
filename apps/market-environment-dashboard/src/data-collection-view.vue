<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Database,
  RefreshCw,
  RotateCcw,
} from 'lucide-vue-next'
import {
  fetchCollectionStatus,
  pollCollectionRun,
  startCollectionRun,
} from './collection-api'
import type {
  CollectionDataset,
  CollectionRun,
  CollectionStatusResponse,
  DatasetCollectionStatus,
} from './collection-api'
import {
  STATUS_LABELS,
  attemptLabel,
  availabilityLabel,
  canCollectAll,
  canRetryDataset,
  collectionDiagnosticDetails,
  getCollectionStatusRequestDate,
  isRunActive,
  resolveCollectionSelectedDate,
  statusTone,
  toggleCoreExpansion,
} from './collection-view-model'
import { formatLocalDate } from './date-util'
import { formatDateTime, formatDateTimeTitle, MARKET_TIME_ZONE } from './timezone'

const DATASET_LABELS: Record<CollectionDataset, string> = {
  core: '核心指数',
  breadth: '市场广度',
  limits: '涨跌停生态',
  'industry-ranking': 'THS 分类排名',
  'sector-turnover': 'THS 板块量价',
  'sector-breadth': 'THS 板块宽度',
  activeDirection: '容量方向',
}
const SECTOR_DATASETS = new Set<CollectionDataset>(['industry-ranking', 'sector-turnover', 'sector-breadth'])
const selectedDate = ref('')
const dateInitialized = ref(false)
const status = ref<CollectionStatusResponse | null>(null)
const activeRun = ref<CollectionRun | null>(null)
const loading = ref(false)
const error = ref('')
const expandedCore = ref(false)
const expandedLimits = ref(false)
let requestSequence = 0
let runSequence = 0

const completedProgress = computed(() => {
  if (!activeRun.value) return ''
  return `${activeRun.value.completedTasks} / ${activeRun.value.totalTasks}`
})
const fullCollectionAllowed = computed(() => (
  status.value
    ? canCollectAll(status.value.manualRefreshEnabled, status.value.datasets, activeRun.value)
    : false
))
const sectorAnalysisReadiness = computed(() => status.value?.sectorAnalysis ?? null)
const thsOperations = computed(() => status.value?.operations ?? [])

function formatDuration(value: number | null | undefined) {
  if (value == null) return '--'
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`
}

async function loadStatus() {
  const requestId = ++requestSequence
  loading.value = true
  error.value = ''
  try {
    const requestedDate = getCollectionStatusRequestDate(selectedDate.value, dateInitialized.value)
    const nextStatus = await fetchCollectionStatus(requestedDate)
    if (requestId !== requestSequence) return
    selectedDate.value = resolveCollectionSelectedDate(
      selectedDate.value,
      dateInitialized.value,
      nextStatus.asOf,
    )
    dateInitialized.value = true
    status.value = nextStatus
  } catch (cause) {
    if (requestId !== requestSequence) return
    error.value = cause instanceof Error ? cause.message : '采集状态读取失败'
  } finally {
    if (requestId === requestSequence) loading.value = false
  }
}

async function collectDatasets(datasets?: CollectionDataset[]) {
  const currentRunSequence = ++runSequence
  error.value = ''
  try {
    const run = await startCollectionRun(selectedDate.value, datasets)
    if (currentRunSequence !== runSequence) return
    activeRun.value = run
    const completed = await pollCollectionRun(run.runId, {
      isCurrent: () => currentRunSequence === runSequence,
    })
    if (!completed || currentRunSequence !== runSequence) return
    activeRun.value = completed
    await loadStatus()
  } catch (cause) {
    if (currentRunSequence !== runSequence) return
    error.value = cause instanceof Error ? cause.message : '数据采集失败'
  }
}

function handleDateChange() {
  ++runSequence
  dateInitialized.value = true
  activeRun.value = null
  void loadStatus()
}

function retryDataset(item: DatasetCollectionStatus) {
  if (!status.value || !canRetryDataset(status.value.manualRefreshEnabled, item, activeRun.value)) return
  void collectDatasets([item.dataset])
}

function toggleLimitsExpansion() {
  expandedLimits.value = !expandedLimits.value
}

function limitsDetail(item: DatasetCollectionStatus) {
  return item.detail ?? item.latestAttempt
}

function qualityLabel(value?: string | null) {
  return ({ ok: '正常', partial: '部分覆盖', fallback: '降级来源', 'fallback-derived': '本地派生降级', degraded: '降级', insufficient: '数据不足', failed: '失败' } as Record<string, string>)[value ?? ''] ?? '数据不足'
}

function collectionQuality(item: DatasetCollectionStatus) {
  const quality = item.quality as {
    status?: string
    rankingMethod?: string
    industryMappingCoverage?: number
    catalogRevisionId?: string
    catalogRevision?: string
    sourceRevision?: string
    coverage?: number
    dependency?: string
  } | null | undefined
  if (!quality) return null
  if (SECTOR_DATASETS.has(item.dataset)) {
    const details = [quality.status ? qualityLabel(quality.status) : null]
    const revision = item.catalogRevisionId
      ?? quality.catalogRevisionId
      ?? quality.catalogRevision
      ?? quality.sourceRevision
    if (revision) details.push(`版本 ${revision}`)
    if (quality.coverage != null) details.push(`覆盖 ${(quality.coverage * 100).toFixed(0)}%`)
    if (quality.dependency) details.push(`依赖 ${quality.dependency}`)
    return details.join(' · ')
  }
  if (item.dataset !== 'activeDirection') return null
  const details = [quality.status ? qualityLabel(quality.status) : null]
  if (quality.rankingMethod) details.push('本地成交额排序')
  if (quality.industryMappingCoverage != null) details.push(`行业映射 ${(quality.industryMappingCoverage * 100).toFixed(0)}%`)
  return details.filter(Boolean).join(' · ')
}

function collectionWarning(item: DatasetCollectionStatus) {
  const warnings = [item.latestAttempt?.warning, item.refreshWarning, item.restriction]
  return [...new Set(warnings.filter((warning): warning is string => Boolean(warning)))].join('；')
}

function operationStatusLabel(value?: string | null) {
  return ({
    queued: '等待执行', running: '执行中', success: '成功', partial: '部分完成',
    failed: '失败', conflict: '存在冲突', blocked: '依赖阻塞',
  } as Record<string, string>)[value ?? ''] ?? value ?? '未知'
}

function readinessStatusLabel(value?: string | null) {
  return ({
    ok: '已就绪',
    partial: '部分覆盖',
    degraded: '降级保留',
    'reduced-confidence': '低置信度',
    insufficient: '数据不足',
    missing: '缺失',
    failed: '失败',
  } as Record<string, string>)[value ?? ''] ?? value ?? '数据不足'
}

function readinessAttemptLabel(value?: string | null) {
  return ({
    success: '成功',
    partial: '部分完成',
    'failed-retained': '失败，保留旧结果',
    'failed-missing': '失败，缺少结果',
    insufficient: '数据不足',
  } as Record<string, string>)[value ?? ''] ?? value ?? '尚无尝试'
}

function formatReadinessCoverage(value: number | null | undefined) {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`
}

function readinessVersionEntries() {
  const versions = sectorAnalysisReadiness.value?.versions
  if (!versions) return []
  const labels: Record<string, string> = {
    data: '数据', classification: '分类', membership: '成员', universe: '范围',
    adjustment: '复权', benchmark: '基准', calculation: '计算',
  }
  return Object.entries(versions)
    .filter(([, value]) => Boolean(value))
    .map(([key, value]) => `${labels[key] ?? key} ${value}`)
}

onMounted(loadStatus)
</script>

<template>
  <section class="collection-page" aria-labelledby="collection-title">
    <header class="collection-header">
      <div>
        <span>数据管理</span>
        <h1 id="collection-title">市场数据采集</h1>
      </div>
      <div class="collection-controls">
        <label class="date-field collection-date-field">
          <span class="sr-only">选择采集日期</span>
          <input
            v-model="selectedDate"
            type="date"
            :max="formatLocalDate(new Date())"
            :disabled="isRunActive(activeRun)"
            @change="handleDateChange"
          />
        </label>
        <button class="icon-button" type="button" :disabled="loading" aria-label="刷新采集状态" title="刷新采集状态" @click="loadStatus">
          <RefreshCw :size="17" :class="{ spin: loading }" />
        </button>
        <button class="command-button" type="button" :disabled="!fullCollectionAllowed" @click="collectDatasets()">
          <RotateCcw :size="16" />
          <span>全部重新采集</span>
        </button>
      </div>
    </header>

    <div v-if="activeRun" class="collection-progress" :class="activeRun.status">
      <div><span>当前批次</span><strong>{{ activeRun.status === 'collecting' ? '采集中' : activeRun.status }}</strong></div>
      <div><span>进度</span><strong>{{ completedProgress }}</strong></div>
      <div class="progress-track" aria-hidden="true"><i :style="{ width: `${activeRun.totalTasks ? activeRun.completedTasks / activeRun.totalTasks * 100 : 0}%` }" /></div>
    </div>

    <section v-if="sectorAnalysisReadiness" class="sector-readiness-panel" aria-labelledby="sector-readiness-title">
      <div class="sector-readiness-heading">
        <div><span>独立历史分析</span><h2 id="sector-readiness-title">Sector continuity readiness</h2></div>
        <span class="collection-badge" :class="sectorAnalysisReadiness.status === 'ok' ? 'success' : sectorAnalysisReadiness.status === 'failed' ? 'failed' : 'warning'">{{ readinessStatusLabel(sectorAnalysisReadiness.status) }}</span>
      </div>
      <p class="sector-readiness-readonly">只读状态 · 申万历史回填需单独授权，不属于七个每日数据集，也不会由本页触发。</p>
      <div class="sector-readiness-grid">
        <div><span>分析日期</span><strong>{{ sectorAnalysisReadiness.asOf }}</strong></div>
        <div><span>历史覆盖</span><strong>{{ sectorAnalysisReadiness.availableHistory }} / {{ sectorAnalysisReadiness.requiredHistory }}（{{ formatReadinessCoverage(sectorAnalysisReadiness.coverage) }}）</strong></div>
        <div><span>缺失交易日</span><strong>{{ sectorAnalysisReadiness.missingSessions.length ? sectorAnalysisReadiness.missingSessions.join('、') : '无' }}</strong></div>
        <div><span>最近尝试</span><strong>{{ readinessAttemptLabel(sectorAnalysisReadiness.latestAttempt?.status) }}</strong></div>
        <div><span>重试资格</span><strong>{{ sectorAnalysisReadiness.retryEligible ? '可由授权流程处理' : '不可重试' }}</strong></div>
        <div v-if="sectorAnalysisReadiness.backfill"><span>回填进度</span><strong>{{ sectorAnalysisReadiness.backfill.completedSessions ?? 0 }} / {{ sectorAnalysisReadiness.backfill.totalSessions ?? '--' }}（{{ sectorAnalysisReadiness.backfill.status || '--' }}）</strong></div>
      </div>
      <div v-if="readinessVersionEntries().length" class="sector-readiness-versions">
        <span v-for="entry in readinessVersionEntries()" :key="entry">{{ entry }}</span>
      </div>
      <ul v-if="sectorAnalysisReadiness.warnings.length || sectorAnalysisReadiness.latestAttempt?.warning" class="sector-readiness-warnings">
        <li v-for="warning in [...sectorAnalysisReadiness.warnings, sectorAnalysisReadiness.latestAttempt?.warning].filter(Boolean)" :key="warning">{{ warning }}</li>
      </ul>
    </section>

    <section v-if="thsOperations.length" class="ths-operation-panel" aria-labelledby="ths-operation-title">
      <div class="sector-readiness-heading">
        <div><span>显式操作</span><h2 id="ths-operation-title">THS 目录、历史与成员事实进度</h2></div>
        <span class="collection-badge warning">{{ thsOperations.length }} 项</span>
      </div>
      <div class="ths-operation-list">
        <article v-for="operation in thsOperations" :key="operation.runId">
          <div><strong>{{ operation.kind }}</strong><span>{{ operation.runId }}</span></div>
          <span class="collection-badge" :class="['success'].includes(operation.status) ? 'success' : ['failed'].includes(operation.status) ? 'failed' : 'warning'">{{ operationStatusLabel(operation.status) }}</span>
          <div class="ths-operation-progress">
            <span>{{ operation.progress.completed }} / {{ operation.progress.total }}</span>
            <span>失败 {{ operation.progress.failed }}</span>
            <span>冲突 {{ operation.progress.conflicts }}</span>
          </div>
          <p v-if="operation.warning">{{ operation.warning }}</p>
        </article>
      </div>
    </section>

    <section v-if="error" class="state-panel error-panel collection-error" role="alert">
      <CircleAlert :size="20" />
      <div><strong>数据管理暂时不可用</strong><p>{{ error }}</p></div>
      <button class="text-button" type="button" @click="loadStatus">重试</button>
    </section>

    <section v-if="!status && loading" class="state-panel"><div class="loader" /><span>正在读取本地采集状态…</span></section>
    <section v-else-if="status" class="collection-table-panel">
      <div class="collection-summary">
        <div><Database :size="17" /><span>{{ status.datasets.filter((item) => item.available).length }} / {{ status.datasets.length }} 类数据可用</span></div>
        <span v-if="!status.manualRefreshEnabled" class="manual-disabled">手工采集未启用</span>
      </div>
      <div class="collection-table-wrap">
        <table class="collection-table">
          <thead><tr><th>数据集</th><th>可用状态</th><th>最近尝试</th><th>来源 / 样本</th><th>最近成功</th><th>耗时</th><th>提示</th><th>操作</th></tr></thead>
          <tbody>
            <template v-for="item in status.datasets" :key="item.dataset">
              <tr :class="{ 'sector-dataset-row': SECTOR_DATASETS.has(item.dataset) }">
                <td data-label="数据集">
                  <button v-if="item.dataset === 'core'" class="expand-button" type="button" :aria-expanded="expandedCore" @click="expandedCore = toggleCoreExpansion(expandedCore)">
                    <ChevronDown v-if="expandedCore" :size="16" /><ChevronRight v-else :size="16" />
                    <strong>{{ DATASET_LABELS[item.dataset] }}</strong>
                  </button>
                  <button v-else-if="item.dataset === 'limits'" class="expand-button" type="button" :aria-expanded="expandedLimits" aria-label="展开涨跌停生态" @click="toggleLimitsExpansion">
                    <ChevronDown v-if="expandedLimits" :size="16" /><ChevronRight v-else :size="16" />
                    <strong>{{ DATASET_LABELS[item.dataset] }}</strong>
                  </button>
                  <strong v-else>{{ DATASET_LABELS[item.dataset] }}</strong>
                  <span>{{ item.dataset }}</span>
                </td>
                <td data-label="可用状态"><span class="collection-badge" :class="item.available ? 'success' : 'failed'">{{ availabilityLabel(item) }}</span></td>
                <td data-label="最近尝试"><span class="collection-badge" :class="statusTone(item.latestAttempt?.status)">{{ attemptLabel(item) }}</span><time v-if="item.latestAttempt?.completedAt || item.latestAttempt?.startedAt || item.latestAttempt?.queuedAt" class="collection-attempt-time" :datetime="item.latestAttempt.completedAt || item.latestAttempt.startedAt || item.latestAttempt.queuedAt || undefined" :title="formatDateTimeTitle(item.latestAttempt.completedAt || item.latestAttempt.startedAt || item.latestAttempt.queuedAt)">{{ formatDateTime(item.latestAttempt.completedAt || item.latestAttempt.startedAt || item.latestAttempt.queuedAt, { precision: 'second', timeZone: MARKET_TIME_ZONE }) }}</time></td>
                <td data-label="来源 / 样本"><strong>{{ item.source === 'none' ? '--' : item.source }}</strong><span>{{ item.observations.toLocaleString('zh-CN') }} 条</span><small v-if="collectionQuality(item)">{{ collectionQuality(item) }}</small></td>
                <td data-label="最近成功"><span :title="formatDateTimeTitle(item.lastSuccessAt)">{{ formatDateTime(item.lastSuccessAt, { precision: 'second', timeZone: MARKET_TIME_ZONE }) }}</span></td>
                <td data-label="耗时">{{ formatDuration(item.latestAttempt?.durationMs) }}</td>
                <td data-label="提示" class="collection-warning"><span class="collection-warning-text" :title="collectionWarning(item) || undefined">{{ collectionWarning(item) || '--' }}</span></td>
                <td data-label="操作">
                  <button
                    class="retry-button"
                    type="button"
                    :disabled="!canRetryDataset(status.manualRefreshEnabled, item, activeRun)"
                    :title="item.restriction || undefined"
                    @click="retryDataset(item)"
                  ><RotateCcw :size="15" /><span>重新采集</span></button>
                </td>
              </tr>
              <tr v-if="collectionDiagnosticDetails(item).length" class="ths-diagnostic-row">
                <td colspan="8">
                  <div class="ths-diagnostic-details" role="status" :aria-label="`${DATASET_LABELS[item.dataset]}诊断详情`">
                    <strong>THS 诊断</strong>
                    <span v-for="detail in collectionDiagnosticDetails(item)" :key="detail">{{ detail }}</span>
                  </div>
                </td>
              </tr>
              <tr v-if="item.dataset === 'core' && expandedCore" class="core-detail-row">
                <td colspan="8">
                  <div v-if="item.coreIndices.length" class="core-index-list">
                    <div v-for="index in item.coreIndices" :key="index.code">
                      <strong>{{ index.name }}</strong><span>{{ index.code }}</span>
                      <span class="collection-badge" :class="statusTone(index.status)">{{ STATUS_LABELS[index.status] }}</span>
                      <span>{{ index.source }}</span><span>{{ formatDuration(index.durationMs) }}</span><em>{{ index.warning || '--' }}</em>
                    </div>
                  </div>
                  <div v-else class="core-empty">尚无核心指数采集明细</div>
                </td>
              </tr>
              <tr v-if="item.dataset === 'limits' && expandedLimits" class="core-detail-row limits-detail-row">
                <td colspan="8">
                  <div class="limits-collection-detail">
                    <div><span>当前样本日期</span><strong>{{ limitsDetail(item)?.sampleAsOf || '--' }}</strong></div>
                    <div><span>前一交易日</span><strong>{{ limitsDetail(item)?.previousAsOf || '--' }}</strong></div>
                    <div><span>排除样本数</span><strong>{{ limitsDetail(item)?.excludedCount?.toLocaleString('zh-CN') ?? '--' }}</strong></div>
                    <div><span>晋级质量</span><strong>{{ qualityLabel(limitsDetail(item)?.promotionQuality) }}</strong></div>
                    <div class="limits-collection-dependency"><span>晋级依赖</span><strong>{{ limitsDetail(item)?.promotionDependency || (limitsDetail(item)?.promotionRequired === false ? '不需要前一交易日样本' : '需要精确相邻交易日和规范证券身份') }}</strong></div>
                    <div v-if="limitsDetail(item)?.warnings?.length" class="limits-collection-warnings"><span>警告</span><strong>{{ limitsDetail(item)?.warnings?.join('；') }}</strong></div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>
