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
  getCollectionStatusRequestDate,
  isRunActive,
  resolveCollectionSelectedDate,
  statusTone,
  toggleCoreExpansion,
} from './collection-view-model'
import { formatLocalDate } from './date-util'

const DATASET_LABELS: Record<CollectionDataset, string> = {
  core: '核心指数',
  breadth: '市场广度',
  limits: '涨跌停生态',
  sectors: '行业板块',
  activeDirection: '容量方向',
}
const selectedDate = ref('')
const dateInitialized = ref(false)
const status = ref<CollectionStatusResponse | null>(null)
const activeRun = ref<CollectionRun | null>(null)
const loading = ref(false)
const error = ref('')
const expandedCore = ref(false)
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

function formatDateTime(value: string | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

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
              <tr>
                <td data-label="数据集">
                  <button v-if="item.dataset === 'core'" class="expand-button" type="button" :aria-expanded="expandedCore" @click="expandedCore = toggleCoreExpansion(expandedCore)">
                    <ChevronDown v-if="expandedCore" :size="16" /><ChevronRight v-else :size="16" />
                    <strong>{{ DATASET_LABELS[item.dataset] }}</strong>
                  </button>
                  <strong v-else>{{ DATASET_LABELS[item.dataset] }}</strong>
                  <span>{{ item.dataset }}</span>
                </td>
                <td data-label="可用状态"><span class="collection-badge" :class="item.available ? 'success' : 'failed'">{{ availabilityLabel(item) }}</span></td>
                <td data-label="最近尝试"><span class="collection-badge" :class="statusTone(item.latestAttempt?.status)">{{ attemptLabel(item) }}</span></td>
                <td data-label="来源 / 样本"><strong>{{ item.source === 'none' ? '--' : item.source }}</strong><span>{{ item.observations.toLocaleString('zh-CN') }} 条</span></td>
                <td data-label="最近成功">{{ formatDateTime(item.lastSuccessAt) }}</td>
                <td data-label="耗时">{{ formatDuration(item.latestAttempt?.durationMs) }}</td>
                <td data-label="提示" class="collection-warning"><span class="collection-warning-text" :title="item.latestAttempt?.warning || item.refreshWarning || item.restriction || undefined">{{ item.latestAttempt?.warning || item.refreshWarning || item.restriction || '--' }}</span></td>
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
            </template>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>
