<script setup lang="ts">
/**
 * Document05SectorsPage — 第 05 章 主线持续性和成交集中度（行业轮动）。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '05'"`
 * block in Phase B-05 of frontend-component-split. Data comes from the
 * core payload's chapter01.sectors — no section prefetch needed.
 */
import { BarChart3 } from 'lucide-vue-next'
import { computed } from 'vue'

import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'
import {
  sectorEnrichmentCoverage,
  sectorEnrichmentDateLabel,
  sectorEnrichmentFromQuality,
  sectorEnrichmentSourceLabel,
  sectorEnrichmentStatusLabel,
  sectorEnrichmentWarnings,
} from '../../sector-enrichment'

const market = useMarketStore()
const ctx = useDocumentContext()

const sectors = computed(() => market.chapter?.sectors)
const rows = computed(() => sectors.value?.rows ?? [])
const enrichment = computed(() => sectorEnrichmentFromQuality(sectors.value?.quality))
const enrichmentCoverage = computed(() => sectorEnrichmentCoverage(enrichment.value))
const enrichmentDate = computed(() => sectorEnrichmentDateLabel(enrichment.value))
const enrichmentWarnings = computed(() => sectorEnrichmentWarnings(enrichment.value))
const qualityWarnings = computed(() => [...new Set([
  sectors.value?.quality.warning,
  ...(sectors.value?.quality.warnings ?? []),
  ...enrichmentWarnings.value,
].filter((warning): warning is string => Boolean(warning)))])

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
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="panel table-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">行业轮动</span><h2>{{ sectors?.state || '板块证据' }}</h2></div>
      <span class="quality-badge" :class="ctx.qualityTone(sectors?.quality)">{{ ctx.qualityLabel(sectors?.quality) }}</span>
    </div>
    <div v-if="enrichment" class="sector-enrichment-band" aria-label="行业字段补充质量">
      <div class="sector-enrichment-heading">
        <strong>字段补充 · {{ sectorEnrichmentStatusLabel(enrichment.status) }}</strong>
        <span>{{ sectorEnrichmentSourceLabel(enrichment) }}</span>
      </div>
      <div v-if="enrichmentCoverage.length || enrichment.mappingRevision || enrichmentDate" class="sector-enrichment-meta">
        <span v-for="item in enrichmentCoverage" :key="item">{{ item }}</span>
        <span v-if="enrichment.mappingRevision">映射版本 {{ enrichment.mappingRevision }}</span>
        <span v-if="enrichmentDate">{{ enrichmentDate }}</span>
      </div>
      <ul v-if="enrichmentWarnings.length" class="sector-enrichment-warnings">
        <li v-for="warning in enrichmentWarnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>
    <div v-if="rows.length" class="table-scroll">
      <table class="sector-table">
        <thead><tr><th>板块</th><th>涨跌幅</th><th>上涨 / 下跌</th><th>主力净额</th><th>领涨股</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.code || row.name">
            <td><strong>{{ row.name }}</strong><span>{{ row.code || '' }}</span></td>
            <td :class="changeTone(row.changePct)">{{ formatPct(row.changePct) }}</td>
            <td>{{ formatCount(row.upCount) }} / {{ formatCount(row.downCount) }}</td>
            <td>{{ formatAmount(row.mainNet) }}</td>
            <td>{{ row.leader || '--' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty-evidence">
      <BarChart3 :size="24" />
      <strong>板块数据不足</strong>
      <p>{{ qualityWarnings.join('；') || '行业相对强度、成交持续性、板块宽度和集中度尚未返回。' }}</p>
    </div>
  </section>
</template>
