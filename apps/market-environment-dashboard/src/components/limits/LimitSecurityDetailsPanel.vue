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
}>()

type DetailGroupKey = keyof LimitSecurityDetails

const PAGE_SIZE = 20
const groups: Array<{ key: DetailGroupKey; label: string }> = [
  { key: 'limitUp', label: '涨停' },
  { key: 'limitDown', label: '跌停' },
  { key: 'failedLimitUp', label: '炸板' },
  { key: 'promoted', label: '晋级' },
]

const activeGroup = ref<DetailGroupKey>('limitUp')
const query = ref('')
const page = ref(1)

const emptyQuality: MetricQuality = { status: 'insufficient', reason: '未提供该组明细' }
const currentGroup = computed<LimitSecurityDetailGroup>(() => props.details?.[activeGroup.value] ?? {
  total: null,
  rows: [],
  quality: emptyQuality,
})
const filteredRows = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  if (!keyword) return currentGroup.value.rows
  return currentGroup.value.rows.filter((row) => [row.thscode, row.code, row.name]
    .some((value) => value?.toLocaleLowerCase().includes(keyword)))
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / PAGE_SIZE)))
const visibleRows = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return filteredRows.value.slice(start, start + PAGE_SIZE)
})

watch([activeGroup, query, () => props.details], () => {
  page.value = 1
})

function selectGroup(key: DetailGroupKey): void {
  activeGroup.value = key
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
            :aria-selected="activeGroup === group.key"
            :class="{ active: activeGroup === group.key }"
            @click="selectGroup(group.key)"
          >
            {{ group.label }}
            <span>{{ formatValue(details?.[group.key]?.total) }}</span>
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
        <strong>{{ query.trim() ? '没有匹配的证券' : '该组明细不足' }}</strong>
        <p>{{ query.trim() ? '请调整证券代码或名称关键词。' : '缺失值不会用其他集合或日期的数据补齐。' }}</p>
      </div>

      <div class="limit-security-pagination" aria-label="证券明细分页">
        <span>第 {{ page }} / {{ pageCount }} 页 · 每页 {{ PAGE_SIZE }} 行</span>
        <div>
          <button type="button" :disabled="page <= 1" aria-label="上一页" title="上一页" @click="page -= 1"><ChevronLeft :size="17" /></button>
          <button type="button" :disabled="page >= pageCount" aria-label="下一页" title="下一页" @click="page += 1"><ChevronRight :size="17" /></button>
        </div>
      </div>
    </div>
  </details>
</template>
