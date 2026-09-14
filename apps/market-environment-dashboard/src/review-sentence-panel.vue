<script setup lang="ts">
import { Copy } from 'lucide-vue-next'
import type { DataGap, ReviewSentence } from './types'

defineProps<{
  sentence: ReviewSentence | null | undefined
  dataGaps?: DataGap[]
}>()

const emit = defineEmits<{
  copy: []
}>()

const gapLabel = (reason?: string | null) => ({
  'insufficient-history': '历史窗口不足，暂无法计算分位',
  'missing-today': '当日行情尚未返回',
  'provider-failed': '行情供应商请求失败',
  'not-computable': '当前数据在数学上不可计算',
} as Record<string, string>)[reason ?? ''] ?? '数据不足'
</script>

<template>
  <section class="panel review-sentence-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">市场级句式模板</span><h2>今日复盘句 · 今日收束句</h2></div>
      <button class="text-button" type="button" :disabled="!sentence" @click="emit('copy')"><Copy :size="15" />复制完整句</button>
    </div>
    <p class="review-template">{{ sentence?.template || '市场级证据不足，暂无法生成句式。' }}</p>
    <div v-if="sentence?.segments?.length" class="review-segment-list">
      <div v-for="segment in sentence.segments" :key="segment.key" class="review-sentence-segment" :class="segment.status">
        <span>{{ segment.label }}</span><strong>{{ segment.value }}</strong><small v-if="segment.reason">{{ gapLabel(segment.reason) }}</small>
      </div>
    </div>
    <blockquote>{{ sentence?.fullSentence || '数据不足' }}</blockquote>
    <ul v-if="sentence?.warnings?.length" class="data-gap-list">
      <li v-for="warning in sentence.warnings" :key="warning"><strong>风险提示</strong><span>{{ warning }}</span></li>
    </ul>
    <ul v-if="dataGaps?.length" class="data-gap-list">
      <li v-for="gap in dataGaps" :key="`${gap.field}-${gap.reason}`"><strong>{{ gap.field }}</strong><span>{{ gapLabel(gap.reason) }}</span></li>
    </ul>
  </section>
</template>
