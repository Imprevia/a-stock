<script setup lang="ts">
import { ChevronDown, ChevronLeft, ChevronRight, ListFilter, Search } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

import type {
  LimitSecurityDetailGroup,
  LimitSecurityDetailRow,
  LimitSecurityDetails,
  MetricQuality,
} from '../../types'

const props = defineProps<{
  details?: LimitSecurityDetails | null
  poolType?: LimitPoolType | null
  rows?: LimitSecurityDetailRow[] | null
  quality?: MetricQuality | null
  hasMore?: boolean
  page?: number
  loading?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  poolChange: [poolType: LimitPoolType]
  pageChange: [direction: 'next' | 'previous']
}>()

type DetailGroupKey = keyof LimitSecurityDetails
type LimitPoolType = 'limit_up' | 'limit_down' | 'failed_limit_up' | 'promoted'

const PAGE_SIZE = 20
const groups: Array<{ key: DetailGroupKey; poolType: LimitPoolType; label: string }> = [
  { key: 'limitUp', poolType: 'limit_up', label: '涨停' },
  { key: 'limitDown', poolType: 'limit_down', label: '跌停' },
  { key: 'failedLimitUp', poolType: 'failed_limit_up', label: '炸板' },
  { key: 'promoted', poolType: 'promoted', label: '晋级' },
]

const activeGroup = ref<DetailGroupKey>('limitUp')
const query = ref('')
const legacyPage = ref(1)

const emptyQuality: MetricQuality = { status: 'insufficient', reason: '未提供该组明细' }
const controlled = computed(() => props.poolType != null)
const selectedGroup = computed<DetailGroupKey>(() => {
  if (!controlled.value) return activeGroup.value
  return groups.find((group) => group.poolType === props.poolType)?.key ?? 'limitUp'
})
const currentGroup = computed<LimitSecurityDetailGroup>(() => props.details?.[activeGroup.value] ?? {
  total: controlled.value ? props.quality?.observations ?? null : null,
  rows: controlled.value ? props.rows ?? [] : [],
  quality: controlled.value ? props.quality ?? emptyQuality : emptyQuality,
})
const filteredRows = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  if (!keyword) return currentGroup.value.rows
  return currentGroup.value.rows.filter((row) => [row.thscode, row.code, row.name]
    .some((value) => value?.toLocaleLowerCase().includes(keyword)))
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / PAGE_SIZE)))
const visibleRows = computed(() => {
  if (controlled.value) return filteredRows.value
  const start = (legacyPage.value - 1) * PAGE_SIZE
  return filteredRows.value.slice(start, start + PAGE_SIZE)
})
const displayedPage = computed(() => controlled.value ? Math.max(1, props.page ?? 1) : legacyPage.value)

watch([activeGroup, query, () => props.details], () => {
  if (!controlled.value) legacyPage.value = 1
})

function selectGroup(key: DetailGroupKey, poolType: LimitPoolType): void {
  query.value = ''
  if (controlled.value) {
    if (poolType !== props.poolType) emit('poolChange', poolType)
    return
  }
  activeGroup.value = key
}

function changePage(direction: 'next' | 'previous'): void {
  if (controlled.value) {
    emit('pageChange', direction)
    return
  }
  legacyPage.value += direction === 'next' ? 1 : -1
}

function formatValue(value: string | number | null | undefined): string {
  if (value == null || value === '') return '--'
  return typeof value === 'number' ? value.toLocaleString('zh-CN') : value
}

function formatPercent(value: number | null | undefined): string {
  return value == null ? '--' : `${value.toFixed(2)}%`
}

function qualityLabel(status: string | null | undefined): string {
  return ({
    ok: '正常',
    degraded: '降级',
    fallback: '降级来源',
    partial: '部分覆盖',
    insufficient: '数据不足',
    missing: '缺失',
    failed: '失败',
  } as Record<string, string>)[status ?? '']
    ?? status
    ?? '数据不足'
}

function qualityTone(status: string | null | undefined): string {
  if (status === 'ok') return 'ok'
  if (status === 'degraded') return 'fallback'
  return 'missing'
}

function rowIdentity(row: LimitSecurityDetailRow): string {
  return row.thscode || row.securityId || `${row.exchange}:${row.code}`
}

function rowAttributes(row: LimitSecurityDetailRow): string {
  const values: string[] = []
  if (row.isSt === true) values.push('ST')
  if (row.isNew === true) values.push('新股')
  if (!values.length && row.isSt === false && row.isNew === false) values.push('普通')
  return values.join(' / ') || '--'
}
</script>

