<script setup lang="ts">
/**
 * VolumeChartPanel — 60 日成交额柱图。
 *
 * Owns one echarts instance via useChartLifecycle; receives `dates` and
 * per-bar `amount` values from the parent. Redraws when inputs change.
 */
import { computed, ref } from 'vue'
import type { HistoryPoint } from '../../types'
import { useChartLifecycle } from '../../composables/useChartLifecycle'

const props = defineProps<{
  history: HistoryPoint[]
  dates: string[]
}>()

const chartElement = ref<HTMLElement | null>(null)

const option = computed(() => ({
  animation: false,
  grid: { top: 8, right: 18, bottom: 8, left: 62 },
  tooltip: { trigger: 'axis', confine: true, textStyle: { fontSize: 14 } },
  xAxis: {
    type: 'category',
    data: props.dates,
    axisLabel: { show: false },
    axisLine: { lineStyle: { color: '#edf0f2' } },
  },
  yAxis: {
    type: 'value',
    scale: true,
    splitNumber: 3,
    axisLabel: {
      color: '#a0a8b0',
      fontSize: 14,
      hideOverlap: true,
      formatter: (value: number) => `${(value / 100000000).toFixed(0)}亿`,
    },
    splitLine: { lineStyle: { color: '#f3f5f6' } },
  },
  series: [
    {
      name: '成交额',
      type: 'bar',
      data: props.history.map((item) => item.amount || null),
      barMaxWidth: 12,
      itemStyle: { color: '#b9d2d4' },
    },
  ],
}))

useChartLifecycle(
  chartElement,
  () => option.value as unknown as Record<string, unknown>,
  () => [props.history, props.dates],
)
</script>

<template>
  <div ref="chartElement" class="volume-chart" />
</template>