<script setup lang="ts">
/**
 * Document09AssessmentPage — 第 09 章 如何综合判断市场环境（唯一结论）。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '09'"`
 * block in Phase B-09 of frontend-component-split. Reads the assessment
 * from the core payload and the next-session comparison from
 * `market.nextSessionComparison`. Per spec the 09 route declares
 * meta.section = null — the page relies on already-loaded state and does
 * not trigger its own section prefetch.
 */
import { computed } from 'vue'

import NextSessionPanel from '../../next-session-panel.vue'
import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()

const assessment = computed(() => market.assessment)
const coverage = computed(() => market.chapter?.coverage)
</script>

<template>
  <section class="synthesis-grid">
    <article class="conclusion-block">
      <span class="panel-kicker">唯一结论</span>
      <div class="conclusion-state">
        <strong>{{ ctx.environmentLabel(assessment?.state) }}</strong>
        <em>{{ assessment?.score == null ? '分数不足' : `${assessment.score.toFixed(1)} 分` }}</em>
      </div>
      <p>置信度 {{ ctx.confidenceLabel(assessment?.confidence) }}，覆盖率 {{ coverage == null ? '--' : `${(coverage * 100).toFixed(0)}%` }}。经验阈值仍处于待回测状态。</p>
    </article>
    <article class="panel synthesis-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">证据链</span><h2>支持当前判断</h2></div>
      </div>
      <ul v-if="assessment?.evidence?.length">
        <li v-for="item in assessment.evidence" :key="item">{{ item }}</li>
      </ul>
      <div v-else class="empty-inline">暂无完整证据链</div>
    </article>
    <article class="panel synthesis-panel risk">
      <div class="panel-heading">
        <div><span class="panel-kicker">风险否决</span><h2>不可忽略的风险</h2></div>
      </div>
      <ul v-if="assessment?.risks?.length">
        <li v-for="item in assessment.risks" :key="item">{{ item }}</li>
      </ul>
      <div v-else class="empty-inline">当前未返回已触发的风险否决</div>
    </article>
    <article class="panel verification-panel">
      <div><span>次日确认</span><strong>{{ assessment?.nextConfirmation || '数据不足，等待新增证据' }}</strong></div>
      <div><span>失效条件</span><strong>{{ assessment?.invalidation || '尚未形成可追溯失效条件' }}</strong></div>
    </article>
  </section>

  <NextSessionPanel :comparison="market.nextSessionComparison" mode="summary" />
</template>