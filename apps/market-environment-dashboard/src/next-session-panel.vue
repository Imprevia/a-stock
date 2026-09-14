<script setup lang="ts">
import type { NextSessionComparison } from './types'

const props = withDefaults(defineProps<{
  comparison: NextSessionComparison | null | undefined
  mode?: 'full' | 'summary'
}>(), { mode: 'full' })

const statusLabel = (status?: string) => ({ available: '已形成后验', pending: '等待下一日快照', insufficient: '对照不足' } as Record<string, string>)[status ?? ''] ?? '对照不足'
const deltaLabel = (value: number | null | undefined, suffix = '') => value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`
</script>

<template>
  <section v-if="comparison" class="panel next-session-panel" :class="{ 'synthesis-next': props.mode === 'summary' }">
    <div class="panel-heading">
      <div><span class="panel-kicker">{{ props.mode === 'summary' ? '精确下一交易日后验' : '精确下一交易日自动对照' }}</span><h2>{{ props.mode === 'summary' ? '综合结论变化' : (comparison.nextAsOf || '下一交易日待定') }}</h2></div>
      <span class="quality-badge" :class="comparison.status === 'available' ? 'ok' : 'missing'">{{ statusLabel(comparison.status) }}</span>
    </div>
    <template v-if="props.mode === 'summary'">
      <p v-if="comparison.status === 'available'">{{ comparison.current?.directionLabel || '--' }} → {{ comparison.next?.directionLabel || '--' }}；上涨占比 {{ deltaLabel(comparison.deltas.advanceRatio, ' 个百分点') }}，涨跌幅中位数 {{ deltaLabel(comparison.deltas.medianReturn, ' 个百分点') }}。其余原始七项证据请在 01 页查看。</p>
      <div v-else class="empty-inline">{{ comparison.warnings?.join('；') || '下一交易日后验尚未形成。' }}</div>
    </template>
    <template v-else>
      <div class="next-session-dates"><span>当前 {{ comparison.currentAsOf || comparison.requestedAsOf }}</span><span>下一日 {{ comparison.nextAsOf || '--' }}</span></div>
      <div v-if="comparison.status === 'available' && comparison.next" class="next-session-grid">
        <div><span>方向</span><strong>{{ comparison.current?.directionLabel || '--' }} → {{ comparison.next.directionLabel || '--' }}</strong></div>
        <div><span>上涨占比变化</span><strong>{{ deltaLabel(comparison.deltas.advanceRatio, ' 个百分点') }}</strong></div>
        <div><span>涨跌幅中位数变化</span><strong>{{ deltaLabel(comparison.deltas.medianReturn, ' 个百分点') }}</strong></div>
        <div><span>MA20 上方变化</span><strong>{{ deltaLabel(comparison.deltas.aboveMa20Count, ' 个') }}</strong></div>
        <div><span>成交额中位比值变化</span><strong>{{ deltaLabel(comparison.deltas.medianAmountRatio5, 'x') }}</strong></div>
        <div><span>放量上涨 / 下跌变化</span><strong>{{ deltaLabel(comparison.deltas.volumeBackedAdvanceCount) }} / {{ deltaLabel(comparison.deltas.volumeBackedDeclineCount) }}</strong></div>
      </div>
      <div v-else class="empty-inline">{{ comparison.warnings?.join('；') || '下一交易日精确证据尚未就绪，不使用自然日或其他日期替代。' }}</div>
    </template>
    <ul v-if="comparison.warnings?.length && props.mode === 'full'" class="data-gap-list">
      <li v-for="warning in comparison.warnings" :key="warning"><strong>对照边界</strong><span>{{ warning }}</span></li>
    </ul>
  </section>
</template>
