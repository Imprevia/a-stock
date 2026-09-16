<script setup lang="ts">
/**
 * Document04TierRiskPage — 第 04 章 高、中、低位亏钱效应。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '04'"`
 * block in Phase B-04 of frontend-component-split. Reads only from
 * `useMarketStore()` + `useDocumentContext()`. Chapter 04 content comes
 * from the core payload's chapter01.tierRisk — no section prefetch
 * needed.
 */
import { ShieldAlert } from 'lucide-vue-next'
import { computed } from 'vue'

import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()

const tierRisk = computed(() => market.chapter?.tierRisk)
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="metric-grid four">
    <article class="metric-card"><span>高位风险</span><strong>{{ tierRisk?.high ?? '--' }}</strong></article>
    <article class="metric-card"><span>中位风险</span><strong>{{ tierRisk?.middle ?? '--' }}</strong></article>
    <article class="metric-card"><span>低位风险</span><strong>{{ tierRisk?.low ?? '--' }}</strong></article>
    <article class="metric-card"><span>修复率</span><strong>{{ tierRisk?.repairRatio == null ? '--' : `${(tierRisk.repairRatio * 100).toFixed(0)}%` }}</strong></article>
  </section>

  <section class="panel analysis-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">分层风险</span><h2>{{ tierRisk?.state || '数据不足' }}</h2></div>
      <span class="quality-badge" :class="ctx.qualityTone(tierRisk?.quality)">{{ ctx.qualityLabel(tierRisk?.quality) }}</span>
    </div>
    <div class="empty-evidence">
      <ShieldAlert :size="24" />
      <strong>分层样本必须独立计算</strong>
      <p>{{ tierRisk?.quality.warning || '最高板、核心、中位接力、首板与失败样本尚未形成可追溯数据集，不按安全状态处理。' }}</p>
    </div>
  </section>
</template>