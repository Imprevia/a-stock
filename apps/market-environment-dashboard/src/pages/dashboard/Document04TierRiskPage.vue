<script setup lang="ts">
/**
 * Document04TierRiskPage — 第 04 章 高、中、低位亏钱效应。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '04'"`
 * block in Phase B-04 of frontend-component-split. Chapter 04 reuses the
 * limits section's risk-tier stratifications and failure-repair evidence.
 */
import { ShieldAlert } from 'lucide-vue-next'
import { computed } from 'vue'

import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()

const riskTiers = computed(() => (market.limits?.stratifications ?? [])
  .filter((row) => row.dimension === 'risk_tier'))
const repairEvidence = computed(() => (market.limits?.riskEvidence ?? [])
  .find((row) => row.code === 'failure-repair'))
const hasEvidence = computed(() => riskTiers.value.length > 0 || repairEvidence.value != null)

function tier(key: string) {
  return riskTiers.value.find((row) => row.key === key)
}

function formatCount(value: number | null | undefined): string {
  return value == null ? '--' : value.toLocaleString('zh-CN')
}

function formatRepair(value: string | number | null | undefined): string {
  if (value == null || value === '') return '--'
  return typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : value
}

function qualityStatus(key: string): string | undefined {
  return key === 'failure-repair' ? repairEvidence.value?.quality?.status : tier(key)?.quality?.status
}

function evidenceDetail(key: string): string {
  const quality = key === 'failure-repair' ? repairEvidence.value?.quality : tier(key)?.quality
  const evidence = key === 'failure-repair' ? repairEvidence.value?.evidence ?? [] : []
  const evidenceAsOf = key === 'failure-repair' ? repairEvidence.value?.asOf : quality?.asOf
  const metadata = [
    evidenceAsOf ? `样本日期 ${evidenceAsOf}` : null,
    quality?.source ? `来源 ${quality.source}` : null,
    quality?.observations != null ? `观察 ${quality.observations}` : null,
  ]
  return [...evidence, quality?.reason, ...(quality?.warnings ?? []), ...metadata].filter(Boolean).join('；') || '该项暂无可追溯证据'
}
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="metric-grid four">
    <article class="metric-card tier-risk-card">
      <span>高位样本</span><strong>{{ formatCount(tier('high')?.count) }}</strong>
      <small :class="ctx.metricQualityTone(qualityStatus('high'))">{{ ctx.metricQualityLabel(qualityStatus('high')) }}</small>
    </article>
    <article class="metric-card tier-risk-card">
      <span>中位样本</span><strong>{{ formatCount(tier('middle')?.count) }}</strong>
      <small :class="ctx.metricQualityTone(qualityStatus('middle'))">{{ ctx.metricQualityLabel(qualityStatus('middle')) }}</small>
    </article>
    <article class="metric-card tier-risk-card">
      <span>低位样本</span><strong>{{ formatCount(tier('low')?.count) }}</strong>
      <small :class="ctx.metricQualityTone(qualityStatus('low'))">{{ ctx.metricQualityLabel(qualityStatus('low')) }}</small>
    </article>
    <article class="metric-card tier-risk-card">
      <span>炸板修复率</span><strong>{{ formatRepair(repairEvidence?.value) }}</strong>
      <small :class="ctx.metricQualityTone(qualityStatus('failure-repair'))">{{ ctx.metricQualityLabel(qualityStatus('failure-repair')) }}</small>
    </article>
  </section>

  <section class="panel analysis-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">分层风险</span><h2>高、中、低位与炸板修复证据</h2></div>
    </div>
    <div v-if="hasEvidence" class="tier-risk-evidence-list">
      <div v-for="item in [
        { key: 'high', label: '高位样本', value: formatCount(tier('high')?.count) },
        { key: 'middle', label: '中位样本', value: formatCount(tier('middle')?.count) },
        { key: 'low', label: '低位样本', value: formatCount(tier('low')?.count) },
        { key: 'failure-repair', label: '炸板修复率', value: formatRepair(repairEvidence?.value) },
      ]" :key="item.key">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <em :class="ctx.metricQualityTone(qualityStatus(item.key))">{{ ctx.metricQualityLabel(qualityStatus(item.key)) }}</em>
        <p>{{ evidenceDetail(item.key) }}</p>
      </div>
    </div>
    <div v-else class="empty-evidence">
      <ShieldAlert :size="24" />
      <strong>分层样本必须独立计算</strong>
      <p>高、中、低位样本与炸板修复证据尚未形成可追溯数据，不按安全状态处理。</p>
    </div>
  </section>
</template>