<template>
  <details class="panel limit-security-details">
    <summary>
      <span class="limit-security-summary-title"><ListFilter :size="18" />证券明细</span>
      <span class="limit-security-summary-meta">涨停 / 跌停 / 炸板 / 晋级<ChevronDown :size="17" /></span>
    </summary>

    <div class="limit-security-body">
      <div class="limit-security-toolbar">
        <div class="limit-security-tabs" role="tablist" aria-label="证券明细集合">
          <button
            v-for="group in groups"
            :key="group.key"
            type="button"
            role="tab"
            :aria-selected="selectedGroup === group.key"
            :class="{ active: selectedGroup === group.key }"
            :disabled="loading"
            @click="selectGroup(group.key, group.poolType)"
          >
            {{ group.label }}
            <span>{{ formatValue(controlled && selectedGroup === group.key ? currentGroup.total : details?.[group.key]?.total) }}</span>
          </button>
        </div>
        <label class="limit-security-search">
          <Search :size="16" />
          <span class="sr-only">搜索证券代码或名称</span>
          <input v-model="query" type="search" placeholder="搜索代码或名称" />
        </label>
      </div>

      <div class="limit-security-meta">
        <span>集合总数 <strong>{{ formatValue(currentGroup.total) }}</strong></span>
        <span>当前匹配 <strong>{{ filteredRows.length }}</strong></span>
        <span>质量 <strong :class="qualityTone(currentGroup.quality.status)">{{ qualityLabel(currentGroup.quality.status) }}</strong></span>
        <span>来源 <strong>{{ currentGroup.quality.source || '--' }}</strong></span>
        <span>样本日期 <strong>{{ currentGroup.quality.asOf || '--' }}</strong></span>
        <span>观察数 <strong>{{ formatValue(currentGroup.quality.observations) }}</strong></span>
      </div>
      <p v-if="currentGroup.quality.reason" class="limit-security-group-warning">{{ currentGroup.quality.reason }}</p>
      <ul v-if="currentGroup.quality.warnings?.length" class="limit-security-group-warnings">
        <li v-for="warning in currentGroup.quality.warnings" :key="warning">{{ warning }}</li>
      </ul>
      <p v-if="error" class="limit-security-group-warning" role="alert">{{ error }}</p>

      <div v-if="visibleRows.length" class="table-scroll limit-security-table-scroll">
        <table class="limits-table limit-security-table">
          <thead>
            <tr>
              <th>证券</th><th>名称</th><th>市场属性</th><th>收盘</th><th>涨跌幅</th><th>连板</th>
              <th>事件时间</th><th>涨停原因</th><th>封单额</th><th>开板</th><th>换手率</th><th>成交额</th><th>来源与质量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in visibleRows" :key="rowIdentity(row)">
              <td><strong>{{ row.thscode || row.code || '--' }}</strong><small>{{ row.exchange || '--' }}</small></td>
              <td><strong>{{ row.name || '--' }}</strong><small>{{ row.listingDate || '--' }}</small></td>
              <td>{{ rowAttributes(row) }}</td>
              <td>{{ formatValue(row.closePrice) }}</td>
              <td>{{ formatPercent(row.changePct) }}</td>
              <td>{{ row.streakDays == null ? '--' : `${row.streakDays} 板` }}</td>
              <td><strong>{{ row.limitUpTime || row.firstLimitTime || '--' }}</strong><small>{{ row.lastLimitTime || '--' }}</small></td>
              <td>{{ row.limitUpReason || '--' }}</td>
              <td><strong>{{ formatValue(row.sealMoney) }}</strong><small>最高 {{ formatValue(row.maxSealMoney) }}</small></td>
              <td>{{ formatValue(row.openTimes) }}</td>
              <td>{{ formatPercent(row.turnoverRatioPct) }}</td>
              <td>{{ formatValue(row.turnover) }}</td>
              <td>
                <strong>{{ row.source || '--' }} · {{ qualityLabel(row.rowQuality) }}</strong>
                <small v-if="row.warnings?.length" class="row-warning">{{ row.warnings.join('；') }}</small>
                <small v-else>无行级警告</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-evidence compact limit-security-empty">
        <Search :size="22" />
        <strong>{{ loading ? '正在加载当前集合' : query.trim() ? '没有匹配的证券' : '该组明细不足' }}</strong>
        <p>{{ loading ? '仅请求当前选中的证券池。' : query.trim() ? '搜索仅过滤当前页，请调整证券代码或名称关键词。' : '缺失值不会用其他集合或日期的数据补齐。' }}</p>
      </div>

      <div class="limit-security-pagination" aria-label="证券明细分页">
        <span v-if="controlled">第 {{ displayedPage }} 页 · 当前页 {{ filteredRows.length }} 行</span>
        <span v-else>第 {{ displayedPage }} / {{ pageCount }} 页 · 每页 {{ PAGE_SIZE }} 行</span>
        <div>
          <button type="button" :disabled="loading || displayedPage <= 1" aria-label="上一页" title="上一页" @click="changePage('previous')"><ChevronLeft :size="17" /></button>
          <button type="button" :disabled="loading || (controlled ? !hasMore : displayedPage >= pageCount)" aria-label="下一页" title="下一页" @click="changePage('next')"><ChevronRight :size="17" /></button>
        </div>
      </div>
    </div>
  </details>
</template>
