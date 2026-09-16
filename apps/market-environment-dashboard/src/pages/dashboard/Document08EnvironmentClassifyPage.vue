<script setup lang="ts">
/**
 * Document08EnvironmentClassifyPage — 第 08 章 如何归类市场环境。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '08'"`
 * block in Phase B-08 of frontend-component-split. Data comes from the
 * core payload's chapter01.assessment + coverage — no section prefetch
 * needed.
 */
import { Database as DatabaseIcon, TrendingUp } from 'lucide-vue-next'
import { computed } from 'vue'

import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()

const assessment = computed(() => market.assessment)
const coverage = computed(() => market.chapter?.coverage)
const evidence = computed(() => assessment.value?.evidence ?? [])
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="classification-layout">
    <article class="classification-main">
      <span>当前环境</span>
      <strong>{{ ctx.environmentLabel(assessment?.state) }}</strong>
      <p>置信度 {{ ctx.confidenceLabel(assessment?.confidence) }} · 规则覆盖 {{ coverage == null ? '--' : `${(coverage * 100).toFixed(0)}%` }}</p>
    </article>
    <article class="panel evidence-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">证据一致性</span><h2>风险优先分类</h2></div>
      </div>
      <div class="evidence-list">
        <div v-for="item in evidence" :key="item">
          <TrendingUp :size="16" />
          <span>{{ item }}</span>
        </div>
        <div v-if="!evidence.length" class="muted-row">
          <DatabaseIcon :size="16" />
          <span>有效证据链不足，暂不归类为趋势、轮动或退潮。</span>
        </div>
      </div>
    </article>
  </section>
</template>